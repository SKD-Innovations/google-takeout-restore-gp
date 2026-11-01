"""Produce bundled ExifTool, including a signable Perl runtime on Unix build machines."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
lock = json.loads((root / "packaging/vendor-lock.json").read_text())
windows = sys.platform == "win32"
entry = lock["exiftool_windows" if windows else "exiftool_source"]
vendor = root / "vendor"
vendor.mkdir(exist_ok=True)
archive = vendor / ("exiftool.zip" if windows else "exiftool.tar.gz")
if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
    with urllib.request.urlopen(entry["url"], timeout=120) as response:
        archive.write_bytes(response.read(100 * 1024 * 1024))
if hashlib.sha256(archive.read_bytes()).hexdigest() != entry["sha256"]:
    raise RuntimeError("ExifTool checksum mismatch")
work = vendor / "exiftool-source"
work.mkdir(exist_ok=True)
out = root / "photorestore/resources/exiftool"
out.mkdir(parents=True, exist_ok=True)
if windows:
    with zipfile.ZipFile(archive) as z:
        # The pinned vendor archive is also checked for traversal.
        for name in z.namelist():
            if not (work / name).resolve().is_relative_to(work.resolve()):
                raise RuntimeError("Unsafe archive path")
        z.extractall(work)
    executable = next(work.rglob("exiftool(-k).exe"))
    shutil.copytree(executable.parent, out, dirs_exist_ok=True)
    (out / "exiftool(-k).exe").rename(out / "exiftool.exe")
else:
    with tarfile.open(archive) as tar:
        tar.extractall(work, filter="data")
    source = next(work.glob("Image-ExifTool-*"))
    if not (out / "perl/bin/perl").exists():
        subprocess.run([sys.executable, str(root / "scripts/prepare_perl.py")], check=True)
    shutil.copy2(source / "exiftool", out / "exiftool")
    shutil.copytree(source / "lib", out / "lib", dirs_exist_ok=True)
    shutil.copy2(source / "README", out / "EXIFTOOL-README.txt")
    (out / "exiftool").chmod(0o755)
exe = out / ("exiftool.exe" if windows else "exiftool")
sys.path.insert(0, str(root))
from photorestore.metadata import exiftool_command, clean_environment

version = subprocess.run(
    [*exiftool_command(exe), "-config", "", "-ver"],
    env=clean_environment(),
    capture_output=True,
    text=True,
    check=True,
).stdout.strip()
if version != "13.60":
    raise RuntimeError("Unexpected ExifTool version: " + version)
(out.parent / "exiftool.json").write_text(
    json.dumps({"version": version, "sha256": hashlib.sha256(exe.read_bytes()).hexdigest()}, indent=2) + "\n"
)
print("Bundled ExifTool", version, "including its Perl runtime")
