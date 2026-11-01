"""Build-time only: derive the browser URL from pinned Playwright and embed its checksum.
The browser is NOT added to the installer. Its hash is sealed into the signed application.
"""

import hashlib
import json
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = root / "photorestore" / "resources"
output.mkdir(parents=True, exist_ok=True)
info = subprocess.run(
    [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium", "--no-shell"],
    capture_output=True,
    text=True,
    check=True,
).stdout
url = re.search(r"Download url:\s+(https://\S+)", info).group(1)
revision = re.search(r"chromium v(\d+)", info).group(1)
cache = root / "vendor" / "browser.zip"
cache.parent.mkdir(exist_ok=True)
digest = hashlib.sha256()
with urllib.request.urlopen(url, timeout=120) as response, cache.open("wb") as target:
    while chunk := response.read(1024 * 1024):
        target.write(chunk)
        digest.update(chunk)
with zipfile.ZipFile(cache) as z:
    choices = [
        n
        for n in z.namelist()
        if n.endswith(("/chrome", "/chrome.exe", "/Contents/MacOS/Google Chrome for Testing"))
    ]
    if len(choices) != 1:
        raise RuntimeError("Expected exactly one browser executable: " + str(choices))
manifest = {"url": url, "revision": revision, "sha256": digest.hexdigest(), "executable": choices[0]}
(output / "browser.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Pinned browser revision", revision, "SHA-256", digest.hexdigest())
