"""Hash distributable packages, excluding archives internal to application bundles."""

import hashlib
from pathlib import Path

root = Path("dist")
candidates = [*root.iterdir(), *(root / "installers").glob("*")]
artifacts = [
    p
    for p in candidates
    if p.is_file()
    and (p.suffix in (".zip", ".dmg", ".deb", ".AppImage") or p.name.endswith(("-setup.exe", ".tar.gz")))
]
with (root / "SHA256SUMS").open("w") as output:
    for path in sorted(artifacts):
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        output.write(digest + "  " + str(path.relative_to(root)) + "\n")
