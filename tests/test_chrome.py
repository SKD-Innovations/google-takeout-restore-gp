import threading
import zipfile
from pathlib import Path
import pytest
from cryptography.fernet import Fernet
from photorestore.chrome import ManagedChrome, encrypt_archive, decrypt_archive, cleanup_unlocked_profiles
from photorestore.errors import AppError
from photorestore.service import Service


def test_encrypted_profile_roundtrip_and_tamper_rejection(tmp_path):
    original = tmp_path / "profile.zip"
    original.write_bytes(b"private cookies" * 100000)
    encrypted = tmp_path / "profile.enc"
    key = Fernet.generate_key()
    encrypt_archive(original, encrypted, key)
    assert b"private cookies" not in encrypted.read_bytes()
    restored = tmp_path / "restored.zip"
    decrypt_archive(encrypted, restored, key)
    assert restored.read_bytes() == original.read_bytes()
    changed = bytearray(encrypted.read_bytes())
    changed[100] ^= 1
    encrypted.write_bytes(changed)
    with pytest.raises(AppError, match="GPP-408"):
        decrypt_archive(encrypted, restored, key)
    assert not restored.exists()


def test_close_encrypts_profile_and_omits_cache_and_process_endpoints(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    key = Fernet.generate_key()
    chrome = ManagedChrome(None, profile, key, threading.Event())
    chrome.work.mkdir()
    (chrome.work / "Default").mkdir()
    (chrome.work / "Default" / "Cookies").write_bytes(b"fake credentials")
    (chrome.work / "Default" / "Cache").mkdir()
    (chrome.work / "Default" / "Cache" / "blob").write_bytes(b"cache")
    (chrome.work / "DevToolsActivePort").write_text("1234\n/devtools/browser/old")
    chrome.started = True
    chrome.close()
    assert chrome.archive.is_file() and not chrome.work.exists()
    zipped = tmp_path / "read.zip"
    decrypt_archive(chrome.archive, zipped, key)
    with zipfile.ZipFile(zipped) as z:
        assert z.namelist() == ["Default/Cookies"]
        assert z.read("Default/Cookies") == b"fake credentials"


def test_startup_removes_only_managed_unlocked_profile_directories(tmp_path):
    profile = tmp_path / "profiles" / ("a" * 32)
    profile.mkdir(parents=True)
    for name in ("chrome-work", "chrome-unlock-dead", "chrome-lock-dead"):
        (profile / name).mkdir()
        (profile / name / "private").write_bytes(b"fake")
    (profile / "chrome.profile.enc").write_bytes(b"encrypted")
    cleanup_unlocked_profiles(tmp_path)
    assert [p.name for p in profile.iterdir()] == ["chrome.profile.enc"]


def test_confirmation_requires_authenticated_waiting_operation(tmp_path):
    service = Service(tmp_path / "data")
    assert service.call("confirm_google")["error"]["code"] == "GPP-102"
    token = service.call("register", {"username": "Test User", "password": "long local password"})["data"][
        "token"
    ]
    assert service.call("confirm_google", {}, token)["error"]["code"] == "GPP-106"
    service.job.update(active=True, awaiting_google_confirmation=True)
    assert service.call("confirm_google", {}, token)["ok"]
    assert service.signin_ready.is_set() and not service.job["awaiting_google_confirmation"]


def test_original_flow_waits_for_confirmation_then_reuses_default_context(tmp_path, monkeypatch):
    from photorestore.browser import GoogleBrowser

    order = []
    ready = threading.Event()

    class Page:
        def set_default_timeout(self, _):
            pass

    class Context:
        def new_page(self):
            return Page()

    context = Context()

    class CDP:
        def send(self, method):
            assert method == "Browser.close"

    class Browser:
        contexts = [context]

        def new_browser_cdp_session(self):
            return CDP()

    class Chromium:
        def connect_over_cdp(self, endpoint, timeout):
            assert ready.is_set() and endpoint == "ws://127.0.0.1:1234/devtools/browser/test"
            order.append("attached")
            return Browser()

    class PW:
        chromium = Chromium()

        def start(self):
            assert ready.is_set()
            order.append("playwright_started")
            return self

        def stop(self):
            pass

    class Chrome:
        def __init__(self, *args):
            pass

        def start(self, url):
            assert not order
            order.append("chrome_opened")
            ready.set()  # Simulated user completion; Playwright has not started yet.
            order.append("user_confirmed")
            return "ws://127.0.0.1:1234/devtools/browser/test"

        def close(self):
            pass

    monkeypatch.setattr("photorestore.browser.ManagedChrome", Chrome)
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: PW())
    with GoogleBrowser(
        None, tmp_path, None, None, threading.Event(), signin_ready=ready, progress=lambda *a: None
    ) as browser:
        assert browser.context is context
    assert order == ["chrome_opened", "user_confirmed", "playwright_started", "attached"]


def test_restart_preserves_working_profile_if_previous_chrome_is_running(tmp_path, monkeypatch):
    profile = tmp_path / "profiles" / ("a" * 32)
    work = profile / "chrome-work"
    work.mkdir(parents=True)
    (work / "DevToolsActivePort").write_text("1234\n/devtools/browser/old")

    class Connected:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setattr("photorestore.chrome.socket.create_connection", lambda *args, **kwargs: Connected())
    with pytest.raises(AppError, match="GPP-413"):
        cleanup_unlocked_profiles(tmp_path)
    assert work.exists()
