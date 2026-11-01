"""Recovery and destructive actions use disposable data and mocked OS boundaries."""

import json
import os
import stat
from unittest.mock import Mock
import pytest
from cryptography.fernet import Fernet
from filelock import FileLock
from photorestore.auth import Accounts
from photorestore.errors import AppError
from photorestore.service import Service
from photorestore.store import Store
from photorestore.maintenance import clear_owned_data

PASSWORD = "a private recovery test password"
NEW = "a replacement recovery password"


def account(tmp_path):
    store = Store(tmp_path / "accounts.sqlite")
    store.initialize()
    auth = Accounts(store)
    auth.create("Alice", PASSWORD)
    return auth, auth.login("Alice", PASSWORD)


def test_recovery_preserves_key_is_single_use_and_never_logged(tmp_path):
    auth, alice = account(tmp_path)
    encrypted = Fernet(alice.key).encrypt(b"saved session")
    code = auth.issue_recovery(alice)
    assert code.startswith("TRR-") and auth.issue_recovery(alice) is None
    with auth.store.connect() as con:
        stored = dict(con.execute("SELECT * FROM users").fetchone())
        audit = json.dumps([dict(r) for r in con.execute("SELECT * FROM audit")])
    assert code not in audit and stored["recovery_hash"] != code
    assert code.encode() not in stored["recovery_wrapped_key"]
    auth.recover_password("alice", code.lower(), NEW)
    recovered = auth.login("Alice", NEW)
    assert Fernet(recovered.key).decrypt(encrypted) == b"saved session"
    with pytest.raises(AppError, match="GPP-109"):
        auth.recover_password("Alice", code, PASSWORD)
    replacement = auth.issue_recovery(recovered)
    assert replacement != code
    assert auth.store.verify_audit()


def test_bad_and_disabled_recovery_are_rejected_and_throttled(tmp_path):
    auth, alice = account(tmp_path)
    code = auth.issue_recovery(alice)
    for _ in range(5):
        with pytest.raises(AppError, match="GPP-109"):
            auth.recover_password("Alice", "wrong", NEW)
    with pytest.raises(AppError, match="GPP-105"):
        auth.recover_password("Alice", code, NEW)
    with auth.store.connect() as con:
        assert con.execute("SELECT recovery_failures FROM users").fetchone()[0] == 5
        con.execute("UPDATE users SET disabled=1,recovery_locked_until=0")
    with pytest.raises(AppError, match="GPP-109"):
        auth.recover_password("Alice", code, NEW)


def test_replacement_and_admin_reset_invalidate_old_recovery(tmp_path):
    auth, alice = account(tmp_path)
    old = auth.issue_recovery(alice)
    with pytest.raises(AppError, match="GPP-104"):
        auth.issue_recovery(alice, "wrong", replace=True)
    new = auth.issue_recovery(alice, PASSWORD, replace=True)
    with pytest.raises(AppError, match="GPP-109"):
        auth.recover_password("Alice", old, NEW)
    bid = auth.create("Bobby", PASSWORD, alice)
    bcode = auth.issue_recovery(auth.login("Bobby", PASSWORD))
    auth.manage(alice, bid, "reset", NEW)
    with pytest.raises(AppError, match="GPP-109"):
        auth.recover_password("Bobby", bcode, PASSWORD)
    auth.recover_password("Alice", new, NEW)


def test_existing_database_migrates_without_changing_accounts_or_audit(tmp_path):
    auth, alice = account(tmp_path)
    head = auth.store.verify_audit()
    with auth.store.connect() as con:
        for column in ("recovery_hash", "recovery_wrapped_key", "recovery_failures", "recovery_locked_until"):
            con.execute(f"ALTER TABLE users DROP COLUMN {column}")
        con.execute("PRAGMA user_version=1")
    auth.store.initialize()
    assert auth.store.verify_audit() == head
    assert auth.login("Alice", PASSWORD).key == alice.key
    assert auth.issue_recovery(alice)
    with auth.store.connect() as con:
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2


def signed_in(tmp_path):
    service = Service(tmp_path / "data")
    result = service.call("register", {"username": "Alice", "password": PASSWORD})
    assert result["ok"], result
    return service, result["data"]["token"], result["data"]["recovery_key"]


def test_public_recovery_and_recovery_export_are_scoped(tmp_path):
    service, token, code = signed_in(tmp_path)
    destination = tmp_path / "key.txt"
    service.dialog = Mock(return_value=str(destination))
    assert service.call("save_recovery", {"recovery_key": code}, "wrong")["error"]["code"] == "GPP-102"
    assert service.call("save_recovery", {"recovery_key": "wrong"}, token)["error"]["code"] == "GPP-109"
    assert service.call("save_recovery", {"recovery_key": code}, token)["ok"]
    assert code in destination.read_text(encoding="utf-8")
    if os.name == "posix":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    else:
        # Windows chmod controls read-only status, not Unix owner/group permissions.
        assert destination.stat().st_mode & stat.S_IREAD
        assert destination.stat().st_mode & stat.S_IWRITE
    assert (
        service.call("recover_password", {"username": "Alice", "recovery_key": code, "password": NEW})[
            "error"
        ]["code"]
        == "GPP-106"
    )
    service.call("logout", {}, token)
    assert service.call("recover_password", {"username": "Alice", "recovery_key": code, "password": NEW})[
        "ok"
    ]
    assert service.call("login", {"username": "Alice", "password": NEW})["ok"]


def test_reset_settings_keeps_history_session_and_other_users(tmp_path):
    service, token, _ = signed_in(tmp_path)
    profile = service.profile
    (profile / "google.session").write_bytes(b"encrypted")
    service.call("create_user", {"username": "Bobby", "password": PASSWORD}, token)
    service.call("save_settings", {"settings": {"edited": "skip", "advanced": True}}, token)
    with service.store.connect() as con:
        con.execute("INSERT INTO config VALUES('source','/source')")
        service.store.audit(con, service.session.user_id, "example.history")
    assert service.call("reset_settings", {}, token)["ok"]
    assert service.settings.edited == "both" and not service.settings.advanced
    assert (profile / "google.session").read_bytes() == b"encrypted"
    assert len(service.call("users", {}, token)["data"]) == 2
    with service.store.connect() as con:
        assert con.execute("SELECT value FROM config WHERE key='source'").fetchone()[0] == "/source"
        assert con.execute("SELECT 1 FROM audit WHERE action='example.history'").fetchone()


def native_boundaries(monkeypatch, service, accepted=True):
    monkeypatch.setattr("photorestore.service.macos.device_verification_available", lambda: True)
    verify = Mock(return_value=accepted)
    monkeypatch.setattr("photorestore.service.macos.verify_device_owner", verify)
    service.window = Mock()
    service.window.create_confirmation_dialog.return_value = True
    return verify


CONFIRM = {"confirmation": "REMOVE ALL LOCAL DATA"}


def test_clear_data_requires_role_device_verification_and_native_confirmation(tmp_path, monkeypatch):
    service, token, _ = signed_in(tmp_path)
    verify = native_boundaries(monkeypatch, service, accepted=False)
    assert service.call("clear_data", CONFIRM, token)["error"]["code"] == "GPP-110"
    assert service.accounts.exists()
    verify.return_value = True
    service.window.create_confirmation_dialog.return_value = False
    assert service.call("clear_data", CONFIRM, token)["data"] is False
    assert service.accounts.exists()
    assert service.call("clear_data", {}, token)["error"]["code"] == "GPP-101"
    service.call("create_user", {"username": "Bobby", "password": PASSWORD}, token)
    service.call("logout", {}, token)
    bob = service.call("login", {"username": "Bobby", "password": PASSWORD})["data"]["token"]
    assert service.call("clear_data", CONFIRM, bob)["error"]["code"] == "GPP-103"


def test_start_over_removes_all_app_data_preserves_lock_and_external_files(tmp_path, monkeypatch):
    service, token, _ = signed_in(tmp_path)
    native_boundaries(monkeypatch, service)
    source = tmp_path / "original.jpg"
    source.write_bytes(b"original media")
    (service.root / "external-link").symlink_to(source)
    (service.root / "runtime").mkdir()
    (service.root / "runtime/browser").write_text("cached browser")
    service.call("logout", {}, token)
    with FileLock(service.root / "application.lock"):
        result = service.call("clear_data", CONFIRM)
        assert result == {"ok": True, "data": True}
        assert (service.root / "application.lock").exists()
        assert not service.accounts.exists()
        assert not (service.root / "profiles").exists()
        assert not (service.root / "runtime").exists()
        assert source.read_bytes() == b"original media"
        assert service.call("status", {}, token)["error"]["code"] == "GPP-102"
        assert service.call("register", {"username": "Fresh", "password": PASSWORD})["ok"]


def test_uninstall_failure_keeps_accounts_and_success_only_clears_owned_root(tmp_path, monkeypatch):
    service, token, _ = signed_in(tmp_path)
    native_boundaries(monkeypatch, service)
    monkeypatch.setattr("photorestore.service.macos.installed_bundle", lambda: None)
    assert service.call("uninstall", CONFIRM, token)["error"]["code"] == "GPP-112"
    assert service.accounts.exists()
    monkeypatch.setattr("photorestore.service.macos.installed_bundle", lambda: "/Applications/Fake.app")
    trash = Mock(side_effect=AppError("GPP-111"))
    monkeypatch.setattr("photorestore.service.macos.trash_installed_app", trash)
    assert service.call("uninstall", CONFIRM, token)["error"]["code"] == "GPP-111"
    assert service.accounts.exists()
    trash.side_effect = None
    timer = Mock()
    monkeypatch.setattr("photorestore.service.threading.Timer", timer)
    window = service.window
    with FileLock(service.root / "application.lock"):
        assert service.call("uninstall", CONFIRM, token)["ok"]
        assert service.uninstalled
        assert list(p.name for p in service.root.iterdir()) == ["application.lock"]
    timer.assert_called_once_with(1, window.destroy)
    timer.return_value.start.assert_called_once()


def test_cleanup_refuses_symlink_root(tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    original = external / "original"
    original.write_text("keep")
    link = tmp_path / "link"
    link.symlink_to(external, target_is_directory=True)
    with pytest.raises(AppError, match="GPP-111"):
        clear_owned_data(link)
    assert original.read_text() == "keep"


def test_non_mac_cleanup_rechecks_admin_password_and_busy_jobs(tmp_path, monkeypatch):
    service, token, _ = signed_in(tmp_path)
    monkeypatch.setattr("photorestore.service.macos.device_verification_available", lambda: False)
    service.window = Mock()
    service.window.create_confirmation_dialog.return_value = True
    service.thread = Mock()
    service.thread.is_alive.return_value = True
    assert service.call("clear_data", {**CONFIRM, "password": PASSWORD}, token)["error"]["code"] == "GPP-106"
    service.thread.is_alive.return_value = False
    assert service.call("clear_data", {**CONFIRM, "password": "wrong"}, token)["error"]["code"] == "GPP-104"
    assert service.accounts.exists()
    assert service.call("clear_data", {**CONFIRM, "password": PASSWORD}, token)["ok"]
    assert not service.accounts.exists()
    assert service.call("clear_data", CONFIRM)["error"]["code"] == "GPP-102"


def test_cleanup_io_error_stops_further_operations(tmp_path, monkeypatch):
    service, token, _ = signed_in(tmp_path)
    native_boundaries(monkeypatch, service)
    monkeypatch.setattr("photorestore.service.clear_owned_data", Mock(side_effect=AppError("GPP-111")))
    assert service.call("clear_data", CONFIRM, token)["error"]["code"] == "GPP-111"
    assert service.maintenance_failed
    assert service.call("register", {"username": "Fresh", "password": PASSWORD})["error"]["code"] == "GPP-111"
