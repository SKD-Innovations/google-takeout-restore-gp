"""Two-pass, bounded-memory indexing. All decisions survive process restarts."""

import hashlib
import json
import os
import threading
from pathlib import Path
from .errors import AppError
from .metadata import EDITED, PHOTOS, SUPPORTED, normalize, read_sidecar, resolve_metadata
from .store import canonical, now


class Cancelled(Exception):
    pass


def digest_file(path, stop=None):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            if stop and stop.is_set():
                raise Cancelled()
            digest.update(chunk)
    return digest.hexdigest()


def walk_files(root, stop):
    # Stream entries instead of os.walk's full per-directory filename lists. A huge
    # flat Takeout folder therefore does not require a huge in-memory listing.
    stack = []
    try:
        stack.append(os.scandir(root))
        while stack:
            if stop.is_set():
                raise Cancelled()
            try:
                entry = next(stack[-1])
            except StopIteration:
                stack.pop().close()
                continue
            if entry.name.startswith("."):
                continue
            if entry.is_dir(follow_symlinks=False):
                if len(stack) >= 256:
                    raise AppError("GPP-208")
                stack.append(os.scandir(entry.path))
            else:
                yield Path(entry.path)
    except OSError as exc:
        raise AppError("GPP-208") from exc
    finally:
        for iterator in stack:
            iterator.close()


class Scanner:
    def __init__(self, store, actor, settings, stop=None, progress=None):
        self.store, self.actor, self.settings = store, actor, settings
        self.stop = stop or threading.Event()
        self.progress = progress or (lambda *args: None)

    def scan(self, source):
        try:
            source = Path(source).resolve(strict=True)
            if not source.is_dir():
                raise AppError("GPP-201")
        except OSError as exc:
            raise AppError("GPP-201") from exc
        # Use SQLite as the sidecar index, including truncated names with exact title matches.
        with self.store.connect() as con:
            con.execute("DELETE FROM sidecars")
        sidecar_count = 0
        for path in walk_files(source, self.stop):
            if path.suffix.lower() != ".json":
                continue
            invalid, data, title = 0, None, None
            try:
                raw = read_sidecar(path)
                title = raw.get("title") if isinstance(raw.get("title"), str) else None
                # Album JSON is handled separately; it is not photo metadata.
                data = canonical(normalize(raw))
            except AppError:
                invalid = 1
            with self.store.connect() as con:
                con.execute(
                    "INSERT OR REPLACE INTO sidecars VALUES(?,?,?,?,?)",
                    (str(path), str(path.parent), title, data, invalid),
                )
            sidecar_count += 1
            self.progress("Indexing metadata sidecars", sidecar_count)
        count = 0
        for path in walk_files(source, self.stop):
            if path.suffix.lower() not in SUPPORTED:
                continue
            self.index_one(source, path)
            count += 1
            self.progress("Scanning files", count)
        return count

    def index_one(self, source, path):
        stamp = now()
        status, code, sha, meta, warnings = "pending", None, None, {}, []
        size, mtime = 0, 0
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise AppError("GPP-205")
            before = path.stat()
            size, mtime = before.st_size, before.st_mtime_ns
            edited = bool(EDITED.search(path.stem))
            if self.settings.edited == "skip" and edited:
                status, code = "skipped", "GPP-207"
            elif self.settings.edited == "only_edited" and not edited:
                if any(
                    (path.parent / (path.stem + suffix + path.suffix)).is_file()
                    for suffix in ("-edited", " - edited", "_edited")
                ):
                    status, code = "skipped", "GPP-207"
            limit = 200_000_000 if path.suffix.lower() in PHOTOS else 10_000_000_000
            if size == 0:
                raise AppError("GPP-201")
            if size > limit and self.settings.oversize == "skip":
                status, code = "rejected", "GPP-203"
            with self.store.connect() as con:
                found = resolve_metadata(con, path)
            if found is None:
                warnings.append("No matched sidecar; embedded metadata will be retained.")
            else:
                meta = found
            # Read album metadata only if it has the Takeout album shape.
            album_file = path.parent / "metadata.json"
            if self.settings.albums == "recreate" and album_file.is_file():
                album_data = read_sidecar(album_file)
                album = album_data.get("albumData", {}).get("title")
                if isinstance(album, str) and album.strip():
                    meta["album"] = album[:1000]
            if status == "pending":
                sha = digest_file(path, self.stop)
                after = path.stat()
                if (size, mtime, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                    raise AppError("GPP-202")
        except AppError as exc:
            status, code = "rejected" if exc.code in ("GPP-203", "GPP-205") else "failed", exc.code
        except (OSError, ValueError, TypeError, AttributeError):
            status, code = "failed", "GPP-201"
        fingerprint = (
            sha
            if self.settings.duplicates == "hash"
            else (canonical([path.name, size]) if self.settings.duplicates == "name_size" else None)
        )
        relative = str(path.relative_to(source))
        pair = str(path.with_suffix("")) if self.settings.pairs == "together" else str(path)
        with self.store.connect() as con:
            existing = con.execute(
                "SELECT * FROM items WHERE source=? AND relative=?", (str(source), relative)
            ).fetchone()
            if existing and existing["status"] in ("uploaded", "restoration_review", "review", "verified"):
                # Never erase evidence of a remote side effect on a rescan.
                if sha and existing["sha256"] != sha:
                    con.execute(
                        "UPDATE items SET status='restoration_review',code='GPP-202',updated=? WHERE id=?",
                        (stamp, existing["id"]),
                    )
                return
            duplicate = None
            if status == "pending" and fingerprint:
                duplicate = con.execute(
                    "SELECT id,metadata,status FROM items WHERE fingerprint=? AND id!=? AND status NOT IN ('skipped','rejected','failed') LIMIT 1",
                    (fingerprint, existing["id"] if existing else -1),
                ).fetchone()
                if duplicate:
                    status, code = "skipped", "GPP-206"
                    previous_meta = json.loads(duplicate["metadata"])
                    conflicts = any(
                        k in meta and k in previous_meta and meta[k] != previous_meta[k]
                        for k in ("taken", "geo", "description")
                    )
                    remote = duplicate["status"] in ("uploaded", "restoration_review", "verified", "review")
                    if conflicts:
                        status, code = "failed", "GPP-301"
                        con.execute(
                            "UPDATE items SET status=?,code=?,updated=? WHERE id=?",
                            ("restoration_review" if remote else "failed", "GPP-301", stamp, duplicate["id"]),
                        )
                    elif not remote:
                        merged = {**meta, **previous_meta}
                        for key in ("favorited", "archived"):
                            if key in meta or key in previous_meta:
                                merged[key] = bool(meta.get(key) or previous_meta.get(key))
                        con.execute(
                            "UPDATE items SET metadata=? WHERE id=?", (canonical(merged), duplicate["id"])
                        )
                    elif meta.get("album") or meta.get("favorited") or meta.get("archived"):
                        con.execute(
                            "UPDATE items SET status='restoration_review',code='GPP-304',updated=? WHERE id=?",
                            (stamp, duplicate["id"]),
                        )
            values = (
                str(source),
                relative,
                path.name,
                size,
                mtime,
                sha,
                fingerprint,
                status,
                code,
                canonical(meta),
                canonical(warnings),
                pair,
                stamp,
                stamp,
            )
            con.execute(
                """INSERT INTO items(source,relative,name,size,mtime,sha256,fingerprint,status,code,metadata,warnings,pair_key,created,updated)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,relative) DO UPDATE SET
                           size=excluded.size,mtime=excluded.mtime,sha256=excluded.sha256,fingerprint=excluded.fingerprint,
                           status=excluded.status,code=excluded.code,metadata=excluded.metadata,warnings=excluded.warnings,
                           pair_key=excluded.pair_key,attempts=0,updated=excluded.updated""",
                values,
            )
            item_id = con.execute(
                "SELECT id FROM items WHERE source=? AND relative=?", (str(source), relative)
            ).fetchone()[0]
            if meta.get("album"):
                con.execute(
                    "INSERT OR IGNORE INTO occurrences VALUES(?,?)",
                    (duplicate["id"] if duplicate else item_id, meta["album"]),
                )
            self.store.audit(
                con, self.actor, "item.indexed", {"item": item_id, "status": status, "code": code}
            )
