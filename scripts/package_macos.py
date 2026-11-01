"""Build a designed Finder installation image and a portable app archive."""

import argparse
import platform
import plistlib
import subprocess
import tomllib
import tempfile
from ds_store import DSStore
from pathlib import Path
import dmgbuild

root = Path(__file__).resolve().parents[1]
dist = root / "dist"
app = dist / "Takeout Restore.app"
version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
arch = "arm64" if platform.machine() == "arm64" else "x64"
parser = argparse.ArgumentParser()
parser.add_argument("--target", default=f"macos-{arch}")
args = parser.parse_args()
info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
for key, value in {
    "CFBundleIdentifier": "org.takeoutrestore.desktop",
    "CFBundlePackageType": "APPL",
    "CFBundleName": "Takeout Restore",
    "CFBundleShortVersionString": version,
}.items():
    if info.get(key) != value:
        raise RuntimeError(f"Invalid bundle metadata: {key}")
if not (app / "Contents/MacOS" / info["CFBundleExecutable"]).is_file():
    raise RuntimeError("Application executable is missing")
output = dist / f"TakeoutRestore-{version}-{args.target}-preview.dmg"
dmgbuild.build_dmg(
    str(output),
    "Takeout Restore",
    settings={
        "files": [str(app)],
        "symlinks": {"Applications": "/Applications"},
        "badge_icon": str(root / "packaging/icon.icns"),
        "background": str(root / "packaging/dmg-background.png"),
        "format": "UDZO",
        "filesystem": "HFS+",
        "window_rect": ((180, 120), (660, 440)),
        "default_view": "icon-view",
        "icon_size": 96,
        "text_size": 13,
        "icon_locations": {"Takeout Restore.app": (175, 210), "Applications": (485, 210)},
        "hide_extensions": [],  # FinderInfo on a signed app invalidates strict verification (Apple QA1940).
        "show_toolbar": False,
        "show_status_bar": False,
        "show_sidebar": False,
        "include_icon_view_settings": True,
        "include_list_view_settings": False,
    },
)
# Verify the distributed copy too: Finder attributes added during packaging can
# invalidate a signature even when the original .app passed verification.
with tempfile.TemporaryDirectory(prefix="dmg-verify-", dir=dist) as tmp:
    mount = Path(tmp)
    subprocess.run(
        ["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mount), str(output)],
        capture_output=True,
        check=True,
    )
    try:
        if (mount / "Applications").readlink() != Path("/Applications"):
            raise RuntimeError("Incorrect Applications shortcut")
        with DSStore.open(str(mount / ".DS_Store"), "r") as store:
            if store["Takeout Restore.app"]["Iloc"] != (175, 210) or store["Applications"]["Iloc"] != (
                485,
                210,
            ):
                raise RuntimeError("Missing Finder icon positions")
            if store["."]["icvp"]["backgroundType"] != 2:
                raise RuntimeError("Missing Finder installation background")
        subprocess.run(
            ["codesign", "--verify", "--deep", "--strict", str(mount / "Takeout Restore.app")], check=True
        )
    finally:
        subprocess.run(["hdiutil", "detach", str(mount)], capture_output=True, check=True)

subprocess.run(
    [
        "ditto",
        "-c",
        "-k",
        "--sequesterRsrc",
        "--keepParent",
        str(app),
        str(dist / f"TakeoutRestore-{version}-{args.target}-portable.zip"),
    ],
    check=True,
)
print("Created", output.name)
