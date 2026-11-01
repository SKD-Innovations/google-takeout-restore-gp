"""Package maintained source only, never local credentials, caches or vendor binaries."""

import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = [
    root / name
    for name in (
        "README.md",
        "USAGE.md",
        "SECURITY.md",
        "LICENSE",
        "NOTICE",
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "pipeline.py",
        ".gitignore",
    )
]
for name in ("photorestore", "tests", "scripts", "packaging", "docs", ".github"):
    for path in (root / name).rglob("*"):
        if path.is_file() and not any(
            part in ("__pycache__", "resources", ".DS_Store") for part in path.relative_to(root).parts
        ):
            files.append(path)
output = root / "dist/TakeoutRestore-source-preview.zip"
output.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, Path("TakeoutRestore") / path.relative_to(root))
print("Packaged", len(files), "source files")
