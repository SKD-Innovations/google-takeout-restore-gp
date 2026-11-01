"""CI-only ephemeral keychain and App Store Connect API-key notarization."""

import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
from pathlib import Path


def run(args, label):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        # Never print a command containing a password or private-key material.
        raise RuntimeError(label + " failed; review the signing setup in docs/SIGNING.md")
    return result.stdout


def env(name):
    value = os.environ.get(name)
    if not value:
        raise RuntimeError("Required signing setting missing: " + name)
    return value


root = Path(env("RUNNER_TEMP")) / "takeout-signing"
mode = sys.argv[1]
if mode == "setup":
    root.mkdir(mode=0o700, exist_ok=True)
    cert = root / "developer-id.p12"
    cert.write_bytes(base64.b64decode(env("MAC_CERTIFICATE_P12_BASE64"), validate=True))
    cert.chmod(0o600)
    keychain = root / "build.keychain-db"
    password = secrets.token_urlsafe(32)
    original = run(["security", "list-keychains", "-d", "user"], "Read keychain list")
    (root / "keychains.json").write_text(
        json.dumps([s.strip().strip('"') for s in original.splitlines() if s.strip()])
    )
    run(["security", "create-keychain", "-p", password, str(keychain)], "Create temporary keychain")
    run(["security", "set-keychain-settings", "-lut", "21600", str(keychain)], "Configure keychain")
    run(["security", "unlock-keychain", "-p", password, str(keychain)], "Unlock keychain")
    run(
        [
            "security",
            "import",
            str(cert),
            "-k",
            str(keychain),
            "-P",
            env("MAC_CERTIFICATE_PASSWORD"),
            "-T",
            "/usr/bin/codesign",
        ],
        "Import certificate",
    )
    run(
        [
            "security",
            "set-key-partition-list",
            "-S",
            "apple-tool:,apple:",
            "-s",
            "-k",
            password,
            str(keychain),
        ],
        "Grant signing access",
    )
    originals = json.loads((root / "keychains.json").read_text())
    run(["security", "list-keychains", "-d", "user", "-s", str(keychain), *originals], "Select keychain")
    cert.unlink()
elif mode == "notarize":
    root.mkdir(mode=0o700, exist_ok=True)
    key = root / "AuthKey.p8"
    key.write_bytes(base64.b64decode(env("APPLE_API_KEY_P8_BASE64"), validate=True))
    key.chmod(0o600)
    artifact = Path(sys.argv[2])
    try:
        result = run(
            [
                "xcrun",
                "notarytool",
                "submit",
                str(artifact),
                "--key",
                str(key),
                "--key-id",
                env("APPLE_API_KEY_ID"),
                "--issuer",
                env("APPLE_API_ISSUER"),
                "--wait",
                "--timeout",
                "30m",
                "--output-format",
                "json",
            ],
            "Notarization",
        )
        if json.loads(result).get("status") != "Accepted":
            raise RuntimeError("Apple did not accept the artifact for notarization")
        run(["xcrun", "stapler", "staple", str(artifact)], "Staple notarization ticket")
        run(["xcrun", "stapler", "validate", str(artifact)], "Validate notarization ticket")
    finally:
        key.unlink(missing_ok=True)
elif mode == "cleanup":
    if (root / "keychains.json").exists():
        originals = json.loads((root / "keychains.json").read_text())
        run(["security", "list-keychains", "-d", "user", "-s", *originals], "Restore keychain list")
    if (root / "build.keychain-db").exists():
        run(["security", "delete-keychain", str(root / "build.keychain-db")], "Delete temporary keychain")
    shutil.rmtree(root, ignore_errors=True)
else:
    raise RuntimeError("Unknown signing operation")
