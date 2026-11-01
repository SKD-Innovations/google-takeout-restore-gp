"""Launch a dedicated Chrome process and attach over loopback CDP, as the original pipeline did.
Profiles are unlocked only during an operation and encrypted again after Chrome exits.
"""

import base64
import http.client
import json
from urllib.parse import urlsplit
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .errors import AppError
from .runtime import safe_extract
from .scanner import Cancelled

HEADER = b"TRCP1"
CHUNK = 1024 * 1024
MAX_ARCHIVE = 2 * 1024**3
EXCLUDED = {
    "Cache",
    "Code Cache",
    "GPUCache",
    "ShaderCache",
    "GrShaderCache",
    "Crashpad",
    "BrowserMetrics",
    "CacheStorage",
}


def installed_chrome():
    candidates = []
    if sys.platform == "darwin":
        candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        ]
    elif sys.platform == "win32":
        for name in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
            if os.environ.get(name):
                candidates.append(Path(os.environ[name]) / "Google/Chrome/Application/chrome.exe")
    else:
        candidates = [
            Path("/opt/google/chrome/chrome"),
            Path("/usr/bin/google-chrome-stable"),
            Path("/usr/bin/google-chrome"),
        ]
    return next((p for p in candidates if p.is_file()), None)


def encrypt_archive(source, target, key):
    nonce = os.urandom(12)
    encryptor = Cipher(algorithms.AES(base64.urlsafe_b64decode(key)), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(HEADER)
    temporary = target.with_suffix(".tmp")
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            temporary.chmod(0o600)
            dst.write(HEADER + nonce)
            while data := src.read(CHUNK):
                dst.write(encryptor.update(data))
            dst.write(encryptor.finalize())
            dst.write(encryptor.tag)
            dst.flush()
            os.fsync(dst.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def decrypt_archive(source, target, key):
    try:
        size = source.stat().st_size
        if not len(HEADER) + 12 + 16 <= size <= MAX_ARCHIVE:
            raise AppError("GPP-408")
        with source.open("rb") as src:
            if src.read(len(HEADER)) != HEADER:
                raise AppError("GPP-408")
            nonce = src.read(12)
            src.seek(-16, 2)
            tag = src.read(16)
            decryptor = Cipher(
                algorithms.AES(base64.urlsafe_b64decode(key)), modes.GCM(nonce, tag)
            ).decryptor()
            decryptor.authenticate_additional_data(HEADER)
            src.seek(len(HEADER) + 12)
            remaining = size - len(HEADER) - 12 - 16
            with target.open("wb") as dst:
                while remaining:
                    data = src.read(min(CHUNK, remaining))
                    if not data:
                        raise AppError("GPP-408")
                    remaining -= len(data)
                    dst.write(decryptor.update(data))
                # Authenticate before allowing any archive contents to be extracted.
                dst.write(decryptor.finalize())
    except (InvalidTag, ValueError, OSError) as exc:
        target.unlink(missing_ok=True)
        raise AppError("GPP-408") from exc


class ManagedChrome:
    def __init__(self, runtime, profile, key, stop):
        self.runtime, self.profile, self.key, self.stop = runtime, profile, key, stop
        self.work = profile / "chrome-work"
        self.archive = profile / "chrome.profile.enc"
        self.process = None
        self.started = False

    def start(self, url="about:blank"):
        executable = installed_chrome() or self.runtime.executable()
        # This path belongs only to this application's authenticated local user.
        shutil.rmtree(self.work, ignore_errors=True)
        self.work.mkdir(mode=0o700)
        try:
            if self.archive.exists():
                with tempfile.TemporaryDirectory(dir=self.profile, prefix="chrome-unlock-") as tmp:
                    zipped = Path(tmp) / "profile.zip"
                    decrypt_archive(self.archive, zipped, self.key)
                    try:
                        safe_extract(zipped, self.work, max_bytes=4 * 1024**3)
                    except (zipfile.BadZipFile, AppError, OSError) as exc:
                        raise AppError("GPP-408") from exc
            # Match the original script's explicit nonzero CDP port. Choose an unused
            # loopback port instead of hard-coding 9222, which another app may own.
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            self.process = subprocess.Popen(  # noqa: S603 -- discovered browser, fixed argument vector
                [
                    str(executable),
                    "--user-data-dir=" + str(self.work.resolve()),
                    "--remote-debugging-address=127.0.0.1",
                    f"--remote-debugging-port={port}",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disk-cache-size=33554432",
                    "--media-cache-size=33554432",
                    url,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.started = True
            deadline = time.monotonic() + 45
            active = self.work / "DevToolsActivePort"
            while time.monotonic() < deadline:
                if self.stop.is_set():
                    raise Cancelled()
                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
                try:
                    connection.request("GET", "/json/version")
                    response = connection.getresponse()
                    if response.status == 200:
                        info = json.loads(response.read(8192))
                        endpoint = urlsplit(info.get("webSocketDebuggerUrl", ""))
                        path = endpoint.path
                        if (
                            endpoint.scheme == "ws"
                            and endpoint.hostname in ("127.0.0.1", "localhost")
                            and endpoint.port == port
                            and not endpoint.username
                            and not endpoint.password
                            and path.startswith("/devtools/browser/")
                            and all(c.isalnum() or c in "/-" for c in path)
                        ):
                            active.write_text(f"{port}\n{path}\n")
                            return f"ws://127.0.0.1:{port}{path}"
                except (OSError, ValueError, http.client.HTTPException):
                    pass
                finally:
                    connection.close()
                if self.process.poll() is not None:
                    raise AppError("GPP-411")
                self.stop.wait(0.1)
            raise AppError("GPP-411")
        except BaseException:
            self.close(save=False)
            raise

    def close(self, save=True):
        try:
            if self.process and self.process.poll() is None:
                # The caller first requests Browser.close over CDP for a clean Chrome shutdown.
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
            if save and self.started and self.work.is_dir():
                with tempfile.TemporaryDirectory(dir=self.profile, prefix="chrome-lock-") as tmp:
                    zipped = Path(tmp) / "profile.zip"
                    with zipfile.ZipFile(zipped, "w", zipfile.ZIP_DEFLATED) as z:
                        for directory, folders, files in os.walk(self.work, followlinks=False):
                            folders[:] = [
                                n
                                for n in folders
                                if n not in EXCLUDED and not (Path(directory) / n).is_symlink()
                            ]
                            for name in files:
                                path = Path(directory) / name
                                if (
                                    name.startswith("Singleton")
                                    or name in ("DevToolsActivePort", "lockfile")
                                    or path.is_symlink()
                                    or not path.is_file()
                                ):
                                    continue
                                z.write(path, str(path.relative_to(self.work)))
                    if zipped.stat().st_size > MAX_ARCHIVE - 64:
                        raise AppError("GPP-412")
                    encrypt_archive(zipped, self.archive, self.key)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            raise AppError("GPP-412") from exc
        finally:
            self.started = False
            shutil.rmtree(self.work, ignore_errors=True)


def cleanup_unlocked_profiles(root):
    """Called under the application's single-instance lock after an interrupted process."""
    profiles = root / "profiles"
    if not profiles.is_dir():
        return
    for profile in profiles.iterdir():
        if (
            profile.is_symlink()
            or not profile.is_dir()
            or len(profile.name) != 32
            or any(c not in "0123456789abcdef" for c in profile.name)
        ):
            continue
        for path in profile.iterdir():
            if path.name == "chrome-work" or path.name.startswith(("chrome-unlock-", "chrome-lock-")):
                if path.name == "chrome-work" and not path.is_symlink():
                    active = path / "DevToolsActivePort"
                    if active.is_file():
                        lines = active.read_text().splitlines()
                        if lines and lines[0].isascii() and lines[0].isdigit() and 0 < int(lines[0]) <= 65535:
                            try:
                                with socket.create_connection(("127.0.0.1", int(lines[0])), timeout=0.2):
                                    raise AppError("GPP-413")
                            except OSError:
                                pass
                if path.is_symlink():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
