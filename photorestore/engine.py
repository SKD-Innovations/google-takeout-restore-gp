import hashlib
import errno
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from .errors import AppError
from .metadata import PHOTOS, apply_metadata
from .scanner import Cancelled
from .store import canonical, now


PIXEL_CHECK_LOCK = threading.Lock()


def stage(item, directory, settings, stop):
    source = Path(item["source"])
    original = source / item["relative"]
    if original.is_symlink() or not original.resolve().is_relative_to(source.resolve()):
        raise AppError("GPP-205")
    try:
        before = original.stat()
        if (before.st_size, before.st_mtime_ns) != (item["size"], item["mtime"]):
            raise AppError("GPP-202")
        required = item["size"] * 3 + 512 * 1024**2
        if required > settings.scratch_gb * 1024**3 or required > shutil.disk_usage(directory).free:
            raise AppError("GPP-204")
        dest = directory / original.name
        digest = hashlib.sha256()
        with original.open("rb") as src, dest.open("xb") as dst:
            while chunk := src.read(1024 * 1024):
                if stop.is_set():
                    raise Cancelled()
                digest.update(chunk)
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        os.utime(dest, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = original.stat()
        if digest.hexdigest() != item["sha256"] or (before.st_size, before.st_mtime_ns, before.st_ino) != (
            after.st_size,
            after.st_mtime_ns,
            after.st_ino,
        ):
            raise AppError("GPP-202")
        if original.suffix.lower() in PHOTOS and settings.oversize == "skip":
            from PIL import Image, UnidentifiedImageError

            # Header-only inspection; no decompression. Restore the Pillow threshold under a lock.
            try:
                import warnings

                with PIXEL_CHECK_LOCK, warnings.catch_warnings():
                    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
                    previous_limit = Image.MAX_IMAGE_PIXELS
                    Image.MAX_IMAGE_PIXELS = 200_000_000
                    try:
                        with Image.open(dest) as im:
                            if im.width * im.height > 200_000_000:
                                raise AppError("GPP-203")
                    finally:
                        Image.MAX_IMAGE_PIXELS = previous_limit
            except Image.DecompressionBombError as exc:
                raise AppError("GPP-203") from exc
            except UnidentifiedImageError:
                pass  # HEIC/RAW may need ExifTool; browser still validates format.
        return dest
    except OSError as exc:
        raise AppError("GPP-204" if exc.errno == errno.ENOSPC else "GPP-201") from exc


class UploadEngine:
    def __init__(self, store, actor, settings, profile, tool, stop, progress):
        self.store, self.actor, self.settings = store, actor, settings
        self.profile, self.tool, self.stop, self.progress = profile, tool, stop, progress

    def transition(self, item_id, status, code=None, receipt=None):
        with self.store.connect() as con:
            con.execute(
                "UPDATE items SET status=?,code=?,receipt=COALESCE(?,receipt),updated=? WHERE id=?",
                (status, code, canonical(receipt) if receipt else None, now(), item_id),
            )
            self.store.audit(con, self.actor, "item." + status, {"item": item_id, "code": code})

    def run(self, browser, max_items=None):
        scratch = self.profile / "scratch"
        scratch.mkdir(exist_ok=True, mode=0o700)
        count, last_pair = 0, None
        while not self.stop.is_set() and (max_items is None or count < max_items):
            with self.store.connect() as con:
                item = None
                if last_pair and self.settings.pairs == "together":
                    item = con.execute(
                        "SELECT * FROM items WHERE status='pending' AND pair_key=? AND attempts<? ORDER BY id LIMIT 1",
                        (last_pair, self.settings.retry_limit),
                    ).fetchone()
                if not item:
                    item = con.execute(
                        "SELECT * FROM items WHERE status='pending' AND attempts<? ORDER BY id LIMIT 1",
                        (self.settings.retry_limit,),
                    ).fetchone()
                if not item:
                    break
                item = dict(item)
                con.execute(
                    "UPDATE items SET status='preparing',attempts=attempts+1,updated=? WHERE id=?",
                    (now(), item["id"]),
                )
            last_pair = item["pair_key"]
            self.progress("Preparing item " + str(item["id"]), count)
            try:
                with tempfile.TemporaryDirectory(dir=scratch, prefix="item-") as tmp:
                    staged = stage(item, Path(tmp), self.settings, self.stop)
                    metadata = json.loads(item["metadata"])
                    apply_metadata(self.tool, staged, metadata, self.settings.descriptions == "carry")
                    self.progress("Uploading item " + str(item["id"]), count)
                    receipt = browser.upload(
                        staged,
                        self.settings.upload_timeout_minutes,
                        lambda item_id=item["id"]: self.transition(item_id, "uploading"),
                    )
                    with self.store.connect() as con:
                        albums = con.execute(
                            "SELECT album FROM occurrences WHERE item_id=?", (item["id"],)
                        ).fetchall()
                        pair = con.execute(
                            "SELECT 1 FROM items WHERE pair_key=? AND id!=? LIMIT 1",
                            (item["pair_key"], item["id"]),
                        ).fetchone()
                    needs_review = (
                        (albums and self.settings.albums == "recreate")
                        or (metadata.get("favorited") and self.settings.favorites == "carry")
                        or (metadata.get("archived") and self.settings.archive == "carry")
                        or (pair and self.settings.pairs == "together")
                    )
                    self.transition(
                        item["id"],
                        "restoration_review" if needs_review else "uploaded",
                        "GPP-304" if needs_review else None,
                        receipt,
                    )
                    count += 1
                    if hasattr(browser, "dismiss_confirmation"):
                        browser.dismiss_confirmation()
            except Cancelled:
                self.transition(item["id"], "pending")
                raise
            except AppError as exc:
                with self.store.connect() as con:
                    current = con.execute("SELECT status FROM items WHERE id=?", (item["id"],)).fetchone()[0]
                unknown = current == "uploading" and exc.code != "GPP-404"
                if (
                    current != "uploading"
                    and exc.code == "GPP-407"
                    and item["attempts"] + 1 < self.settings.retry_limit
                ):
                    delay = min(30, 2 ** (item["attempts"] + 1))
                    self.transition(item["id"], "pending", exc.code)
                    self.progress(f"Connection interrupted — retrying safely in {delay} seconds", count)
                    self.stop.wait(delay)
                    continue
                self.transition(
                    item["id"], "review" if unknown else "failed", "GPP-403" if unknown else exc.code
                )
                if (
                    exc.code
                    in (
                        "GPP-201",
                        "GPP-204",
                        "GPP-303",
                        "GPP-401",
                        "GPP-402",
                        "GPP-403",
                        "GPP-407",
                        "GPP-409",
                        "GPP-410",
                        "GPP-411",
                        "GPP-412",
                        "GPP-414",
                    )
                    or unknown
                ):
                    raise
            except Exception as exc:
                with self.store.connect() as con:
                    current = con.execute("SELECT status FROM items WHERE id=?", (item["id"],)).fetchone()[0]
                self.transition(
                    item["id"],
                    "review" if current == "uploading" else "failed",
                    "GPP-403" if current == "uploading" else "GPP-901",
                )
                raise AppError("GPP-901") from exc
        return count
