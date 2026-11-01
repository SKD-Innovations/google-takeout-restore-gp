"""Incident export privacy, consent, persistence, and compose-only mail handoff."""

import hashlib
import json
import os
import stat
import sqlite3
import sys
import types
import zipfile
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit
import pytest
from photorestore import maildraft, support
from photorestore.errors import AppError
from photorestore.service import Service, StartupSupport
from photorestore.store import Store

PASSWORD = "a private support test password"


def signed_in(tmp_path):
    service = Service(tmp_path / "data")
    token = service.call("register", {"username": "Alice", "password": PASSWORD})["data"]["token"]
    return service, token


def test_bundle_redacts_secrets_and_identifies_build_and_observed_error(tmp_path, monkeypatch):
    service, token = signed_in(tmp_path)
    secret = "PRIVATE_PERSON_PHOTO_password_cookie_recovery"
    (service.profile / "google.session").write_text(secret)
    with service.store.connect() as con:
        service.store.audit(con, "Alice", "private.event", {"path": secret})
        con.execute("INSERT INTO config VALUES('source',?)", (secret,))
    (service.profile / "logs/events.jsonl").write_text(
        json.dumps(
            {
                "event": "operation.error",
                "time": "2026-11-01T00:00:00+00:00",
                "code": "GPP-403",
                "message": secret,
                "path": secret,
                "stage": "confirmation_timeout",
                "exception_type": "AppError",
            }
        )
        + "\n"
    )
    identity = {
        "name": "Takeout Restore",
        "version": "0.2.0",
        "build_id": "a" * 64,
        "executable_sha256": "b" * 64,
    }
    monkeypatch.setattr(support, "app_identity", lambda: identity)
    try:
        try:
            raise TimeoutError(secret)
        except TimeoutError as cause:
            error = AppError("GPP-403")
            error.stage = "confirmation_timeout"
            raise error from cause
    except AppError as exc:
        incident = service.capture_incident("GPP-403", "upload", exc, "c" * 32)
    path = tmp_path / "report.zip"
    draft = support.write_incident_bundle(path, incident, service.store, service.profile)
    with zipfile.ZipFile(path) as z:
        assert set(z.namelist()) == {"incident.json", "report.txt", "events.json"}
        all_text = "".join(z.read(n).decode() for n in z.namelist())
        info = json.loads(z.read("incident.json"))
    assert secret not in all_text and str(tmp_path) not in all_text and "Alice" not in all_text
    assert info["application"] == identity
    assert info["incident"]["detail"]["cause_types"] == ["TimeoutError"]
    assert info["incident"]["detail"]["stage"] == "confirmation_timeout"
    assert "not established" in info["root_cause"].lower()
    assert "a" * 64 in draft["body"] and "b" * 64 in draft["body"]
    assert draft["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    else:
        assert path.stat().st_mode & stat.S_IREAD
        assert path.stat().st_mode & stat.S_IWRITE
    service.call("logout", {}, token)


def test_routine_errors_do_not_offer_reports_unexpected_failure_does(tmp_path, monkeypatch):
    service, token = signed_in(tmp_path)
    composer = Mock()
    monkeypatch.setattr("photorestore.service.open_report_draft", composer)
    assert "incident" not in service.call("scan", {}, token)["error"]
    service.dialog = Mock(side_effect=RuntimeError("SECRET SOURCE PATH"))
    error = service.call("pick_source", {}, token)["error"]
    assert error["code"] == "GPP-901" and error["incident"]["id"]
    assert "SECRET SOURCE" not in json.dumps(error)
    assert service.call("status", {}, token)["data"]["incident"]["id"] == error["incident"]["id"]
    composer.assert_not_called()  # Merely encountering an error never opens or sends mail.


def test_incidents_survive_login_are_user_scoped_and_can_be_acknowledged(tmp_path):
    service, token = signed_in(tmp_path)
    incident = service.capture_incident("GPP-402", "test_google")
    same = service.capture_incident("GPP-402", "test_google")
    assert same["id"] == incident["id"]  # Polling cannot create an incident storm.
    service.call("create_user", {"username": "Bobby", "password": PASSWORD}, token)
    service.call("logout", {}, token)
    assert not service.incident_cache and service.pending_incident is None
    bob = service.call("login", {"username": "Bobby", "password": PASSWORD})["data"]["token"]
    assert service.call("status", {}, bob)["data"]["incident"] is None
    assert (
        service.call("send_report", {"consent": True, "incident_id": incident["id"]}, bob)["error"]["code"]
        == "GPP-101"
    )
    service.call("logout", {}, bob)
    alice = service.call("login", {"username": "Alice", "password": PASSWORD})["data"]["token"]
    assert service.call("status", {}, alice)["data"]["incident"]["id"] == incident["id"]
    assert service.call("acknowledge_incident", {"incident_id": incident["id"]}, alice)["ok"]
    assert service.pending_incident is None
    service.call("logout", {}, alice)
    alice = service.call("login", {"username": "Alice", "password": PASSWORD})["data"]["token"]
    assert service.call("status", {}, alice)["data"]["incident"] is None


def test_report_requires_auth_consent_and_save_before_composer(tmp_path, monkeypatch):
    service, token = signed_in(tmp_path)
    composer = Mock(return_value={"opened": True, "attachment_requested": True, "method": "test"})
    monkeypatch.setattr("photorestore.service.open_report_draft", composer)
    service.dialog = Mock(return_value=None)
    assert service.call("send_report", {"consent": True})["error"]["code"] == "GPP-102"
    assert service.call("send_report", {}, token)["error"]["code"] == "GPP-101"
    service.dialog.assert_not_called()
    assert service.call("send_report", {"consent": True}, token)["data"]["cancelled"]
    composer.assert_not_called()
    output = tmp_path / "incident.zip"
    service.dialog.return_value = str(output)
    result = service.call("send_report", {"consent": True}, token)
    assert result["ok"] and result["data"]["recipient"] == support.SUPPORT_EMAIL
    assert output.is_file()
    assert not list(tmp_path.glob(".takeout-report-*"))
    subject, body, attachment = composer.call_args.args
    assert attachment == output and output.name in body and ".takeout-report-" not in body
    assert "0.2.0" in subject
    assert service.call("acknowledge_incident", {"incident_id": result["data"]["incident_id"]}, token)["ok"]
    with service.store.connect() as con:
        assert not con.execute("SELECT 1 FROM audit WHERE action='support.sent'").fetchone()
        assert con.execute("SELECT 1 FROM audit WHERE action='support.draft_requested'").fetchone()


@pytest.mark.parametrize("location", ["app", "source", "symlink", "extension"])
def test_export_cannot_overwrite_app_data_or_source_media(tmp_path, monkeypatch, location):
    service, token = signed_in(tmp_path)
    source = tmp_path / "source"
    source.mkdir()
    service.selected_source = str(source)
    actual = tmp_path / "existing.zip"
    actual.write_text("original")
    link = tmp_path / "linked.zip"
    link.symlink_to(actual)
    destination = {
        "app": service.root / "accounts.sqlite.zip",
        "source": source / "photo.zip",
        "symlink": link,
        "extension": tmp_path / "photo.jpg",
    }[location]
    service.dialog = Mock(return_value=str(destination))
    composer = Mock()
    monkeypatch.setattr("photorestore.service.open_report_draft", composer)
    assert not service.call("send_report", {"consent": True}, token)["ok"]
    assert actual.read_text() == "original"
    composer.assert_not_called()


def test_report_works_when_database_is_broken_and_handles_save_error(tmp_path, monkeypatch):
    service, token = signed_in(tmp_path)
    incident = service.capture_incident("GPP-501", "status")
    monkeypatch.setattr(service.accounts_store, "connect", Mock(side_effect=sqlite3.DatabaseError("PRIVATE")))
    monkeypatch.setattr(service.store, "connect", Mock(side_effect=sqlite3.DatabaseError("PRIVATE")))
    composer = Mock(return_value={"opened": False, "attachment_requested": False, "method": "mailto"})
    monkeypatch.setattr("photorestore.service.open_report_draft", composer)
    service.dialog = Mock(return_value=str(tmp_path / "incident.zip"))
    result = service.call("send_report", {"consent": True, "incident_id": incident["id"]}, token)
    assert result["ok"] and not result["data"]["opened"]
    with zipfile.ZipFile(result["data"]["path"]) as z:
        info = json.loads(z.read("incident.json"))
    assert info["database_diagnostics"].startswith("Unavailable")
    assert "PRIVATE" not in json.dumps(info)
    service.dialog.return_value = str(tmp_path / "missing/report.zip")
    assert (
        service.call("send_report", {"consent": True, "incident_id": incident["id"]}, token)["error"]["code"]
        == "GPP-113"
    )


def test_startup_report_has_no_account_store_access(tmp_path, monkeypatch):
    service = StartupSupport(tmp_path / "data", "GPP-501", RuntimeError("SECRET DB PATH"))
    boot = service.call("bootstrap")["data"]
    assert boot["startup_error"]["code"] == "GPP-501"
    incident_id = boot["incident"]["id"]
    service.dialog = Mock(return_value=str(tmp_path / "startup.zip"))
    monkeypatch.setattr(
        "photorestore.service.open_report_draft",
        Mock(return_value={"opened": False, "attachment_requested": False, "method": "mailto"}),
    )
    assert not service.call("send_report", {"consent": True, "incident_id": "0" * 32})["ok"]
    assert not service.call("status")["ok"]
    assert service.call("send_report", {"consent": True, "incident_id": incident_id})["ok"]
    with zipfile.ZipFile(tmp_path / "startup.zip") as z:
        info = json.loads(z.read("incident.json"))
    assert not info["counts"] and "SECRET DB PATH" not in json.dumps(info)


def test_mailto_fallback_encodes_draft_and_does_not_claim_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr(maildraft.sys, "platform", "linux")
    browser = Mock(return_value=True)
    monkeypatch.setattr(maildraft.webbrowser, "open", browser)
    result = maildraft.open_report_draft("Café & issue?", "line1\n&bcc=evil@test", tmp_path / "report.zip")
    uri = browser.call_args.args[0]
    parsed = urlsplit(uri)
    assert parsed.path == support.SUPPORT_EMAIL
    params = parse_qs(parsed.query)
    assert set(params) == {"subject", "body"}
    assert params["body"] == ["line1\n&bcc=evil@test"]
    assert result["opened"] and not result["attachment_requested"]


def test_mac_native_handoff_uses_compose_service_with_file_url(tmp_path, monkeypatch):
    native = Mock()
    native.canPerformWithItems_.return_value = True
    sharing = Mock()
    sharing.sharingServiceNamed_.return_value = native
    fake_appkit = types.SimpleNamespace(
        NSSharingService=sharing, NSSharingServiceNameComposeEmail="composeEmail"
    )
    fake_foundation = types.SimpleNamespace(
        NSURL=types.SimpleNamespace(fileURLWithPath_=lambda value: ("file-url", value)),
        NSThread=types.SimpleNamespace(isMainThread=lambda: True),
    )
    monkeypatch.setitem(sys.modules, "AppKit", fake_appkit)
    monkeypatch.setitem(sys.modules, "Foundation", fake_foundation)
    monkeypatch.setitem(sys.modules, "PyObjCTools", types.SimpleNamespace(AppHelper=Mock()))
    path = tmp_path / "support.zip"
    assert maildraft.native_mac_draft("Issue", "Body", path)
    sharing.sharingServiceNamed_.assert_called_once_with("composeEmail")
    native.setRecipients_.assert_called_once_with([support.SUPPORT_EMAIL])
    native.setSubject_.assert_called_once_with("Issue")
    native.performWithItems_.assert_called_once_with(["Body", ("file-url", str(path))])


def test_profile_v1_migration_preserves_audit_and_pending_items(tmp_path):
    store = Store(tmp_path / "profile.sqlite")
    store.initialize(profile=True)
    with store.connect() as con:
        store.audit(con, "user", "existing.record")
        con.execute("DROP TABLE incidents")
        con.execute("PRAGMA user_version=1")
    head = store.verify_audit()
    store.initialize(profile=True)
    assert store.verify_audit() == head
    with store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM incidents").fetchone()[0] == 0
        assert con.execute("PRAGMA user_version").fetchone()[0] == 2


def test_build_fingerprint_is_deterministic_and_changes_with_source(tmp_path):
    from scripts.build_identity import write_identity

    (tmp_path / "photorestore/resources").mkdir(parents=True)
    (tmp_path / "photorestore/app.py").write_text("print('test')\n")
    for filename in ("requirements.txt", "requirements-dev.txt", "USAGE.md"):
        (tmp_path / filename).write_text("test\n")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.2.0"\n')
    for filename in ("browser.json", "exiftool.json"):
        (tmp_path / "photorestore/resources" / filename).write_text("{}")
    first = write_identity(tmp_path)
    assert write_identity(tmp_path) == first
    (tmp_path / "photorestore/app.py").write_text("print('updated')\n")
    assert write_identity(tmp_path)["build_id"] != first["build_id"]
    assert str(tmp_path) not in json.dumps(first)
