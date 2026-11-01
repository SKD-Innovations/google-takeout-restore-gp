"""SQLite state and a chained audit trail. Each thread opens its own connection."""

import hashlib
import hmac
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .errors import AppError


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    @contextmanager
    def connect(self):
        con = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA busy_timeout=30000")
        con.execute("PRAGMA synchronous=FULL")
        try:
            con.execute("BEGIN IMMEDIATE")
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def initialize(self, profile=False):
        con = sqlite3.connect(self.path)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            version = 2
            if con.execute("PRAGMA user_version").fetchone()[0] > version:
                raise AppError("GPP-503")
            common = """
              CREATE TABLE IF NOT EXISTS audit (
                seq INTEGER PRIMARY KEY, time TEXT NOT NULL, actor TEXT NOT NULL,
                action TEXT NOT NULL, detail TEXT NOT NULL, previous TEXT NOT NULL, digest TEXT NOT NULL);
            """
            schema = (
                """
              CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password TEXT NOT NULL, salt BLOB NOT NULL, wrapped_key BLOB NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','standard')), disabled INTEGER NOT NULL DEFAULT 0,
                failures INTEGER NOT NULL DEFAULT 0, locked_until REAL NOT NULL DEFAULT 0,
                created TEXT NOT NULL);
            """
                if not profile
                else """
              CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, started TEXT NOT NULL, ended TEXT,
                status TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0, code TEXT);
              CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY, source TEXT NOT NULL, relative TEXT NOT NULL, name TEXT NOT NULL,
                size INTEGER NOT NULL, mtime INTEGER NOT NULL, sha256 TEXT, fingerprint TEXT,
                status TEXT NOT NULL, code TEXT, metadata TEXT NOT NULL DEFAULT '{}',
                warnings TEXT NOT NULL DEFAULT '[]', attempts INTEGER NOT NULL DEFAULT 0,
                receipt TEXT, pair_key TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL,
                UNIQUE(source,relative));
              CREATE INDEX IF NOT EXISTS item_status ON items(status,id);
              CREATE INDEX IF NOT EXISTS item_fingerprint ON items(fingerprint);
              CREATE INDEX IF NOT EXISTS item_pairs ON items(pair_key,id);
              CREATE TABLE IF NOT EXISTS occurrences (
                item_id INTEGER NOT NULL REFERENCES items(id), album TEXT NOT NULL,
                UNIQUE(item_id,album));
              CREATE TABLE IF NOT EXISTS sidecars (
                path TEXT PRIMARY KEY, directory TEXT NOT NULL, title TEXT, data TEXT, invalid INTEGER NOT NULL);
              CREATE INDEX IF NOT EXISTS sidecar_title ON sidecars(directory,title);
              CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY, created TEXT NOT NULL, code TEXT,
                operation TEXT NOT NULL, run_id TEXT, detail TEXT NOT NULL,
                acknowledged INTEGER NOT NULL DEFAULT 0);
            """
            )
            con.executescript(common + schema)
            if not profile:
                columns = {r[1] for r in con.execute("PRAGMA table_info(users)")}
                for name, definition in (
                    ("recovery_hash", "TEXT"),
                    ("recovery_wrapped_key", "BLOB"),
                    ("recovery_failures", "INTEGER NOT NULL DEFAULT 0"),
                    ("recovery_locked_until", "REAL NOT NULL DEFAULT 0"),
                ):
                    if name not in columns:
                        con.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
            con.execute(f"PRAGMA user_version={version}")
            con.commit()
        finally:
            con.close()
        self.path.chmod(0o600)

    @staticmethod
    def audit(con, actor, action, detail=None):
        last = con.execute("SELECT digest FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last[0] if last else "0" * 64
        stamp, payload = now(), canonical(detail or {})
        digest = hashlib.sha256(canonical([stamp, actor, action, payload, previous]).encode()).hexdigest()
        con.execute(
            "INSERT INTO audit(time,actor,action,detail,previous,digest) VALUES (?,?,?,?,?,?)",
            (stamp, actor, action, payload, previous, digest),
        )

    def verify_audit(self):
        previous = "0" * 64
        with self.connect() as con:
            for row in con.execute("SELECT * FROM audit ORDER BY seq"):
                digest = hashlib.sha256(
                    canonical([row["time"], row["actor"], row["action"], row["detail"], previous]).encode()
                ).hexdigest()
                if row["previous"] != previous or not hmac.compare_digest(row["digest"], digest):
                    raise AppError("GPP-502")
                previous = digest
        return previous

    def recover(self, actor):
        with self.connect() as con:
            con.execute(
                "UPDATE items SET status='review',code='GPP-403',updated=? WHERE status='uploading'", (now(),)
            )
            con.execute("UPDATE items SET status='pending',updated=? WHERE status='preparing'", (now(),))
            con.execute("UPDATE runs SET status='interrupted',ended=? WHERE ended IS NULL", (now(),))
            self.audit(con, actor, "session.recovered")
