"""User-reviewed incident reports. No SMTP, automatic uploads, or raw database exports."""

import hashlib
import json
import platform
import re
import sys
import uuid
import zipfile
from functools import lru_cache
from pathlib import Path
from . import __version__
from .errors import CATALOG
from .store import now

SUPPORT_EMAIL = "sarthakg043@gmail.com"
# These indicate an unexpected app/component/website outcome, not proof of blame.
REPORTABLE_CODES = frozenset(
    {
        "GPP-111",
        "GPP-303",
        "GPP-402",
        "GPP-403",
        "GPP-406",
        "GPP-408",
        "GPP-414",
        "GPP-501",
        "GPP-502",
        "GPP-901",
    }
)
OPERATIONS = frozenset(
    {
        "manual_report",
        "startup",
        "application_crash",
        "install_browser",
        "scan",
        "connect_google",
        "test_google",
        "upload",
        "upload_sample",
        "report",
        "diagnostics",
        "logs_csv",
        "send_report",
        "save_recovery",
        "save_settings",
        "reset_settings",
        "login",
        "register",
        "item_action",
        "queue",
        "history",
        "status",
        "logs",
        "users",
        "create_user",
        "manage_user",
        "change_password",
        "disconnect_google",
        "other",
    }
)
STAGES = frozenset(
    {"open_upload", "choose_file", "set_files", "quality_prompt", "wait_confirmation", "confirmation_timeout"}
)


def safe_label(value):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", value) else None


def safe_exception(exc):
    if exc is None:
        return {}
    import traceback

    own_files = {p.name for p in Path(__file__).parent.glob("*.py")}
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__)[-12:]:
        name = Path(frame.filename).name
        if name in own_files and safe_label(frame.name):
            frames.append({"file": name, "line": frame.lineno, "function": frame.name})
    detail = {"exception_type": safe_label(type(exc).__name__), "frames": frames}
    if getattr(exc, "stage", None) in STAGES:
        detail["stage"] = exc.stage
    causes, seen, cause = [], {id(exc)}, exc.__cause__
    while cause is not None and id(cause) not in seen and len(causes) < 4:
        seen.add(id(cause))
        if label := safe_label(type(cause).__name__):
            causes.append(label)
        cause = cause.__cause__
    if causes:
        detail["cause_types"] = causes
    return detail


def new_incident(code=None, operation="manual_report", exc=None, run_id=None):
    return {
        "id": uuid.uuid4().hex,
        "created": now(),
        "code": code if code in CATALOG else None,
        "operation": operation if operation in OPERATIONS else "other",
        "run_id": run_id if isinstance(run_id, str) and re.fullmatch(r"[a-f0-9]{32}", run_id) else None,
        "detail": safe_exception(exc),
    }


def public_incident(incident):
    title, explanation = CATALOG.get(
        incident["code"], ("Manual incident report", "Tell us what happened in the email draft.")
    )
    return {
        "id": incident["id"],
        "created": incident["created"],
        "code": incident["code"],
        "title": title,
        "message": explanation,
    }


@lru_cache(maxsize=1)
def app_identity():
    result = {
        "name": "Takeout Restore",
        "version": __version__,
        "build_id": None,
        "executable_sha256": None,
        "hash_scope": "Source/dependency fingerprint and installed launcher executable; not a DMG hash.",
    }
    try:
        manifest = json.loads((Path(__file__).parent / "resources/build.json").read_text())
        if manifest.get("version") == __version__ and re.fullmatch(
            r"[a-f0-9]{64}", manifest.get("build_id", "")
        ):
            result["build_id"] = manifest["build_id"]
    except (OSError, ValueError, TypeError):
        pass
    if getattr(sys, "frozen", False):
        try:
            with Path(sys.executable).open("rb") as source:
                result["executable_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
        except OSError:
            pass
    return result


def redacted_events(profile):
    """Never copy raw logs: use a strict field/format allowlist and bounded input."""
    result = []
    if profile is None:
        return result
    for path in sorted((profile / "logs").glob("events.jsonl*"))[:5]:
        if path.is_symlink() or not path.is_file():
            continue
        try:
            with path.open("rb") as source:
                source.seek(max(0, path.stat().st_size - 128_000))
                lines = source.read(128_000).splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                record = json.loads(line)
            except (ValueError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            event = record.get("event")
            if event not in {
                "operation.error",
                "operation.commit_error",
                "database.error",
                "application.error",
                "application.crash",
                "startup.error",
                "upload.confirmation_close_failed",
            }:
                continue
            value = {"event": event}
            if record.get("code") in CATALOG:
                value["code"] = record["code"]
            stamp = record.get("time")
            if isinstance(stamp, str) and re.fullmatch(r"[0-9T:+.Z-]{10,40}", stamp):
                value["time"] = stamp
            if label := safe_label(record.get("exception_type")):
                value["exception_type"] = label
            if record.get("stage") in STAGES:
                value["stage"] = record["stage"]
            result.append(value)
    return sorted(result, key=lambda r: r.get("time", ""))[-200:]


def write_incident_bundle(path, incident, store=None, profile=None):
    identity = app_identity()
    info = {
        "incident": incident,
        "application": identity,
        "created": now(),
        "system": {"name": platform.system(), "release": platform.release(), "machine": platform.machine()},
        "counts": {},
        "error_counts": {},
        "audit_head": None,
        "root_cause": "Not established. The error description records the observed failure, not proof of its root cause.",
    }
    if store:
        try:
            info["audit_head"] = store.verify_audit()
            with store.connect() as con:
                statuses = {
                    "pending",
                    "preparing",
                    "uploading",
                    "uploaded",
                    "verified",
                    "failed",
                    "rejected",
                    "skipped",
                    "review",
                    "restoration_review",
                }
                info["counts"] = {
                    r[0]: r[1]
                    for r in con.execute("SELECT status,COUNT(*) FROM items GROUP BY status")
                    if r[0] in statuses
                }
                info["error_counts"] = {
                    r[0]: r[1]
                    for r in con.execute(
                        "SELECT code,COUNT(*) FROM items WHERE code IS NOT NULL GROUP BY code"
                    )
                    if r[0] in CATALOG
                }
        except Exception:
            info["database_diagnostics"] = "Unavailable; the original incident is preserved."
    public = public_incident(incident)
    report = (
        f"Takeout Restore incident {incident['id']}\nVersion: {__version__}\n"
        f"Occurred (UTC): {incident['created']}\nOperation: {incident['operation']}\n"
        f"Code: {incident['code'] or 'Manual report'}\nObserved issue: {public['title']}\n"
        f"Explanation: {public['message']}\n{info['root_cause']}\n\n"
        "This report excludes source paths, media filenames, Google account information, passwords, "
        "recovery keys, browser profiles, cookies, screenshots, environment variables and raw databases.\n"
        "Review the contents before sharing. Your email app supplies your sender identity when you send.\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("incident.json", json.dumps(info, indent=2, ensure_ascii=False))
        bundle.writestr("report.txt", report)
        bundle.writestr("events.json", json.dumps(redacted_events(profile), indent=2))
    path.chmod(0o600)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    subject = f"Takeout Restore {__version__} | {incident['code'] or 'Report'} | {incident['id'][:12]}"
    body = (
        f"Takeout Restore incident report\n\nVersion: {__version__}\nIncident: {incident['id']}\n"
        f"Occurred (UTC): {incident['created']}\nOperation: {incident['operation']}\n"
        f"Error: {incident['code'] or 'Manual report'} - {public['title']}\n"
        f"Observed issue: {public['message']}\nRoot cause: not established.\n"
        f"System: {info['system']['name']} {info['system']['release']} ({info['system']['machine']})\n"
        f"Source build SHA-256: {identity['build_id'] or 'unavailable in this development build'}\n"
        f"Launcher SHA-256: {identity['executable_sha256'] or 'unavailable in source mode'}\n"
        f"Report ZIP SHA-256: {digest}\n\n"
        "What I was doing: [please describe]\nWhat I expected: [please describe]\n"
        "Can I reproduce it? [yes/no; steps]\n\n"
        f"Attachment: {path.name}\nIf it is missing, attach the saved report ZIP before sending.\n"
        "I reviewed this report and chose to send it.\n"
    )
    return {"incident_id": incident["id"], "subject": subject, "body": body, "sha256": digest}
