"""Conservative single-item Google Photos adapter; no private Google APIs."""

import hashlib
import os
import re
import time
import sys
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.fernet import Fernet
from .errors import AppError
from .chrome import ManagedChrome
from .scanner import Cancelled
from .store import canonical, now

UPLOAD_CONTROLS = [
    'button[aria-label="Create and add photos"]',
    'button[aria-label="Upload"]',
    'button:has-text("Upload")',
]
IMPORT_CONTROLS = [
    '[role="menuitem"][aria-label="Import photos from your computer"]',
    '[role="menuitem"]:has-text("Import photos")',
    '[role="menuitem"]:has-text("Computer")',
]
SUCCESS_TEXT = re.compile(
    r"^\s*(?:1\s+(?:item|photo|video)\s+(?:uploaded|backed\s+up)"
    r"|You\s+backed\s+up\s+1\s+(?:item|photo|video)|Upload\s+complete)\s*[.!]?\s*$",
    re.I,
)
FAILURE_TEXT = re.compile(r"Can't upload|Couldn't upload|Upload failed|Not enough storage|Storage full", re.I)
BLOCKED_SIGN_IN_TEXT = re.compile(r"\bthis\s+browser(?:\s+or\s+app)?\s+may\s+not\s+be\s+secure\b", re.I)
QUALITY_TITLE = re.compile(r"^Choose your backup quality$", re.I)
ORIGINAL_QUALITY = re.compile(r"^Original quality\b", re.I)


def first_visible(page, selectors):
    for selector in selectors:
        loc = page.locator(selector)
        for index in range(min(loc.count(), 10)):
            candidate = loc.nth(index)
            if candidate.is_visible():
                return candidate
    return None


class GoogleBrowser:
    def __init__(self, runtime, profile, key, store, stop, signin_ready=None, progress=None):
        self.runtime, self.profile, self.key, self.store, self.stop = runtime, profile, key, store, stop
        self.pw = self.browser = self.context = self.page = None
        self.session_file = profile / "google.session"
        self.chrome = None
        self._confirmation = None
        self.signin_ready, self.progress = signin_ready, progress

    def __enter__(self):
        from playwright.sync_api import sync_playwright

        self.chrome = ManagedChrome(self.runtime, self.profile, self.key, self.stop)
        try:
            endpoint = self.chrome.start(
                "https://photos.google.com/?hl=en" if self.signin_ready else "about:blank"
            )
            if self.signin_ready is not None:
                self.progress("Sign in in Chrome, then click Continue in the app", 0)
                deadline = time.monotonic() + 900
                while not self.signin_ready.wait(0.2):
                    if self.stop.is_set():
                        raise Cancelled()
                    if self.chrome.process.poll() is not None:
                        raise AppError("GPP-411")
                    if time.monotonic() >= deadline:
                        raise AppError("GPP-401")
                self.progress("Connecting to your Chrome session", 0)
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.connect_over_cdp(endpoint, timeout=30000)
            if not self.browser.contexts:
                raise AppError("GPP-411")
            # Reuse Chrome's authenticated default context, exactly as the original script did.
            self.context = self.browser.contexts[0]
            self.page = self.context.new_page()
            self.page.set_default_timeout(15000)
            return self
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        if self.browser:
            try:
                self.browser.new_browser_cdp_session().send("Browser.close")
            except Exception:  # noqa: S110 -- still stop the owned process and protect the profile
                pass
        if self.pw:
            self.pw.stop()
        if self.chrome:
            try:
                self.chrome.close()
            except AppError:
                if exc_type is None:
                    raise

    def navigate(self):
        try:
            self.page.goto("https://photos.google.com/?hl=en", wait_until="domcontentloaded", timeout=60000)
        except Exception as exc:
            raise AppError("GPP-407") from exc

    def identity(self):
        if urlsplit(self.page.url).hostname != "photos.google.com":
            return None
        controls = self.page.locator('[aria-label*="Google Account"]')
        for i in range(min(controls.count(), 10)):
            text = controls.nth(i).get_attribute("aria-label") or ""
            match = re.search(r"[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
            if match:
                return hashlib.sha256(match.group().lower().encode()).hexdigest()
        return None

    def check_signin_block(self):
        # Only recognize Google's account page, never a photo caption or a local page.
        if urlsplit(self.page.url).hostname != "accounts.google.com":
            return
        blocked = self.page.get_by_text(BLOCKED_SIGN_IN_TEXT)
        for index in range(min(blocked.count(), 5)):
            if blocked.nth(index).is_visible():
                raise AppError("GPP-410")

    def bind_identity(self, identity):
        with self.store.connect() as con:
            old = con.execute("SELECT value FROM config WHERE key='google_identity'").fetchone()
            if old and old[0] != identity:
                raise AppError("GPP-409")
            con.execute("INSERT OR IGNORE INTO config VALUES('google_identity',?)", (identity,))

    def save_session(self):
        state = self.context.storage_state(indexed_db=True)
        data = Fernet(self.key).encrypt(canonical(state).encode())
        temporary = self.session_file.with_suffix(".tmp")
        with temporary.open("wb") as output:
            os.chmod(temporary, 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(self.session_file)

    def handle_quality_prompt(self):
        """Confirm only the recognized backup dialog, after verifying Original quality."""
        if urlsplit(self.page.url).hostname != "photos.google.com":
            return False
        dialogs = self.page.locator('[role="dialog"], [aria-modal="true"]')
        matches = []
        for index in range(min(dialogs.count(), 10)):
            dialog = dialogs.nth(index)
            title = dialog.get_by_text(QUALITY_TITLE)
            if dialog.is_visible() and title.count() and title.first.is_visible():
                matches.append(dialog)
        if not matches:
            return False
        if len(matches) != 1:
            raise AppError("GPP-414")
        dialog = matches[0]
        try:
            original = dialog.get_by_role("radio", name=ORIGINAL_QUALITY)
            if original.count() != 1:
                raise AppError("GPP-414")
            # check() supports native and ARIA radios and verifies the checked state.
            original.check(timeout=5000)
            if not original.is_checked():
                raise AppError("GPP-414")
            continue_button = dialog.get_by_role("button", name=re.compile(r"^Continue$", re.I))
            if continue_button.count() != 1:
                raise AppError("GPP-414")
            continue_button.click(timeout=5000)
            dialog.wait_for(state="hidden", timeout=10000)
            return True
        except AppError:
            raise
        except Exception as exc:
            raise AppError("GPP-414") from exc

    def login(self, progress):
        self.navigate()
        deadline = time.monotonic() + 600
        progress("Complete Google sign-in in the browser window", 0)
        while time.monotonic() < deadline:
            if self.stop.is_set():
                raise Cancelled()
            self.check_signin_block()
            identity = self.identity()
            if identity:
                self.bind_identity(identity)
                self.handle_quality_prompt()
                if first_visible(self.page, UPLOAD_CONTROLS):
                    self.save_session()
                    return
            self.page.wait_for_timeout(1000)
        raise AppError("GPP-401")

    def self_test(self):
        self.navigate()
        self.page.wait_for_timeout(1500)
        self.check_signin_block()
        identity = self.identity()
        if not identity:
            raise AppError("GPP-401")
        self.bind_identity(identity)
        self.handle_quality_prompt()
        if not first_visible(self.page, UPLOAD_CONTROLS):
            raise AppError("GPP-402")
        self.save_session()
        return {"account": "matched", "upload_control": "found", "uploaded_test_file": False}

    def upload(self, path: Path, timeout_minutes, mark_submitted):
        self._confirmation = None
        self.self_test()  # Fresh navigation removes stale success notifications.
        if self.page.get_by_text(SUCCESS_TEXT).count():
            raise AppError("GPP-402")
        if self.stop.is_set():
            raise Cancelled()
        button = first_visible(self.page, UPLOAD_CONTROLS)
        submitted = False
        stage = "open_upload"
        try:
            # Open the add menu first; direct Upload buttons may trigger the chooser.
            if button.get_attribute("aria-label") == "Create and add photos":
                button.click()
                self.page.wait_for_timeout(300)
                button = first_visible(self.page, IMPORT_CONTROLS)
                if not button:
                    raise AppError("GPP-402")
            stage = "choose_file"
            with self.page.expect_file_chooser(timeout=15000) as chooser:
                button.click()
            file_chooser = chooser.value
            # Commit the uncertainty boundary BEFORE handing bytes to Google.
            mark_submitted()
            submitted = True
            stage = "set_files"
            file_chooser.set_files(str(path.resolve()), timeout=60000)
            deadline = time.monotonic() + timeout_minutes * 60
            while time.monotonic() < deadline:
                # Pause is cooperative: finish this single submitted item before stopping.
                stage = "quality_prompt"
                self.handle_quality_prompt()
                stage = "wait_confirmation"
                failure = self.page.get_by_text(FAILURE_TEXT)
                if any(failure.nth(i).is_visible() for i in range(min(failure.count(), 5))):
                    raise AppError("GPP-404")
                empty = self.page.get_by_text(re.compile(r"No items uploaded", re.I))
                if empty.count() and empty.first.is_visible():
                    raise AppError("GPP-403")
                success = self.page.get_by_text(SUCCESS_TEXT)
                for i in range(min(success.count(), 5)):
                    if success.nth(i).is_visible():
                        self._confirmation = success.nth(i)
                        return {
                            "kind": "browser_confirmation",
                            "time": now(),
                            "evidence": " ".join(success.nth(i).inner_text().split())[:100],
                        }
                self.page.wait_for_timeout(1000)
            stage = "confirmation_timeout"
            raise AppError("GPP-403")
        except AppError as exc:
            exc.stage = stage
            raise
        except Exception as exc:
            error = AppError("GPP-403" if submitted else "GPP-402")
            error.stage = stage
            raise error from exc

    def dismiss_confirmation(self):
        """Called after the queue commit; close only the recognized completion card."""
        if self._confirmation is None:
            return
        try:
            container = self._confirmation
            for _ in range(5):
                container = container.locator("xpath=..")
                if container.evaluate("el => ['BODY','HTML'].includes(el.tagName)"):
                    break
                album = container.get_by_text(re.compile(r"^Add to album$", re.I))
                close = container.get_by_role("button", name=re.compile(r"^Close$", re.I))
                if album.count() and close.count() == 1 and close.is_visible():
                    close.click(timeout=2000)
                    container.wait_for(state="hidden", timeout=2000)
                    break
        except Exception:  # noqa: S110 -- confirmation is committed; next navigation clears the card
            pass
        finally:
            self._confirmation = None
