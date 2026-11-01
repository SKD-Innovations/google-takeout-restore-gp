import json
import pytest
from photorestore.errors import AppError
from photorestore.metadata import normalize


def rows(store):
    with store.connect() as c:
        return [dict(x) for x in c.execute("SELECT * FROM items ORDER BY id")]


def test_hash_dedupes_content_not_names(source, scan, store):
    (source / "a.jpg").write_bytes(b"one")
    (source / "b.jpg").write_bytes(b"one")
    (source / "nested").mkdir()
    (source / "nested" / "a.jpg").write_bytes(b"two")
    assert scan(source) == 3
    assert [r["status"] for r in rows(store)].count("pending") == 2
    assert [r["code"] for r in rows(store)].count("GPP-206") == 1
    scan(source)
    assert len(rows(store)) == 3


def test_extracted_sidecar_and_epoch_zero(source, scan, store):
    (source / "a.jpg").write_bytes(b"one")
    (source / "a.jpg.supplemental-metadata.json").write_text(
        json.dumps({"photoTakenTime": {"timestamp": "0"}, "description": "hello"})
    )
    scan(source)
    meta = json.loads(rows(store)[0]["metadata"])
    assert meta["taken"] == "1970-01-01T00:00:00+00:00"
    assert meta["description"] == "hello"


def test_truncated_title_matching_and_ambiguity(source, scan, store):
    media = "a very long and important original name.jpg"
    (source / media).write_bytes(b"one")
    sidecar = {"title": media, "photoTakenTime": {"timestamp": "123"}}
    (source / "truncated.json").write_text(json.dumps(sidecar))
    scan(source)
    assert rows(store)[0]["status"] == "pending"
    (source / "another-truncated.json").write_text(json.dumps(sidecar))
    scan(source)
    assert rows(store)[0]["code"] == "GPP-301"


def test_malformed_metadata_stops_item(source, scan, store):
    (source / "a.jpg").write_bytes(b"one")
    (source / "a.jpg.json").write_text("{broken")
    scan(source)
    assert rows(store)[0]["status"] == "failed"
    assert rows(store)[0]["code"] == "GPP-301"


def test_edited_rules(source, scan, store):
    (source / "a.jpg").write_bytes(b"one")
    (source / "a-edited.jpg").write_bytes(b"two")
    scan(source, edited="only_edited")
    byname = {r["name"]: r for r in rows(store)}
    assert byname["a.jpg"]["status"] == "skipped"
    assert byname["a-edited.jpg"]["status"] == "pending"
    scan(source, edited="skip")
    byname = {r["name"]: r for r in rows(store)}
    assert byname["a.jpg"]["status"] == "pending"
    assert byname["a-edited.jpg"]["status"] == "skipped"


def test_symlink_not_followed(source, scan, store, tmp_path):
    original = tmp_path / "secret.jpg"
    original.write_bytes(b"one")
    try:
        (source / "a.jpg").symlink_to(original)
    except OSError:
        pytest.skip("symlink privilege unavailable")
    scan(source)
    assert rows(store)[0]["code"] == "GPP-205"


def test_rescan_preserves_upload_evidence(source, scan, store):
    (source / "a.jpg").write_bytes(b"one")
    scan(source)
    with store.connect() as c:
        c.execute("UPDATE items SET status='uploaded',receipt='proof'")
    (source / "a.jpg").write_bytes(b"two")
    scan(source)
    row = rows(store)[0]
    assert row["status"] == "restoration_review" and row["receipt"] == "proof" and row["code"] == "GPP-202"


def test_duplicate_album_memberships_preserved(source, scan, store):
    for folder, album in [("one", "Holiday"), ("two", "Family")]:
        p = source / folder
        p.mkdir()
        (p / "a.jpg").write_bytes(b"one")
        (p / "metadata.json").write_text(json.dumps({"albumData": {"title": album}}))
    scan(source)
    with store.connect() as c:
        assert c.execute("SELECT COUNT(DISTINCT item_id) FROM occurrences").fetchone()[0] == 1
        assert c.execute("SELECT COUNT(*) FROM occurrences").fetchone()[0] == 2


def test_invalid_coordinates_and_descriptions():
    with pytest.raises(AppError):
        normalize({"geoData": {"latitude": float("nan"), "longitude": 0}})
    with pytest.raises(AppError):
        normalize({"description": ["not a string"]})
    assert normalize({"geoData": {"latitude": 0, "longitude": 12, "altitude": -3}})["geo"] == {
        "lat": 0,
        "lon": 12,
        "alt": -3,
    }


def test_conflicting_metadata_on_identical_bytes_is_not_silently_discarded(source, scan, store):
    for name, stamp in [("a", 100), ("b", 200)]:
        (source / (name + ".jpg")).write_bytes(b"identical")
        (source / (name + ".jpg.json")).write_text(json.dumps({"photoTakenTime": {"timestamp": str(stamp)}}))
    scan(source)
    assert all(row["status"] == "failed" and row["code"] == "GPP-301" for row in rows(store))
