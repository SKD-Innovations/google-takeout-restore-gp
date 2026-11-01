"""Build a deb plus portable archive. GTK/WebKit are declared system dependencies."""

import shutil
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
package = dist / "deb-root"
app = package / "opt/takeout-restore"
shutil.copytree(dist / "TakeoutRestore", app, dirs_exist_ok=True)
(package / "DEBIAN").mkdir(parents=True, exist_ok=True)
(package / "DEBIAN/control").write_text("""Package: takeout-restore
Version: 0.1.5
Architecture: amd64
Maintainer: Takeout Restore maintainers
Depends: libgtk-3-0, libwebkit2gtk-4.1-0, libgirepository-1.0-1, libnss3, libxss1, libasound2, libgbm1, libatk-bridge2.0-0, libdrm2
Description: Local Google Photos Takeout restoration workflow
""")
bin_dir = package / "usr/bin"
bin_dir.mkdir(parents=True, exist_ok=True)
(bin_dir / "takeout-restore").symlink_to("/opt/takeout-restore/TakeoutRestore")
applications = package / "usr/share/applications"
applications.mkdir(parents=True, exist_ok=True)
shutil.copy(root / "packaging/takeout-restore.desktop", applications)
icons = package / "usr/share/icons/hicolor/scalable/apps"
icons.mkdir(parents=True, exist_ok=True)
shutil.copy(root / "packaging/icon.svg", icons / "takeout-restore.svg")
subprocess.run(
    ["dpkg-deb", "--build", "--root-owner-group", str(package), str(dist / "TakeoutRestore-linux-x64.deb")],
    check=True,
)
shutil.make_archive(str(dist / "TakeoutRestore-linux-x64-portable"), "gztar", dist, "TakeoutRestore")
# AppImage packages the same payload. The .deb is preferred on a clean Ubuntu install:
# it resolves WebKitGTK's system dependencies through the OS package manager.
import hashlib
import json
import os
import urllib.request

lock = json.loads((root / "packaging/vendor-lock.json").read_text())


def fetch(name, filename):
    entry = lock[name]
    path = root / "vendor" / filename
    path.parent.mkdir(exist_ok=True)
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        with urllib.request.urlopen(entry["url"], timeout=120) as response:
            path.write_bytes(response.read())
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        raise RuntimeError("Packaging component checksum mismatch: " + name)
    path.chmod(0o755)
    return path


appdir = dist / "TakeoutRestore.AppDir"
appdir.mkdir(exist_ok=True)
shutil.copytree(dist / "TakeoutRestore", appdir / "app", dirs_exist_ok=True)
(appdir / "AppRun").write_text(
    '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\nexec "$HERE/app/TakeoutRestore" "$@"\n'
)
(appdir / "AppRun").chmod(0o755)
desktop = (
    (root / "packaging/takeout-restore.desktop").read_text().replace("Exec=takeout-restore", "Exec=AppRun")
)
(appdir / "takeout-restore.desktop").write_text(desktop)
shutil.copy(root / "packaging/icon.svg", appdir / "takeout-restore.svg")
shutil.copy(root / "packaging/icon.svg", appdir / ".DirIcon")
tool = fetch("appimagetool", "appimagetool.AppImage")
runtime = fetch("appimage_runtime", "appimage-runtime")
subprocess.run(
    [
        str(tool),
        "--appimage-extract-and-run",
        "--runtime-file",
        str(runtime),
        str(appdir),
        str(dist / "TakeoutRestore-linux-x64.AppImage"),
    ],
    check=True,
    env={**os.environ, "ARCH": "x86_64"},
)
