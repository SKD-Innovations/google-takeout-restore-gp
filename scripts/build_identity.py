"""Generate a reproducible source/dependency fingerprint; never read local credentials."""

import hashlib
import json
import platform
import sys
import tomllib
from pathlib import Path


def write_identity(root):
    paths = []
    for directory in ("photorestore", "packaging", "scripts"):
        paths.extend(
            p
            for p in (root / directory).rglob("*")
            if p.is_file()
            and p.suffix in (".py", ".js", ".html", ".css", ".swift", ".spec", ".plist", ".json")
            and not any(x in ("resources", "__pycache__") for x in p.relative_to(root).parts)
        )
    paths.extend(
        root / name for name in ("pyproject.toml", "requirements.txt", "requirements-dev.txt", "USAGE.md")
    )
    paths.extend(root / "photorestore/resources" / name for name in ("browser.json", "exiftool.json"))
    hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}
    payload = {
        "version": tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"],
        "target": platform.system() + "-" + platform.machine(),
        "python": platform.python_version(),
        "files": hashes,
    }
    payload["build_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    destination = root / "photorestore/resources/build.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


if __name__ == "__main__":
    manifest = write_identity(Path(__file__).resolve().parents[1])
    print("Build fingerprint:", manifest["build_id"])
