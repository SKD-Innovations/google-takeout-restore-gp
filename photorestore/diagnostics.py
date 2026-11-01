import csv
import hashlib
import json
import logging
import platform
import traceback
import zipfile
from logging.handlers import RotatingFileHandler
from . import __version__
from .errors import CATALOG
from .store import now


def logger_for(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    logger = logging.getLogger("takeout." + hashlib.sha256(str(directory.resolve()).encode()).hexdigest())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            directory / "events.jsonl", maxBytes=2_000_000, backupCount=4, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    return logger


def log_event(logger, event, code=None, exc=None):
    value = {"time": now(), "event": event, "code": code}
    if exc:
        # No exception message, locals, source line text, username or absolute paths.
        value["exception_type"] = type(exc).__name__
        value["frames"] = [
            {"file": f.filename.replace("\\", "/").split("/")[-1], "line": f.lineno, "function": f.name}
            for f in traceback.extract_tb(exc.__traceback__)[-15:]
        ]
    if exc:
        stages = {
            "open_upload",
            "choose_file",
            "set_files",
            "quality_prompt",
            "wait_confirmation",
            "confirmation_timeout",
        }
        if getattr(exc, "stage", None) in stages:
            value["stage"] = exc.stage
        cause = exc.__cause__
        seen = {id(exc)}
        causes = []
        while cause is not None and id(cause) not in seen and len(causes) < 5:
            seen.add(id(cause))
            causes.append(type(cause).__name__)
            cause = cause.__cause__
        if causes:
            value["cause_types"] = causes
    logger.info(json.dumps(value))
    return {k: value[k] for k in ("exception_type", "stage", "cause_types") if k in value}


def diagnostics_bundle(path, store, profile):
    head = store.verify_audit()
    with store.connect() as con:
        counts = dict(con.execute("SELECT status,COUNT(*) FROM items GROUP BY status").fetchall())
        codes = dict(
            con.execute("SELECT code,COUNT(*) FROM items WHERE code IS NOT NULL GROUP BY code").fetchall()
        )
    info = {
        "version": __version__,
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "created": now(),
        "counts": counts,
        "codes": codes,
        "audit_head": head,
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("diagnostics.json", json.dumps(info, indent=2))
        z.writestr(
            "README.txt",
            "Contains counts, error codes and redacted stack locations only. No media, names, paths, Google sessions or databases. Review before sharing.\n",
        )
        for log in sorted((profile / "logs").glob("events.jsonl*")):
            z.write(log, "logs/" + log.name)


def csv_safe(value):
    value = str(value or "")
    return "'" + value if value[:1] in "=+-@\t\r\n" else value


def export_report(path, store):
    # Reports intentionally contain personal filenames and restoration intent, unlike diagnostics.
    with path.open("w", newline="", encoding="utf-8-sig") as output, store.connect() as con:
        writer = csv.writer(output)
        writer.writerow(
            [
                "Item",
                "File",
                "Status",
                "Error code",
                "Explanation",
                "Attempts",
                "SHA-256",
                "Albums",
                "Favorite requested",
                "Archive requested",
                "Warnings",
                "Browser receipt",
            ]
        )
        for row in con.execute("SELECT * FROM items ORDER BY id"):
            meta = json.loads(row["metadata"])
            albums = [
                a[0] for a in con.execute("SELECT album FROM occurrences WHERE item_id=?", (row["id"],))
            ]
            values = [
                row["id"],
                row["relative"],
                row["status"],
                row["code"],
                CATALOG.get(row["code"], ("", ""))[1],
                row["attempts"],
                row["sha256"],
                "; ".join(albums),
                meta.get("favorited", False),
                meta.get("archived", False),
                row["warnings"],
                row["receipt"],
            ]
            writer.writerow([csv_safe(v) for v in values])


def export_logs_csv(path, store):
    """Stream the current user's complete audit trail, including error explanations."""
    with path.open("w", newline="", encoding="utf-8-sig") as output, store.connect() as con:
        writer = csv.writer(output)
        writer.writerow(
            [
                "Sequence",
                "Time (UTC)",
                "Event",
                "Details",
                "Error code",
                "Description",
                "Run ID",
                "Item ID",
                "Actor",
                "Previous hash",
                "Hash",
            ]
        )
        for row in con.execute("SELECT * FROM audit ORDER BY seq"):
            try:
                detail = json.loads(row["detail"])
            except (ValueError, TypeError):
                detail = {}
            if not isinstance(detail, dict):
                detail = {}
            code = detail.get("code")
            writer.writerow(
                [
                    csv_safe(v)
                    for v in [
                        row["seq"],
                        row["time"],
                        row["action"],
                        row["detail"],
                        code,
                        CATALOG.get(code, ("", ""))[1],
                        detail.get("run"),
                        detail.get("item"),
                        row["actor"],
                        row["previous"],
                        row["digest"],
                    ]
                ]
            )
