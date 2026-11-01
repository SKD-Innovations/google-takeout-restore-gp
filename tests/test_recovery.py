import json
import threading
import pytest
from photorestore.engine import UploadEngine, stage
from photorestore.errors import AppError
from photorestore.settings import Settings
from photorestore.scanner import Cancelled
from photorestore.store import Store


def item(store):
    with store.connect() as c:
        return dict(c.execute("SELECT * FROM items LIMIT 1").fetchone())


def test_crash_recovery_never_blindly_retries_submitted(source, scan, store):
    (source / "a.jpg").write_bytes(b"one")
    (source / "b.jpg").write_bytes(b"two")
    scan(source)
    with store.connect() as c:
        c.execute("UPDATE items SET status='uploading' WHERE name='a.jpg'")
        c.execute("UPDATE items SET status='preparing' WHERE name='b.jpg'")
    store.recover("test")
    with store.connect() as c:
        assert dict(c.execute("SELECT name,status FROM items")) == {"a.jpg": "review", "b.jpg": "pending"}


def test_stage_preserves_original_and_detects_changes(source, scan, store, tmp_path):
    original = source / "a.jpg"
    original.write_bytes(b"original")
    scan(source)
    work = tmp_path / "work"
    work.mkdir()
    staged = stage(item(store), work, Settings(), threading.Event())
    assert staged.stat().st_mtime_ns == original.stat().st_mtime_ns
    staged.write_bytes(b"edited")
    assert original.read_bytes() == b"original"
    original.write_bytes(b"changed")
    with pytest.raises(AppError, match="GPP-202"):
        stage(item(store), work, Settings(), threading.Event())


def test_no_space_prevents_upload(source, scan, store, tmp_path, monkeypatch):
    (source / "a.jpg").write_bytes(b"one")
    scan(source)
    work = tmp_path / "work"
    work.mkdir()

    class Disk:
        free = 0

    monkeypatch.setattr("photorestore.engine.shutil.disk_usage", lambda _: Disk())
    with pytest.raises(AppError, match="GPP-204"):
        stage(item(store), work, Settings(), threading.Event())


class UnknownBrowser:
    def upload(self, path, timeout, mark):
        mark()
        raise AppError("GPP-403")


class SuccessBrowser:
    def upload(self, path, timeout, mark):
        mark()
        return {"kind": "test"}


def test_unknown_upload_is_not_retried(source, scan, store, tmp_path):
    (source / "a.jpg").write_bytes(b"one")
    scan(source)
    engine = UploadEngine(
        store, "test", Settings(), store.path.parent, tmp_path / "tool", threading.Event(), lambda *a: None
    )
    with pytest.raises(AppError, match="GPP-403"):
        engine.run(UnknownBrowser())
    assert item(store)["status"] == "review"
    assert engine.run(SuccessBrowser()) == 0
    assert item(store)["attempts"] == 1


def test_uploaded_cloud_only_intent_gets_review(source, scan, store, tmp_path, monkeypatch):
    (source / "a.jpg").write_bytes(b"one")
    (source / "a.jpg.json").write_text(json.dumps({"favorited": True}))
    scan(source)
    monkeypatch.setattr("photorestore.engine.apply_metadata", lambda *a: None)
    engine = UploadEngine(
        store, "test", Settings(), store.path.parent, tmp_path / "tool", threading.Event(), lambda *a: None
    )
    assert engine.run(SuccessBrowser()) == 1
    assert item(store)["status"] == "restoration_review"


def test_cancel_before_submission_returns_pending(source, scan, store, tmp_path, monkeypatch):
    (source / "a.jpg").write_bytes(b"one")
    scan(source)

    def cancel(*_):
        raise Cancelled()

    monkeypatch.setattr("photorestore.engine.stage", cancel)
    engine = UploadEngine(
        store, "test", Settings(), store.path.parent, tmp_path / "tool", threading.Event(), lambda *a: None
    )
    with pytest.raises(Cancelled):
        engine.run(SuccessBrowser())
    assert item(store)["status"] == "pending"


def test_audit_detects_changes(store):
    with store.connect() as c:
        store.audit(c, "actor", "example", {"one": 1})
    store.verify_audit()
    with store.connect() as c:
        c.execute("UPDATE audit SET action='tampered'")
    with pytest.raises(AppError, match="GPP-502"):
        store.verify_audit()


def test_newer_schema_is_not_overwritten(tmp_path):
    store = Store(tmp_path / "new.sqlite")
    store.initialize(True)
    with store.connect() as c:
        c.execute("PRAGMA user_version=999")
    with pytest.raises(AppError, match="GPP-503"):
        store.initialize(True)


def test_pre_submission_connection_retry_is_bounded(source, scan, store, tmp_path):
    (source / "a.jpg").write_bytes(b"one")
    scan(source)

    class Stop:
        def is_set(self):
            return False

        def wait(self, seconds):
            return False

    class Offline:
        calls = 0

        def upload(self, path, timeout, mark):
            self.calls += 1
            raise AppError("GPP-407")

    browser = Offline()
    engine = UploadEngine(
        store, "test", Settings(retry_limit=3), store.path.parent, tmp_path / "tool", Stop(), lambda *a: None
    )
    with pytest.raises(AppError, match="GPP-407"):
        engine.run(browser)
    assert browser.calls == 3 and item(store)["attempts"] == 3 and item(store)["status"] == "failed"


@pytest.mark.parametrize("width,accepted", [(19000, True), (21000, False)])
def test_pixel_limit_uses_google_threshold_not_pillow_default(source, scan, store, tmp_path, width, accepted):
    import struct, zlib

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, 10000, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b""))
        + chunk(b"IEND", b"")
    )
    (source / "large.png").write_bytes(raw)
    scan(source)
    work = tmp_path / "work"
    work.mkdir()
    if accepted:
        assert stage(item(store), work, Settings(), threading.Event()).is_file()
    else:
        with pytest.raises(AppError, match="GPP-203"):
            stage(item(store), work, Settings(), threading.Event())


def test_sample_upload_leaves_remaining_queue_ready(source, scan, store, tmp_path):
    for name in ("a", "b", "c"):
        (source / (name + ".jpg")).write_bytes(name.encode())
    scan(source)
    engine = UploadEngine(
        store, "test", Settings(), store.path.parent, tmp_path / "tool", threading.Event(), lambda *a: None
    )
    assert engine.run(SuccessBrowser(), max_items=2) == 2
    with store.connect() as con:
        assert dict(con.execute("SELECT status,COUNT(*) FROM items GROUP BY status")) == {
            "pending": 1,
            "uploaded": 2,
        }


def test_blocked_google_authorization_stops_remaining_queue(source, scan, store, tmp_path):
    for name in ("a", "b", "c"):
        (source / (name + ".jpg")).write_bytes(name.encode())
    scan(source)

    class BlockedBrowser:
        def upload(self, path, timeout, mark):
            raise AppError("GPP-410")

    engine = UploadEngine(
        store, "test", Settings(), store.path.parent, tmp_path / "tool", threading.Event(), lambda *args: None
    )
    with pytest.raises(AppError, match="GPP-410"):
        engine.run(BlockedBrowser())
    with store.connect() as con:
        assert dict(con.execute("SELECT status,COUNT(*) FROM items GROUP BY status")) == {
            "failed": 1,
            "pending": 2,
        }
