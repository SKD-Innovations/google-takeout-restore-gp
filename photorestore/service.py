"""Single authenticated bridge; user identity never comes from frontend parameters."""

import hmac
import hashlib
import json
import secrets
import re
import zipfile
import tempfile
import shutil
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path
from .auth import Accounts
from .browser import GoogleBrowser
from .chrome import installed_chrome, cleanup_unlocked_profiles
from .diagnostics import diagnostics_bundle, export_report, export_logs_csv, log_event, logger_for
from .engine import UploadEngine
from .errors import AppError, CATALOG
from .runtime import Runtime, exiftool_path
from .scanner import Cancelled, Scanner
from .settings import Settings
from .store import Store, canonical, now
from . import macos
from .maintenance import clear_owned_data, close_logs
from .support import REPORTABLE_CODES, SUPPORT_EMAIL, new_incident, public_incident, write_incident_bundle
from .maildraft import open_report_draft


class Service:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        cleanup_unlocked_profiles(self.root)
        self.accounts_store = Store(self.root / "accounts.sqlite")
        self.accounts_store.initialize()
        self.accounts_store.verify_audit()
        self.accounts = Accounts(self.accounts_store)
        self.runtime = Runtime(self.root)
        self.session = self.store = self.profile = self.logger = None
        self.token = None
        self.selected_source = None
        self.settings = Settings()
        self.mutex = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.signin_ready = threading.Event()
        self.job = {"active": False, "phase": "Ready", "count": 0, "error": None}
        self.last_activity = time.monotonic()
        self.window = None
        self.uninstalled = False
        self.maintenance_failed = False
        self.incident_cache = {}
        self.pending_incident = None
        self.incident_dedupe = {}

    def call(self, action, params=None, token=None):
        if not isinstance(action, str) or len(action) > 64:
            return {"ok": False, "error": AppError("GPP-101").public()}
        params = params or {}
        if not isinstance(params, dict) or len(canonical(params)) > 100000:
            return {"ok": False, "error": AppError("GPP-101").public()}
        try:
            with self.mutex:
                result = self.dispatch(action, params, token)
            return {"ok": True, "data": result}
        except AppError as exc:
            return self.failure(exc.code, action, exc)
        except sqlite3.Error as exc:
            if self.logger:
                log_event(self.logger, "database.error", "GPP-501", exc)
            return self.failure("GPP-501", action, exc)
        except Exception as exc:
            if self.logger:
                log_event(self.logger, "application.error", "GPP-901", exc)
            return self.failure("GPP-901", action, exc)

    def failure(self, code, action, exc):
        error = AppError(code).public()
        if action != "send_report" and code in REPORTABLE_CODES:
            incident = self.capture_incident(code, action, exc)
            error["incident"] = public_incident(incident)
        return {"ok": False, "error": error}

    def capture_incident(self, code, operation, exc=None, run_id=None):
        with self.mutex:
            key = (code, operation, run_id)
            recent = self.incident_dedupe.get(key)
            if recent and time.monotonic() - recent[0] < 300 and recent[1] in self.incident_cache:
                return self.incident_cache[recent[1]]
            incident = new_incident(code, operation, exc, run_id)
            self.incident_dedupe[key] = (time.monotonic(), incident["id"])
            if len(self.incident_dedupe) > 50:
                self.incident_dedupe.pop(next(iter(self.incident_dedupe)))
            self.incident_cache[incident["id"]] = incident
            self.pending_incident = incident
            if len(self.incident_cache) > 50:
                self.incident_cache.pop(next(iter(self.incident_cache)))
            if self.store:
                try:
                    with self.store.connect() as con:
                        con.execute(
                            "INSERT INTO incidents(id,created,code,operation,run_id,detail) VALUES(?,?,?,?,?,?)",
                            (
                                incident["id"],
                                incident["created"],
                                code,
                                incident["operation"],
                                incident["run_id"],
                                canonical(incident["detail"]),
                            ),
                        )
                        con.execute(
                            "DELETE FROM incidents WHERE id NOT IN (SELECT id FROM incidents ORDER BY created DESC LIMIT 50)"
                        )
                        self.store.audit(
                            con,
                            self.session.user_id,
                            "incident.created",
                            {"incident": incident["id"], "code": code},
                        )
                except (sqlite3.Error, OSError):
                    pass  # Keep an in-memory incident even if the database is the failure.
        return incident

    def find_incident(self, incident_id=None):
        if incident_id is not None and (
            not isinstance(incident_id, str) or not re.fullmatch(r"[a-f0-9]{32}", incident_id)
        ):
            raise AppError("GPP-101")
        if incident_id in self.incident_cache:
            return self.incident_cache[incident_id]
        if self.store:
            try:
                with self.store.connect() as con:
                    row = con.execute(
                        "SELECT * FROM incidents WHERE id=?"
                        if incident_id
                        else "SELECT * FROM incidents ORDER BY created DESC LIMIT 1",
                        (incident_id,) if incident_id else (),
                    ).fetchone()
                if row:
                    return {k: row[k] for k in ("id", "created", "code", "operation", "run_id")} | {
                        "detail": json.loads(row["detail"])
                    }
            except (sqlite3.Error, ValueError):
                pass
        if incident_id:
            raise AppError("GPP-101")
        return self.pending_incident or new_incident()

    def send_report(self, p):
        self.require_idle()
        if p.get("consent") is not True:
            raise AppError("GPP-101")
        incident = self.find_incident(p.get("incident_id"))
        self.incident_cache[incident["id"]] = incident
        path = self.dialog("save", f"takeout-incident-{incident['id'][:12]}.zip")
        if not path:
            return {"cancelled": True}
        destination = Path(path)
        if (
            destination.suffix.lower() != ".zip"
            or destination.resolve().is_relative_to(self.root.resolve())
            or destination.is_symlink()
        ):
            raise AppError("GPP-101")
        if self.selected_source and destination.resolve().is_relative_to(
            Path(self.selected_source).resolve()
        ):
            raise AppError("GPP-113")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent, prefix=".takeout-report-", suffix=".zip", delete=False
            ) as output:
                temporary = Path(output.name)
            draft = write_incident_bundle(temporary, incident, self.store, self.profile)
            temporary.replace(destination)
            draft["body"] = draft["body"].replace(temporary.name, destination.name)
        except (OSError, zipfile.BadZipFile) as exc:
            raise AppError("GPP-113") from exc
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
        handoff = open_report_draft(draft["subject"], draft["body"], destination)
        if self.store:
            try:
                with self.store.connect() as con:
                    self.store.audit(
                        con,
                        self.session.user_id,
                        "support.draft_requested",
                        {
                            "incident": incident["id"],
                            "code": incident["code"],
                            "report_sha256": draft["sha256"],
                            "method": handoff["method"],
                        },
                    )
            except sqlite3.Error:
                pass
        return {
            **handoff,
            "path": str(destination),
            "recipient": SUPPORT_EMAIL,
            "incident_id": incident["id"],
        }

    def require_idle(self):
        if self.thread and self.thread.is_alive():
            raise AppError("GPP-106")

    def authenticate(self, token, action):
        if not self.session or not isinstance(token, str) or not hmac.compare_digest(self.token, token):
            raise AppError("GPP-102")
        if time.monotonic() - self.last_activity > self.settings.auto_lock_minutes * 60:
            self.stop.set()
            if not self.job["active"]:
                self.logout()
            raise AppError("GPP-102")
        with self.accounts_store.connect() as con:
            row = con.execute(
                "SELECT disabled,role FROM users WHERE id=?", (self.session.user_id,)
            ).fetchone()
            if not row or row["disabled"]:
                raise AppError("GPP-102")
            self.session.role = row["role"]
        if action != "status":
            self.last_activity = time.monotonic()

    def dispatch(self, action, p, token):
        if self.uninstalled or (
            self.maintenance_failed and action not in ("send_report", "acknowledge_incident", "bootstrap")
        ):
            raise AppError("GPP-111")
        if self.maintenance_failed and action == "bootstrap":
            return {
                "startup_error": AppError("GPP-111").public(),
                "incident": public_incident(self.pending_incident),
            }
        if action == "usage_guide":
            guide = Path(__file__).parent / "resources/USAGE.md"
            if not guide.is_file():
                guide = Path(__file__).parent.parent / "USAGE.md"
            return guide.read_text(encoding="utf-8")
        if action == "bootstrap":
            return {
                "has_accounts": self.accounts.exists(),
                "can_start_over": macos.device_verification_available(),
                "incident": public_incident(self.pending_incident)
                if not self.session and self.pending_incident
                else None,
            }
        if action == "recover_password":
            self.require_idle()
            if self.session:
                raise AppError("GPP-106")
            self.accounts.recover_password(p.get("username"), p.get("recovery_key"), p.get("password"))
            return None
        # Before sign-in only a fresh incident from this process can be reported.
        if action in ("send_report", "acknowledge_incident") and not self.session:
            incident_id = p.get("incident_id")
            if not isinstance(incident_id, str) or incident_id not in self.incident_cache:
                raise AppError("GPP-102")
            if action == "send_report":
                return self.send_report(p)
            self.pending_incident = None
            return None
        if action in ("clear_data", "uninstall"):
            return self.maintenance(action, p, token)
        if action in ("register", "login"):
            self.require_idle()
            if self.session and time.monotonic() - self.last_activity > self.settings.auto_lock_minutes * 60:
                self.logout()
            if self.session:
                raise AppError("GPP-106")
            if action == "register":
                self.accounts.create(p.get("username"), p.get("password"))
            session = self.accounts.login(p.get("username"), p.get("password"))
            profile = self.root / "profiles" / session.user_id
            store = Store(profile / "library.sqlite")
            store.initialize(profile=True)
            store.verify_audit()
            store.recover(session.user_id)
            if (profile / "scratch").exists():
                shutil.rmtree(profile / "scratch")
            self.profile, self.store, self.session = profile, store, session
            self.logger = logger_for(profile / "logs")
            self.token = secrets.token_urlsafe(32)
            self.last_activity = time.monotonic()
            with store.connect() as con:
                saved = con.execute("SELECT value FROM config WHERE key='settings'").fetchone()
                source = con.execute("SELECT value FROM config WHERE key='source'").fetchone()
            self.settings = Settings.parse(json.loads(saved[0])) if saved else Settings()
            self.selected_source = source[0] if source else None
            self.job = {"active": False, "phase": "Ready", "count": 0, "error": None}
            self.incident_cache = {}
            self.incident_dedupe = {}
            with store.connect() as con:
                pending = con.execute(
                    "SELECT id FROM incidents WHERE acknowledged=0 ORDER BY created DESC LIMIT 1"
                ).fetchone()
            self.pending_incident = self.find_incident(pending[0]) if pending else None
            return {
                "token": self.token,
                "user": self.user_info(),
                "recovery_key": self.accounts.issue_recovery(session),
            }
        try:
            self.authenticate(token, action)
        except sqlite3.Error:
            # A signed-in user can still report database damage with the existing token.
            if (
                action not in ("send_report", "acknowledge_incident")
                or not self.session
                or not isinstance(token, str)
                or not hmac.compare_digest(self.token, token)
                or time.monotonic() - self.last_activity > self.settings.auto_lock_minutes * 60
            ):
                raise
        if action == "send_report":
            return self.send_report(p)
        if action == "acknowledge_incident":
            incident = self.find_incident(p.get("incident_id"))
            try:
                with self.store.connect() as con:
                    con.execute("UPDATE incidents SET acknowledged=1 WHERE id=?", (incident["id"],))
            except sqlite3.Error:
                pass
            if self.pending_incident and self.pending_incident["id"] == incident["id"]:
                self.pending_incident = None
            return None
        if action == "activity":
            return None
        if action == "status":
            with self.store.connect() as con:
                counts = dict(con.execute("SELECT status,COUNT(*) FROM items GROUP BY status").fetchall())
                sizes = con.execute("SELECT COALESCE(SUM(size),0) FROM items").fetchone()[0]
                bound = bool(con.execute("SELECT 1 FROM config WHERE key='google_identity'").fetchone())
            return {
                "user": self.user_info(),
                "job": dict(self.job),
                "counts": counts,
                "bytes": sizes,
                "settings": asdict(self.settings),
                "source": self.selected_source,
                "browser_ready": bool(installed_chrome()) or self.runtime.ready(),
                "browser_name": "Google Chrome" if installed_chrome() else "Downloaded browser",
                "google_connected": (self.profile / "google.session").exists()
                and (self.profile / "chrome.profile.enc").exists(),
                "google_bound": bound,
                "incident": public_incident(self.pending_incident) if self.pending_incident else None,
            }
        if action == "logout":
            self.require_idle()
            self.logout()
            return None
        if action == "confirm_google":
            if not self.job.get("awaiting_google_confirmation"):
                raise AppError("GPP-106")
            self.job["awaiting_google_confirmation"] = False
            self.signin_ready.set()
            return None
        if action == "pause":
            self.stop.set()
            self.job["phase"] = "Pausing after the current item"
            return None
        if action == "pick_source":
            self.require_idle()
            result = self.dialog("folder")
            if result:
                source = str(Path(result).resolve(strict=True))
                if self.root.resolve().is_relative_to(Path(source)) or Path(source).is_relative_to(
                    self.root.resolve()
                ):
                    raise AppError("GPP-101")
                self.selected_source = source
                with self.store.connect() as con:
                    con.execute("INSERT OR REPLACE INTO config VALUES('source',?)", (source,))
                    self.store.audit(con, self.session.user_id, "source.selected")
            return self.selected_source
        if action == "save_settings":
            self.require_idle()
            new = Settings.parse(p.get("settings"))
            with self.store.connect() as con:
                con.execute("INSERT OR REPLACE INTO config VALUES('settings',?)", (canonical(asdict(new)),))
                self.store.audit(con, self.session.user_id, "settings.changed", asdict(new))
            self.settings = new
            return asdict(new)
        if action == "reset_settings":
            self.require_idle()
            with self.store.connect() as con:
                con.execute("DELETE FROM config WHERE key='settings'")
                self.store.audit(con, self.session.user_id, "settings.reset")
            self.settings = Settings()
            return asdict(self.settings)
        if action in ("install_browser", "scan", "connect_google", "test_google", "upload", "upload_sample"):
            self.require_idle()
            if action == "scan" and not self.selected_source:
                raise AppError("GPP-201")
            if action in ("upload", "upload_sample"):
                with self.store.connect() as con:
                    ready = con.execute(
                        "SELECT 1 FROM items WHERE status='pending' AND attempts<? LIMIT 1",
                        (self.settings.retry_limit,),
                    ).fetchone()
                if not ready:
                    raise AppError("GPP-415")
                if (
                    not (self.profile / "google.session").exists()
                    or not (self.profile / "chrome.profile.enc").exists()
                ):
                    raise AppError("GPP-401")
                exiftool_path()
            self.start(action)
            return None
        if action == "disconnect_google":
            self.require_idle()
            (self.profile / "google.session").unlink(missing_ok=True)
            (self.profile / "chrome.profile.enc").unlink(missing_ok=True)
            with self.store.connect() as con:
                self.store.audit(con, self.session.user_id, "google.disconnected")
            # Keep identity binding: reconnecting another Google account invalidates dedupe history.
            return None
        if action == "queue":
            return self.queue(p)
        if action == "item_action":
            self.require_idle()
            return self.item_action(p)
        if action == "history":
            with self.store.connect() as con:
                return [
                    dict(row) for row in con.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 200")
                ]
        if action in ("report", "diagnostics", "logs_csv"):
            self.require_idle()
            if action == "diagnostics" and not self.settings.advanced:
                raise AppError("GPP-103")
            filename = {
                "report": "takeout-report.csv",
                "diagnostics": "takeout-diagnostics.zip",
                "logs_csv": "takeout-logs.csv",
            }[action]
            path = self.dialog("save", filename)
            if path:
                if action == "logs_csv":
                    export_logs_csv(Path(path), self.store)
                elif action == "report":
                    export_report(Path(path), self.store)
                else:
                    diagnostics_bundle(Path(path), self.store, self.profile)
                with self.store.connect() as con:
                    self.store.audit(con, self.session.user_id, action + ".exported")
            return bool(path)
        if action == "logs":
            with self.store.connect() as con:
                rows = [
                    dict(r)
                    for r in con.execute(
                        "SELECT seq,time,action,detail,digest FROM audit ORDER BY seq DESC LIMIT 200"
                    )
                ]
            return {"events": rows, "errors": CATALOG, "audit_head": self.store.verify_audit()}
        if action == "change_password":
            self.require_idle()
            self.accounts.change_password(self.session, p.get("old"), p.get("new"))
            return None
        if action == "regenerate_recovery":
            self.require_idle()
            return self.accounts.issue_recovery(self.session, p.get("password"), replace=True)
        if action == "save_recovery":
            self.require_idle()
            code = p.get("recovery_key")
            if not isinstance(code, str) or len(code) > 200:
                raise AppError("GPP-101")
            with self.accounts_store.connect() as con:
                digest = con.execute(
                    "SELECT recovery_hash FROM users WHERE id=?", (self.session.user_id,)
                ).fetchone()[0]
            if not digest or not hmac.compare_digest(digest, hashlib.sha256(code.encode()).hexdigest()):
                raise AppError("GPP-109")
            path = self.dialog("save", "takeout-recovery-key.txt")
            if path:
                destination = Path(path)
                if destination.resolve().is_relative_to(self.root.resolve()):
                    raise AppError("GPP-101")
                destination.write_text(
                    f"Takeout Restore recovery key\nUsername: {self.session.username}\n\n{code}\n\n"
                    "Keep this private. It can reset your local password and unlock your saved Google session.\n",
                    encoding="utf-8",
                )
                destination.chmod(0o600)
                with self.accounts_store.connect() as con:
                    self.accounts_store.audit(con, self.session.user_id, "account.recovery_exported")
            return bool(path)
        if action in ("users", "create_user", "manage_user"):
            if action != "users":
                self.require_idle()
            with self.accounts_store.connect() as con:
                self.accounts.require_admin(con, self.session)
            if action == "create_user":
                return self.accounts.create(
                    p.get("username"), p.get("password"), self.session, p.get("role", "standard")
                )
            if action == "manage_user":
                self.accounts.manage(self.session, p.get("id"), p.get("action"), p.get("password"))
                if p.get("action") == "reset":
                    (self.root / "profiles" / p["id"] / "google.session").unlink(missing_ok=True)
                    (self.root / "profiles" / p["id"] / "chrome.profile.enc").unlink(missing_ok=True)
                return None
            with self.accounts_store.connect() as con:
                return [
                    dict(row)
                    for row in con.execute(
                        "SELECT id,username,role,disabled,created FROM users ORDER BY username"
                    )
                ]
        raise AppError("GPP-101")

    def maintenance(self, action, p, token):
        self.require_idle()
        if p.get("confirmation") != "REMOVE ALL LOCAL DATA":
            raise AppError("GPP-101")
        if self.session:
            self.authenticate(token, action)
            with self.accounts_store.connect() as con:
                self.accounts.require_admin(con, self.session)
        elif not macos.device_verification_available():
            raise AppError("GPP-102")
        if action == "uninstall" and not macos.installed_bundle():
            raise AppError("GPP-112")
        if macos.device_verification_available():
            if not macos.verify_device_owner():
                raise AppError("GPP-110")
        elif self.session:
            self.accounts.login(self.session.username, p.get("password"))
        else:
            raise AppError("GPP-110")
        # No web-only confirmation can authorize this operation.
        if not self.window or not self.window.create_confirmation_dialog(
            "Uninstall Takeout Restore?" if action == "uninstall" else "Clear all local data?",
            "Permanently remove ALL local app users, passwords, settings, queues, history, logs, "
            "browser downloads and saved Google sessions on this device? "
            "Your Takeout source files, exported reports and Google Photos library will remain."
            + (
                " The installed application will also move to Bin and close."
                if action == "uninstall"
                else " This cannot be undone."
            ),
        ):
            return False
        cleanup_unlocked_profiles(self.root)
        root, window = self.root, self.window
        # Move the installed bundle first: a permission error must not erase accounts.
        if action == "uninstall":
            macos.trash_installed_app()
        self.logout()
        try:
            clear_owned_data(root)
        except AppError:
            self.maintenance_failed = True
            raise
        if action == "uninstall":
            self.uninstalled = True
            threading.Timer(1, window.destroy).start()
        else:
            self.__init__(root)
            self.window = window
        return True

    def user_info(self):
        return {"username": self.session.username, "role": self.session.role, "id": self.session.user_id}

    def logout(self):
        if self.session:
            with self.accounts_store.connect() as con:
                self.accounts_store.audit(con, self.session.user_id, "auth.logout")
        if self.profile:
            close_logs(self.profile)
        self.session = self.token = self.store = self.profile = self.selected_source = self.logger = None
        self.incident_cache = {}
        self.pending_incident = None
        self.incident_dedupe = {}

    def queue(self, p):
        status = p.get("status", "")
        if status not in (
            "",
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
        ):
            raise AppError("GPP-101")
        search = p.get("search", "")
        offset = p.get("offset", 0)
        if (
            not isinstance(search, str)
            or len(search) > 500
            or type(offset) is not int
            or not 0 <= offset <= 10**9
        ):
            raise AppError("GPP-101")
        where, args = "WHERE 1=1", []
        if status:
            where += " AND status=?"
            args.append(status)
        if search:
            where += " AND instr(lower(name),lower(?))>0"
            args.append(search)
        with self.store.connect() as con:
            count = con.execute("SELECT COUNT(*) FROM items " + where, args).fetchone()[0]  # noqa: S608 -- clauses are constants; all values bound
            fields = "id,name,size,status,code,attempts,updated,warnings"
            if self.settings.advanced:
                fields += ",sha256,metadata,receipt,relative"
            rows = con.execute(
                "SELECT " + fields + " FROM items " + where + " ORDER BY id LIMIT 100 OFFSET ?",  # noqa: S608 -- fixed column allowlist
                [*args, offset],
            ).fetchall()
        return {"total": count, "items": [dict(row) for row in rows], "offset": offset}

    def item_action(self, p):
        if not self.settings.advanced:
            raise AppError("GPP-103")
        if type(p.get("id")) is not int:
            raise AppError("GPP-101")
        action = p.get("action")
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM items WHERE id=?", (p["id"],)).fetchone()
            if not row:
                raise AppError("GPP-101")
            if action == "retry" and row["status"] in ("failed", "skipped", "rejected", "review"):
                if row["status"] == "review" and p.get("confirm_duplicate_risk") is not True:
                    raise AppError("GPP-403")
                if row["code"] == "GPP-301":
                    raise AppError("GPP-301")
                if not row["sha256"]:
                    raise AppError("GPP-202")
                state, code = "pending", None
            elif action == "skip" and row["status"] in ("pending", "failed", "rejected"):
                state, code = "skipped", None
            elif (
                action == "verify"
                and row["status"] in ("review", "restoration_review", "uploaded")
                and p.get("confirmed") is True
            ):
                state, code = "verified", None
            else:
                raise AppError("GPP-101")
            con.execute(
                "UPDATE items SET status=?,code=?,attempts=0,updated=? WHERE id=?",
                (state, code, now(), row["id"]),
            )
            self.store.audit(con, self.session.user_id, "item.manual_" + action, {"item": row["id"]})

    def start(self, action):
        self.stop.clear()
        self.signin_ready.clear()
        self.job = {"active": True, "phase": "Starting", "count": 0, "error": None}
        actor, store, profile, key = self.session.user_id, self.store, self.profile, self.session.key
        settings, source, logger = self.settings, self.selected_source, self.logger
        run_id = secrets.token_hex(16)
        with store.connect() as con:
            con.execute(
                "INSERT INTO runs(id,kind,started,status) VALUES(?,?,?,?)", (run_id, action, now(), "running")
            )
            store.audit(con, actor, "operation.started", {"kind": action, "run": run_id})

        def progress(phase, count):
            self.job.update(
                phase=phase,
                count=count,
                awaiting_google_confirmation=(phase == "Sign in in Chrome, then click Continue in the app"),
            )

        def work():
            code, status, count = None, "finished", 0
            remaining, failure = None, None
            try:
                if action == "install_browser":
                    self.runtime.install(self.stop, progress)
                elif action == "scan":
                    count = Scanner(store, actor, settings, self.stop, progress).scan(source)
                else:
                    with GoogleBrowser(
                        self.runtime,
                        profile,
                        key,
                        store,
                        self.stop,
                        signin_ready=self.signin_ready if action == "connect_google" else None,
                        progress=progress,
                    ) as browser:
                        if action == "connect_google":
                            browser.login(progress)
                        elif action == "test_google":
                            browser.self_test()
                        else:
                            count = UploadEngine(
                                store, actor, settings, profile, exiftool_path(), self.stop, progress
                            ).run(browser, max_items=5 if action == "upload_sample" else None)
                if self.stop.is_set():
                    status = "paused"
                elif action in ("upload", "upload_sample"):
                    with store.connect() as con:
                        remaining = dict(
                            con.execute("SELECT status,COUNT(*) FROM items GROUP BY status").fetchall()
                        )
                    if any(
                        remaining.get(s, 0) for s in ("review", "restoration_review", "failed", "rejected")
                    ):
                        status = "needs_review"
                    elif remaining.get("pending", 0):
                        status = "partial"
            except Cancelled:
                status = "paused"
                count = self.job["count"]
            except Exception as exc:
                code = (
                    exc.code
                    if isinstance(exc, AppError)
                    else "GPP-501"
                    if isinstance(exc, sqlite3.Error)
                    else "GPP-901"
                )
                status = "stopped"
                count = self.job["count"]
                self.job["error"] = AppError(code).public()
                failure = log_event(logger, "operation.error", code, exc)
                if code in REPORTABLE_CODES:
                    self.capture_incident(code, action, exc, run_id)
            finally:
                try:
                    with store.connect() as con:
                        con.execute(
                            "UPDATE runs SET ended=?,status=?,count=?,code=? WHERE id=?",
                            (now(), status, count, code, run_id),
                        )
                        store.audit(
                            con,
                            actor,
                            "operation." + status,
                            {
                                "run": run_id,
                                "code": code,
                                "count": count,
                                **({"remaining": remaining} if remaining is not None else {}),
                                **({"error": failure} if failure else {}),
                            },
                        )
                except Exception as exc:
                    log_event(logger, "operation.commit_error", "GPP-501", exc)
                    self.job["error"] = AppError("GPP-501").public()
                    self.capture_incident("GPP-501", action, exc, run_id)
                self.job.update(
                    active=False,
                    outcome=status,
                    processed_count=count,
                    remaining=remaining,
                    phase={
                        "paused": "Paused",
                        "needs_review": "Review required — check the queue",
                        "partial": "More items ready — check the queue",
                    }.get(status, "Stopped" if code else "Ready"),
                )

        self.thread = threading.Thread(target=work, name="takeout-worker", daemon=False)
        self.thread.start()

    def dialog(self, kind, filename=""):
        if not self.window:
            raise AppError("GPP-101")
        import webview

        result = self.window.create_file_dialog(
            webview.FileDialog.FOLDER if kind == "folder" else webview.FileDialog.SAVE, save_filename=filename
        )
        return result[0] if isinstance(result, (list, tuple)) and result else result


class StartupSupport:
    """Minimal report bridge when the account store cannot be opened. No user-data access."""

    require_idle = Service.require_idle
    find_incident = Service.find_incident
    send_report = Service.send_report
    dialog = Service.dialog

    def __init__(self, root, code, exc):
        self.root = root
        self.store = self.profile = self.session = self.thread = self.window = self.selected_source = None
        incident = new_incident(code, "startup", exc)
        self.incident_cache = {incident["id"]: incident}
        self.incident = incident
        self.pending_incident = incident

    def call(self, action, params=None, token=None):
        p = params or {}
        if not isinstance(p, dict):
            return {"ok": False, "error": AppError("GPP-101").public()}
        try:
            if action == "bootstrap":
                result = {
                    "startup_error": AppError(self.incident["code"]).public(),
                    "incident": public_incident(self.incident),
                }
            elif (
                action in ("send_report", "acknowledge_incident")
                and p.get("incident_id") == self.incident["id"]
            ):
                result = self.send_report(p) if action == "send_report" else None
            else:
                raise AppError("GPP-102")
            return {"ok": True, "data": result}
        except AppError as exc:
            return {"ok": False, "error": exc.public()}
        except Exception:
            return {"ok": False, "error": AppError("GPP-901").public()}
