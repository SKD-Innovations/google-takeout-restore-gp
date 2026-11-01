import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from dataclasses import dataclass
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from .errors import AppError
from .store import Store, now

HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
DUMMY = HASHER.hash(secrets.token_urlsafe(32))


def wrapping_key(password, salt):
    return base64.urlsafe_b64encode(Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode()))


def check_password(password):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise AppError("GPP-108")


@dataclass
class Session:
    user_id: str
    username: str
    role: str
    key: bytes


class Accounts:
    def __init__(self, store: Store):
        self.store = store
        self.unknown_attempts = []

    def exists(self):
        with self.store.connect() as con:
            return con.execute("SELECT 1 FROM users LIMIT 1").fetchone() is not None

    def create(self, username, password, actor=None, role="standard"):
        check_password(password)
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{2,47}", username):
            raise AppError("GPP-101")
        if role not in ("admin", "standard"):
            raise AppError("GPP-101")
        uid, salt, key = secrets.token_hex(16), os.urandom(16), Fernet.generate_key()
        with self.store.connect() as con:
            if con.execute("SELECT 1 FROM users").fetchone():
                self.require_admin(con, actor)
            else:
                role = "admin"
            if con.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
                raise AppError("GPP-107")
            con.execute(
                "INSERT INTO users(id,username,password,salt,wrapped_key,role,created) VALUES(?,?,?,?,?,?,?)",
                (
                    uid,
                    username,
                    HASHER.hash(password),
                    salt,
                    Fernet(wrapping_key(password, salt)).encrypt(key),
                    role,
                    now(),
                ),
            )
            self.store.audit(
                con, actor.user_id if actor else uid, "account.created", {"target": uid, "role": role}
            )
        return uid

    @staticmethod
    def require_admin(con, actor):
        row = con.execute(
            "SELECT role,disabled FROM users WHERE id=?", (actor.user_id if actor else "",)
        ).fetchone()
        if not row or row["disabled"] or row["role"] != "admin":
            raise AppError("GPP-103")

    def login(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 256:
            raise AppError("GPP-104")
        tick = time.time()
        self.unknown_attempts = [x for x in self.unknown_attempts if tick - x < 60]
        if len(self.unknown_attempts) >= 10:
            raise AppError("GPP-105")
        error, result = None, None
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if row and row["locked_until"] > tick:
                raise AppError("GPP-105")
            try:
                valid = HASHER.verify(row["password"] if row else DUMMY, password)
            except VerificationError:
                valid = False
            if not valid or not row or row["disabled"]:
                self.unknown_attempts.append(tick)
                if row:
                    failures = row["failures"] + 1
                    con.execute(
                        "UPDATE users SET failures=?,locked_until=? WHERE id=?",
                        (
                            failures,
                            tick + min(900, 2 ** min(failures, 10)) if failures >= 5 else 0,
                            row["id"],
                        ),
                    )
                self.store.audit(con, row["id"] if row else "unknown", "auth.failed")
                error = "GPP-104"
            else:
                try:
                    key = Fernet(wrapping_key(password, row["salt"])).decrypt(row["wrapped_key"])
                except InvalidToken as exc:
                    raise AppError("GPP-408") from exc
                con.execute("UPDATE users SET failures=0,locked_until=0 WHERE id=?", (row["id"],))
                self.store.audit(con, row["id"], "auth.login")
                result = Session(row["id"], row["username"], row["role"], key)
        if error:
            raise AppError(error)
        return result

    def change_password(self, actor, old, new):
        check_password(new)
        self.login(actor.username, old)
        salt = os.urandom(16)
        with self.store.connect() as con:
            con.execute(
                "UPDATE users SET password=?,salt=?,wrapped_key=? WHERE id=?",
                (HASHER.hash(new), salt, Fernet(wrapping_key(new, salt)).encrypt(actor.key), actor.user_id),
            )
            self.store.audit(con, actor.user_id, "account.password_changed")

    def issue_recovery(self, actor, password=None, replace=False):
        if replace:
            self.login(actor.username, password)
        with self.store.connect() as con:
            row = con.execute("SELECT recovery_hash FROM users WHERE id=?", (actor.user_id,)).fetchone()
            if row[0] and not replace:
                return None
            raw = secrets.token_hex(32).upper()
            code = "TRR-" + "-".join(raw[i : i + 8] for i in range(0, len(raw), 8))
            digest = hashlib.sha256(code.encode()).hexdigest()
            # The code has 256 bits of entropy; its encryption key is domain separated.
            key = base64.urlsafe_b64encode(hashlib.sha256(b"takeout-recovery-v1:" + code.encode()).digest())
            con.execute(
                "UPDATE users SET recovery_hash=?,recovery_wrapped_key=?,recovery_failures=0,"
                "recovery_locked_until=0 WHERE id=?",
                (digest, Fernet(key).encrypt(actor.key), actor.user_id),
            )
            self.store.audit(con, actor.user_id, "account.recovery_issued")
        return code

    def recover_password(self, username, code, password):
        check_password(password)
        if not isinstance(username, str) or not isinstance(code, str) or len(code) > 200:
            raise AppError("GPP-109")
        code = code.strip().upper()
        tick = time.time()
        self.unknown_attempts = [x for x in self.unknown_attempts if tick - x < 60]
        if len(self.unknown_attempts) >= 10:
            raise AppError("GPP-105")
        failed = False
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
            if row and row["recovery_locked_until"] > tick:
                raise AppError("GPP-105")
            digest = hashlib.sha256(code.encode()).hexdigest()
            valid = hmac.compare_digest(digest, (row["recovery_hash"] if row else None) or "0" * 64)
            if not row or not valid or row["disabled"]:
                failed = True
                self.unknown_attempts.append(tick)
                if row:
                    count = row["recovery_failures"] + 1
                    con.execute(
                        "UPDATE users SET recovery_failures=?,recovery_locked_until=? WHERE id=?",
                        (count, tick + min(900, 2 ** min(count, 10)) if count >= 5 else 0, row["id"]),
                    )
                self.store.audit(con, row["id"] if row else "unknown", "account.recovery_failed")
            else:
                key = base64.urlsafe_b64encode(
                    hashlib.sha256(b"takeout-recovery-v1:" + code.encode()).digest()
                )
                try:
                    profile_key = Fernet(key).decrypt(row["recovery_wrapped_key"])
                except InvalidToken as exc:
                    raise AppError("GPP-109") from exc
                salt = os.urandom(16)
                con.execute(
                    "UPDATE users SET password=?,salt=?,wrapped_key=?,failures=0,locked_until=0,"
                    "recovery_hash=NULL,recovery_wrapped_key=NULL,recovery_failures=0,"
                    "recovery_locked_until=0 WHERE id=?",
                    (
                        HASHER.hash(password),
                        salt,
                        Fernet(wrapping_key(password, salt)).encrypt(profile_key),
                        row["id"],
                    ),
                )
                self.store.audit(con, row["id"], "account.password_recovered")
        if failed:
            raise AppError("GPP-109")

    def manage(self, actor, target, action, password=None):
        with self.store.connect() as con:
            self.require_admin(con, actor)
            row = con.execute("SELECT * FROM users WHERE id=?", (target,)).fetchone()
            if (
                not row
                or target == actor.user_id
                or action not in ("disable", "enable", "reset", "admin", "standard")
            ):
                raise AppError("GPP-107")
            if action == "reset":
                check_password(password)
                salt, key = os.urandom(16), Fernet.generate_key()
                con.execute(
                    "UPDATE users SET password=?,salt=?,wrapped_key=?,failures=0,locked_until=0,"
                    "recovery_hash=NULL,recovery_wrapped_key=NULL,recovery_failures=0,"
                    "recovery_locked_until=0 WHERE id=?",
                    (HASHER.hash(password), salt, Fernet(wrapping_key(password, salt)).encrypt(key), target),
                )
            elif action in ("disable", "enable"):
                con.execute("UPDATE users SET disabled=? WHERE id=?", (int(action == "disable"), target))
            else:
                con.execute("UPDATE users SET role=? WHERE id=?", (action, target))
            self.store.audit(con, actor.user_id, "account." + action, {"target": target})
