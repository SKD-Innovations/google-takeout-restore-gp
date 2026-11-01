"""Exercise the actual HTML and authenticated service against disposable local data.
No Google requests or real user files. Run with --chrome to use installed Chrome for testing.
"""

import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock
from photorestore import macos
from playwright.sync_api import sync_playwright
from photorestore.app import build_html
from photorestore.service import Service

parser = argparse.ArgumentParser()
parser.add_argument("--chrome", action="store_true")
args = parser.parse_args()
with tempfile.TemporaryDirectory() as tmp, sync_playwright() as pw:
    root = Path(tmp)
    service = Service(root / "data")
    browser = pw.chromium.launch(channel="chrome" if args.chrome else None, headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900}, device_scale_factor=1)
    page.route("**/*", lambda route: route.abort())
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.expose_function("bridge_request", service.call)
    page.set_content(build_html())
    page.evaluate(
        "window.pywebview={api:{request:(...args)=>window.bridge_request(...args)}};window.dispatchEvent(new Event('pywebviewready'))"
    )
    page.get_by_label("Username", exact=True).fill("Test User")
    page.get_by_label("Password", exact=True).fill("a test-only secure password")
    page.get_by_role("button", name="Create account", exact=True).click()
    page.get_by_role("heading", name="Bring your memories home.").wait_for()
    page.get_by_role("button", name="I’ve saved my key", exact=True).click()
    Path("docs/screenshots").mkdir(parents=True, exist_ok=True)
    page.screenshot(path="docs/screenshots/dashboard.png", full_page=True)
    page.get_by_role("button", name="Settings", exact=True).click()
    page.get_by_label("Edited copies", exact=True).select_option("skip")
    page.get_by_role("button", name="Save preferences", exact=True).click()
    page.get_by_text("Preferences saved", exact=True).wait_for()
    assert service.settings.edited == "skip"
    page.get_by_role("button", name="Reset to default settings", exact=True).click()
    page.locator("#modal-ok").click()
    page.get_by_text("Default settings restored", exact=True).wait_for()
    assert service.settings.edited == "both"
    page.get_by_label("Edited copies", exact=True).select_option("skip")
    page.get_by_role("button", name="Save preferences", exact=True).click()
    page.get_by_text("Preferences saved", exact=True).wait_for()
    page.get_by_label("Advanced view", exact=True).check()
    page.get_by_label("Maximum working space (GB)").wait_for()
    for name in ("Setup", "Queue", "History & reports", "Accounts", "Logs & diagnostics", "Help"):
        page.get_by_role("button", name=name, exact=True).click()
        page.wait_for_timeout(150)
        assert not page.get_by_text("GPP-901", exact=False).count()
    page.get_by_role("button", name="Accounts", exact=True).click()
    page.get_by_label("Username", exact=True).fill("Second User")
    page.get_by_label("Initial password", exact=True).fill("a second secure password")
    page.get_by_role("button", name="Create user", exact=True).click()
    page.get_by_text("User created", exact=True).wait_for()
    page.get_by_role("button", name="Lock & sign out").click()
    page.get_by_role("heading", name="Welcome back.").wait_for()
    page.get_by_label("Username", exact=True).fill("Second User")
    page.get_by_label("Password", exact=True).fill("a second secure password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("heading", name="Bring your memories home.").wait_for()
    page.get_by_role("button", name="I’ve saved my key", exact=True).click()
    assert service.settings.edited == "both"
    assert service.session.role == "standard"
    # Password recovery below uses a replacement key and checks its native export.
    page.get_by_role("button", name="Accounts", exact=True).click()
    page.get_by_role("button", name="Generate replacement recovery key", exact=True).click()
    page.get_by_label("Current app password", exact=True).fill("a second secure password")
    page.locator("#modal-ok").click()
    page.get_by_role("heading", name="Save your recovery key", exact=True).wait_for()
    recovery = page.locator("#recovery-code").text_content()
    key_file = root / "recovery.txt"
    service.dialog = lambda *args: str(key_file)
    page.get_by_role("button", name="Save key to file", exact=True).click()
    page.get_by_text("Recovery key saved", exact=True).wait_for()
    assert recovery in key_file.read_text()
    page.get_by_role("button", name="I’ve saved my key", exact=True).click()
    page.get_by_role("button", name="Logs & diagnostics", exact=True).click()
    destination = root / "logs.csv"
    service.dialog = lambda *args: str(destination)
    page.get_by_role("button", name="Export logs as CSV", exact=True).click()
    page.wait_for_function(
        '() => document.querySelector("#content")?.textContent.includes("logs_csv.exported")'
    )
    assert destination.exists() and "session.recovered" in destination.read_text("utf-8-sig")

    # Exercise wrap constraints with the same unbroken details that broke the native UI.
    with service.store.connect() as con:
        service.store.audit(con, service.session.user_id, "operation." + "long_event_" * 20,
                            {"diagnostic": "a" * 1200, "path": "/folder/" + "very-long-name" * 80})
    for width in (820, 960, 1180, 1580):
        page.set_viewport_size({"width": width, "height": 620})
        for name in ("Dashboard", "Setup", "Queue", "History & reports", "Settings", "Accounts", "Logs & diagnostics", "Help"):
            page.get_by_role("button", name=name, exact=True).click()
            page.wait_for_timeout(70)
            dimensions = page.evaluate("({width:document.documentElement.clientWidth, scroll:document.documentElement.scrollWidth})")
            assert dimensions["scroll"] <= dimensions["width"], (width, name, dimensions)
        page.get_by_role("button", name="Logs & diagnostics", exact=True).click()
        assert page.locator(".audit-detail").first.evaluate("el=>el.scrollWidth<=el.clientWidth")
        if width == 820:
            page.screenshot(path="docs/screenshots/logs-narrow.png", full_page=True)
    page.set_viewport_size({"width":1280,"height":900})

    page.get_by_role("button", name="Dashboard", exact=True).click()
    page.get_by_role("heading", name="Bring your memories home.").wait_for()
    service.signin_ready.clear()
    service.job.update(
        active=True,
        phase="Sign in in Chrome, then click Continue in the app",
        awaiting_google_confirmation=True,
    )
    page.evaluate("() => refresh()")
    assert not service.signin_ready.is_set()
    page.get_by_role("button", name="I’ve signed in — Continue", exact=True).click()
    assert service.signin_ready.wait(5)
    service.job.update(active=False, phase="Ready", awaiting_google_confirmation=False)

    old_profile = service.session.user_id
    page.get_by_role("button", name="Lock & sign out").click()
    page.get_by_role("button", name="Forgot password?", exact=True).click()
    page.get_by_label("Username", exact=True).fill("Second User")
    page.get_by_label("Recovery key", exact=True).fill(recovery)
    page.get_by_label("New password", exact=True).fill("a recovered secure password")
    page.get_by_role("button", name="Reset password", exact=True).click()
    page.get_by_text("Password reset", exact=True).wait_for()
    page.get_by_label("Username", exact=True).fill("Second User")
    page.get_by_label("Password", exact=True).fill("a recovered secure password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("button", name="I’ve saved my key", exact=True).click()
    assert service.session.user_id == old_profile
    page.get_by_role("button", name="Settings", exact=True).click()
    assert page.get_by_role("button", name="Clear all data", exact=True).is_disabled()
    assert page.get_by_role("button", name="Uninstall", exact=True).is_disabled()
    page.get_by_role("button", name="Lock & sign out").click()
    page.get_by_label("Username", exact=True).fill("Test User")
    page.get_by_label("Password", exact=True).fill("a test-only secure password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("heading", name="Bring your memories home.").wait_for()
    page.get_by_role("button", name="Settings", exact=True).click()
    # Mock only the OS boundary: real UI/bridge cleanup uses this temporary root.
    macos.device_verification_available = lambda: True
    macos.verify_device_owner = lambda: True
    service.window = Mock()
    service.window.create_confirmation_dialog.return_value = True
    page.get_by_role("button", name="Clear all data", exact=True).click()
    page.locator("#modal-ok").click()
    page.get_by_role("button", name="Create account", exact=True).wait_for()
    assert not service.accounts.exists() and not (service.root / "profiles").exists()
    assert key_file.exists()  # An explicitly exported recovery file is outside app cleanup.

    assert not errors, errors
    print("UI smoke passed: all screens at 820–1580px, recovery/export/reset, role isolation and confirmed temporary-data cleanup.")
    browser.close()
