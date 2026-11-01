"""Targeted Launch Services registration using Apple's public API."""

import ctypes
import json
import plistlib
import sys
import subprocess
from pathlib import Path

BUNDLE_ID = "org.takeoutrestore.desktop"


def device_verification_available():
    return sys.platform == "darwin" and (Path(__file__).parent / "resources/native/AuthorizeReset").is_file()


def verify_device_owner():
    if not device_verification_available():
        return False
    try:
        result = subprocess.run(  # noqa: S603 — fixed bundled executable, no frontend arguments
            [str(Path(__file__).parent / "resources/native/AuthorizeReset")],
            timeout=130,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def installed_bundle():
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    bundle = Path(sys.executable).parents[2]
    if bundle.parent not in (Path("/Applications"), Path.home() / "Applications"):
        return None
    try:
        info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
        if info.get("CFBundleIdentifier") == BUNDLE_ID and info.get("CFBundlePackageType") == "APPL":
            return bundle
    except (OSError, ValueError):
        pass
    return None


def trash_installed_app():
    from .errors import AppError

    bundle = installed_bundle()
    if not bundle:
        raise AppError("GPP-112")
    # Apple's public Trash API preserves the standard Finder undo/recovery behavior.
    from Foundation import NSFileManager, NSURL

    result = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
        NSURL.fileURLWithPath_(str(bundle)), None, None
    )
    if not result[0]:
        raise AppError("GPP-111")


def register_bundle(bundle):
    if sys.platform != "darwin":
        return False
    try:
        info = plistlib.loads((bundle / "Contents/Info.plist").read_bytes())
        if info.get("CFBundleIdentifier") != BUNDLE_ID or info.get("CFBundlePackageType") != "APPL":
            return False
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        ls = ctypes.CDLL("/System/Library/Frameworks/CoreServices.framework/CoreServices")
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_bool,
        ]
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        ls.LSRegisterURL.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        ls.LSRegisterURL.restype = ctypes.c_int32
        path = bytes(bundle.resolve())
        url = cf.CFURLCreateFromFileSystemRepresentation(None, path, len(path), True)
        if not url:
            return False
        try:
            return ls.LSRegisterURL(url, True) == 0
        finally:
            cf.CFRelease(url)
    except (OSError, ValueError, AttributeError):
        return False


def register_installed_app(data_root):
    """Refresh only this installed app, once per version/path. No Spotlight-index changes."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False):
        return None
    bundle = Path(sys.executable).parents[2]
    if bundle.parent not in (Path("/Applications"), Path.home() / "Applications"):
        return None
    from . import __version__

    marker = data_root / "mac-registration.json"
    expected = {"version": __version__, "bundle": str(bundle)}
    try:
        if marker.exists() and json.loads(marker.read_text()) == expected:
            return None
        if register_bundle(bundle):
            marker.write_text(json.dumps(expected))
            return True
    except (OSError, ValueError):
        pass
    return False
