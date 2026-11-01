"""Build a signable Perl runtime for ExifTool without requiring a user-installed Perl.
Build in a whitespace-free temporary directory: Perl's build scripts do not reliably
handle spaces in source or installation prefixes. Runtime include paths are supplied
by exiftool_command(), so the copied interpreter and libraries remain relocatable.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
if sys.platform == "win32":
    raise SystemExit("Windows ExifTool already includes Perl")
lock = json.loads((root / "packaging/vendor-lock.json").read_text())["perl"]
vendor = root / "vendor"
vendor.mkdir(exist_ok=True)
archive = vendor / "perl.tar.gz"
if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != lock["sha256"]:
    with urllib.request.urlopen(lock["url"], timeout=120) as response:
        archive.write_bytes(response.read())
if hashlib.sha256(archive.read_bytes()).hexdigest() != lock["sha256"]:
    raise RuntimeError("Perl checksum mismatch")
output = root / "photorestore/resources/exiftool/perl"
if not (output / ".complete").is_file():
    with tempfile.TemporaryDirectory(prefix="takeout-perl-") as tmp:
        work = Path(tmp)
        if " " in str(work):
            raise RuntimeError("Set TMPDIR to a whitespace-free build directory")
        with tarfile.open(archive) as tar:
            tar.extractall(work, filter="data")
        source = next(work.glob("perl-*"))
        installed = work / "installed"
        args = [
            "sh",
            "Configure",
            "-des",
            "-Uuseshrplib",
            "-Dprefix=" + str(installed),
            "-Dman1dir=none",
            "-Dman3dir=none",
        ]
        if sys.platform == "darwin":
            # Upstream Perl fix 1a6f4bf: SDK declarations can outpace deployment targets.
            args.extend(
                [
                    "-Dccflags=-mmacosx-version-min=13.0",
                    "-Dldflags=-mmacosx-version-min=13.0",
                    "-Ud_dup3",
                    "-Ud_pipe2",
                ]
            )
        subprocess.run(args, cwd=source, check=True)
        subprocess.run(["make", "-j", str(min(os.cpu_count() or 2, 8))], cwd=source, check=True)
        subprocess.run(["make", "install"], cwd=source, check=True)
        for path in (installed / "bin").iterdir():
            if path.name != "perl":
                path.unlink()
        for path in installed.rglob("*.a"):
            path.unlink()
        shutil.copy2(source / "Artistic", installed / "Artistic.txt")
        shutil.rmtree(output, ignore_errors=True)
        shutil.copytree(installed, output)
        (output / ".complete").write_text(lock["sha256"])
print("Built signable bundled Perl")

# Documentation and developer command-line utilities are unnecessary in the app.
for path in (output / 'bin').iterdir():
    if path.name != 'perl':
        path.unlink()
for path in output.rglob('*.pod'):
    path.unlink()
