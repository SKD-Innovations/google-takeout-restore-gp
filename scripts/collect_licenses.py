"""Include installed dependency license texts in release resources."""

import importlib.metadata
import json
import shutil
from pathlib import Path

out = Path("photorestore/resources/licenses")
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
records = []
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    records.append(
        {
            "name": name,
            "version": dist.version,
            "license": dist.metadata.get("License-Expression")
            or dist.metadata.get("License")
            or "See bundled license or upstream project",
            "url": dist.metadata.get("Home-page"),
        }
    )
    for file in dist.files or []:
        if any(
            part.lower().startswith(("license", "copying", "notice", "authors"))
            for part in Path(str(file)).parts
        ):
            path = Path(dist.locate_file(file))
            if (
                path.is_file()
                and path.suffix.lower() not in (".so", ".dll", ".dylib", ".pyd", ".py", ".pyc", ".exe")
                and path.stat().st_size < 2_000_000
            ):
                target = out / name / Path(str(file)).name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
(out / "dependencies.json").write_text(json.dumps(sorted(records, key=lambda r: r["name"].lower()), indent=2))
shutil.copy2("packaging/ARTISTIC-1.0.txt", out / "PERL-ARTISTIC-1.0.txt")
