"""Exercise the original CDP flow offline with a disposable, encrypted Chrome profile."""

import tempfile
import threading
import time
from pathlib import Path
from cryptography.fernet import Fernet
from playwright.sync_api import sync_playwright
from photorestore.chrome import ManagedChrome, installed_chrome
from photorestore.runtime import Runtime, safe_extract

with tempfile.TemporaryDirectory(prefix="takeout-cdp-test-") as tmp:
    root = Path(tmp)
    key = Fernet.generate_key()
    profile = root / "profile"
    profile.mkdir()
    runtime = Runtime(root)
    if not installed_chrome():
        manifest = runtime.manifest()
        extracted = runtime.root / manifest["revision"]
        extracted.mkdir(parents=True)
        safe_extract(Path(__file__).resolve().parents[1] / "vendor/browser.zip", extracted)
    for attempt in (1, 2):
        chrome = ManagedChrome(runtime, profile, key, threading.Event())
        endpoint = chrome.start()
        assert endpoint.startswith("ws://127.0.0.1:")
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
            if attempt == 1:
                context.add_cookies(
                    [
                        {
                            "name": "offline-test",
                            "value": "private-marker",
                            "domain": "example.test",
                            "path": "/",
                            "expires": time.time() + 86400,
                        }
                    ]
                )
            else:
                assert any(
                    c["name"] == "offline-test" and c["value"] == "private-marker" for c in context.cookies()
                )
            page = context.new_page()
            page.goto("data:text/html,<title>Offline CDP test</title>")
            assert page.title() == "Offline CDP test"
            browser.new_browser_cdp_session().send("Browser.close")
        chrome.close()
        assert not chrome.work.exists() and chrome.archive.is_file()
        assert b"private-marker" not in chrome.archive.read_bytes()
print("CDP attach, default-context reuse, encrypted profile and cookie persistence passed offline.")
