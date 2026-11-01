"""Verify the downloaded archive can be safely extracted and launched without Google."""

import hashlib
import json
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from photorestore.runtime import Runtime, safe_extract

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "photorestore/resources/browser.json").read_text())
archive = root / "vendor/browser.zip"
with archive.open("rb") as source:
    assert hashlib.file_digest(source, "sha256").hexdigest() == manifest["sha256"]
with tempfile.TemporaryDirectory(prefix="takeout-browser-test-") as tmp:
    runtime = Runtime(Path(tmp))
    extracted = runtime.root / manifest["revision"]
    extracted.mkdir(parents=True)
    safe_extract(archive, extracted)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=str(runtime.executable()), headless=True, chromium_sandbox=True
        )
        page = browser.new_page()
        page.route("**/*", lambda route: route.abort())
        page.set_content("<title>Offline component test</title><p>Ready</p>")
        assert page.title() == "Offline component test"
        browser.close()
print("Verified browser archive extraction and offline launch passed.")
