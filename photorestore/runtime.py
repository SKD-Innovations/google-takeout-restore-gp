"""Release-pinned browser download, verified before safe atomic extraction."""

import hashlib
import errno
import json
import os
import shutil
import ssl
import certifi
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from .errors import AppError

RESOURCES = Path(__file__).parent / "resources"
ALLOWED_HOSTS = {
    "cdn.playwright.dev",
    "playwright.download.prss.microsoft.com",
    "storage.googleapis.com",
    "cdn.playwright.azureedge.net",
}


def resource_path(name):
    return RESOURCES / name


def safe_extract(archive, target, max_bytes=8 * 1024**3):
    total = 0
    links = []
    with zipfile.ZipFile(archive) as z:
        for info in z.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename or ":" in info.filename:
                raise AppError("GPP-406")
            dest = target.joinpath(*name.parts)
            if not dest.resolve().is_relative_to(target.resolve()):
                raise AppError("GPP-406")
            mode = info.external_attr >> 16
            total += info.file_size
            if total > max_bytes:
                raise AppError("GPP-406")
            if stat.S_ISLNK(mode):
                if info.file_size > 4096:
                    raise AppError("GPP-406")
                link = z.read(info).decode("utf-8")
                if Path(link).is_absolute() or not (dest.parent / link).resolve().is_relative_to(
                    target.resolve()
                ):
                    raise AppError("GPP-406")
                links.append((dest, link))
            elif info.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, dest.open("xb") as out:
                    shutil.copyfileobj(src, out, 1024 * 1024)
                dest.chmod(0o755 if mode & 0o111 else 0o644)
        # Delayed links prevent extraction through attacker-controlled symlinks.
        for dest, link in links:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.symlink_to(link)
        for dest, _ in links:
            if not dest.resolve().is_relative_to(target.resolve()):
                raise AppError("GPP-406")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def validate_url(url):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS or parts.username or parts.password:
        raise AppError("GPP-406")


class Runtime:
    def __init__(self, data_dir, manifest=None):
        self.root = data_dir / "runtime"
        self.manifest_path = manifest or resource_path("browser.json")

    def manifest(self):
        try:
            result = json.loads(self.manifest_path.read_text())
            if len(result["sha256"]) != 64 or not result["executable"] or not result["revision"].isdigit():
                raise ValueError()
            return result
        except (OSError, ValueError, KeyError) as exc:
            raise AppError("GPP-405") from exc

    def executable(self):
        m = self.manifest()
        path = self.root / m["revision"] / m["executable"]
        if not path.is_file():
            raise AppError("GPP-405")
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise AppError("GPP-406")
        return path

    def ready(self):
        try:
            self.executable()
            return True
        except AppError:
            return False

    def install(self, stop, progress):
        m = self.manifest()
        validate_url(m["url"])
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        final = self.root / m["revision"]
        if self.ready():
            return
        with tempfile.TemporaryDirectory(dir=self.root, prefix="download-") as tmp:
            work = Path(tmp)
            archive = work / "browser.zip"
            digest, size = hashlib.sha256(), 0
            opener = urllib.request.build_opener(
                SafeRedirect(),
                urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())),
            )
            try:
                with opener.open(m["url"], timeout=60) as response, archive.open("wb") as output:
                    total = int(response.headers.get("Content-Length", 0))
                    while chunk := response.read(1024 * 1024):
                        if stop.is_set():
                            from .scanner import Cancelled

                            raise Cancelled()
                        size += len(chunk)
                        if size > 2 * 1024**3:
                            raise AppError("GPP-406")
                        output.write(chunk)
                        digest.update(chunk)
                        progress("Downloading browser", round(size / total * 100) if total else 0)
            except OSError as exc:
                raise AppError("GPP-407") from exc
            if digest.hexdigest() != m["sha256"]:
                raise AppError("GPP-406")
            progress("Verifying and installing browser", 100)
            extracted = work / "extracted"
            extracted.mkdir()
            try:
                safe_extract(archive, extracted)
            except OSError as exc:
                raise AppError("GPP-204" if exc.errno == errno.ENOSPC else "GPP-406") from exc
            except (zipfile.BadZipFile, RuntimeError) as exc:
                raise AppError("GPP-406") from exc
            if not (extracted / m["executable"]).is_file():
                raise AppError("GPP-406")
            if final.exists():
                shutil.rmtree(final)
            extracted.replace(final)


def exiftool_path():
    filename = "exiftool.exe" if sys.platform == "win32" else "exiftool"
    bundled = resource_path("exiftool") / filename
    if bundled.is_file():
        return bundled
    # Explicit development override only. Packaged apps never trust PATH.
    if not getattr(sys, "frozen", False) and os.environ.get("TAKEOUT_DEV_EXIFTOOL"):
        return Path(os.environ["TAKEOUT_DEV_EXIFTOOL"]).resolve()
    raise AppError("GPP-303")
