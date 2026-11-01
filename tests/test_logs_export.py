import csv
import json
import pytest
from photorestore.diagnostics import export_logs_csv, log_event, logger_for
from photorestore.errors import AppError
from photorestore.service import Service


def test_export_includes_entire_audit_and_error_descriptions(store, tmp_path):
    with store.connect() as con:
        for n in range(250):
            store.audit(con, "user", "example", {"item": n})
        store.audit(con, "=HYPERLINK(evil)", "item.review", {"code": "GPP-403", "item": 2})
    output = tmp_path / "logs.csv"
    export_logs_csv(output, store)
    with output.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 251
    assert rows[-1]["Actor"].startswith("'=")
    assert rows[-1]["Error code"] == "GPP-403"
    assert "Check Google Photos" in rows[-1]["Description"]
    assert rows[-1]["Item ID"] == "2" and len(rows[-1]["Hash"]) == 64


def test_simple_view_export_is_authenticated_and_user_scoped(tmp_path, monkeypatch):
    service = Service(tmp_path / "data")
    dest = tmp_path / "export.csv"
    monkeypatch.setattr(service, "dialog", lambda *args: str(dest))
    assert service.call("logs_csv")["error"]["code"] == "GPP-102"
    token = service.call("register", {"username": "Alice", "password": "long private passphrase"})["data"][
        "token"
    ]
    assert service.call("logs_csv", {}, token)["ok"] and dest.is_file()
    assert not service.settings.advanced
    with service.store.connect() as con:
        service.store.audit(con, "Alice", "alice-private-event")
    service.call("create_user", {"username": "Bobby", "password": "long private passphrase"}, token)
    service.call("logout", {}, token)
    bob = service.call("login", {"username": "Bobby", "password": "long private passphrase"})["data"]["token"]
    assert service.call("logs_csv", {}, bob)["ok"]
    assert "alice-private-event" not in dest.read_text()


def test_failure_diagnostics_keep_stage_and_cause_but_no_exception_text(tmp_path):
    logger = logger_for(tmp_path / "profile" / "logs")
    try:
        try:
            raise TimeoutError("SECRET PASSWORD /private/user/photo.jpg")
        except TimeoutError as cause:
            error = AppError("GPP-403")
            error.stage = "set_files"
            raise error from cause
    except AppError as exc:
        detail = log_event(logger, "operation.error", "GPP-403", exc)
    assert detail["stage"] == "set_files" and detail["cause_types"] == ["TimeoutError"]
    raw = (tmp_path / "profile/logs/events.jsonl").read_text()
    assert "SECRET PASSWORD" not in raw and "/private/user" not in raw


def test_no_ready_items_does_not_start_browser_or_record_finished_run(tmp_path):
    service = Service(tmp_path / "data")
    token = service.call("register", {"username": "Alice", "password": "long private passphrase"})["data"][
        "token"
    ]
    assert service.call("upload", {}, token)["error"]["code"] == "GPP-415"
    with service.store.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_upload_run_records_review_outcome_instead_of_finished(tmp_path, monkeypatch):
    from photorestore.scanner import Scanner

    service = Service(tmp_path / "data")
    service.call("register", {"username": "Alice", "password": "long private passphrase"})
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.jpg").write_bytes(b"one")
    Scanner(service.store, "test", service.settings).scan(source)
    with service.store.connect() as con:
        con.execute("UPDATE items SET status='review',code='GPP-403'")

    class Browser:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class Engine:
        def __init__(self, *args):
            pass

        def run(self, *args, **kwargs):
            return 0

    monkeypatch.setattr("photorestore.service.GoogleBrowser", Browser)
    monkeypatch.setattr("photorestore.service.UploadEngine", Engine)
    monkeypatch.setattr("photorestore.service.exiftool_path", lambda: tmp_path / "tool")
    service.start("upload")
    service.thread.join(5)
    assert service.job["outcome"] == "needs_review"
    with service.store.connect() as con:
        assert con.execute("SELECT status FROM runs").fetchone()[0] == "needs_review"
        detail = json.loads(
            con.execute("SELECT detail FROM audit WHERE action='operation.needs_review'").fetchone()[0]
        )
        assert detail["count"] == 0 and detail["remaining"]["review"] == 1
