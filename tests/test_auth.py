import pytest
from cryptography.fernet import Fernet
from photorestore.auth import Accounts
from photorestore.errors import AppError
from photorestore.store import Store
from photorestore.service import Service

PASSWORD = "a long private passphrase"


def test_first_admin_cannot_be_created_twice(tmp_path):
    db = Store(tmp_path / "auth.sqlite")
    db.initialize()
    auth = Accounts(db)
    auth.create("Alice", PASSWORD)
    alice = auth.login("alice", PASSWORD)
    assert alice.role == "admin"
    with pytest.raises(AppError, match="GPP-103"):
        auth.create("Mallory", PASSWORD)
    bob_id = auth.create("Bobby", PASSWORD, alice)
    bob = auth.login("bobby", PASSWORD)
    with pytest.raises(AppError, match="GPP-103"):
        auth.manage(bob, alice.user_id, "disable")
    with pytest.raises(AppError, match="GPP-107"):
        auth.manage(alice, alice.user_id, "standard")
    auth.manage(alice, bob_id, "disable")
    with pytest.raises(AppError, match="GPP-104"):
        auth.login("bobby", PASSWORD)


def test_password_change_preserves_key_reset_rotates(tmp_path):
    db = Store(tmp_path / "auth.sqlite")
    db.initialize()
    auth = Accounts(db)
    auth.create("Alice", PASSWORD)
    alice = auth.login("Alice", PASSWORD)
    blob = Fernet(alice.key).encrypt(b"google cookies")
    auth.change_password(alice, PASSWORD, "a completely new password")
    new = auth.login("Alice", "a completely new password")
    assert Fernet(new.key).decrypt(blob) == b"google cookies"
    bid = auth.create("Bobby", PASSWORD, new)
    old_key = auth.login("Bobby", PASSWORD).key
    auth.manage(new, bid, "reset", "a replacement password")
    assert auth.login("Bobby", "a replacement password").key != old_key


def test_failed_login_is_committed_and_locks(tmp_path):
    db = Store(tmp_path / "auth.sqlite")
    db.initialize()
    auth = Accounts(db)
    auth.create("Alice", PASSWORD)
    for _ in range(5):
        with pytest.raises(AppError, match="GPP-104"):
            auth.login("Alice", "wrong")
    with pytest.raises(AppError, match="GPP-105"):
        auth.login("Alice", PASSWORD)
    with db.connect() as c:
        assert c.execute("SELECT failures FROM users").fetchone()[0] == 5
    assert db.verify_audit()


def test_bridge_isolation_and_no_unauthenticated_mutation(tmp_path):
    service = Service(tmp_path / "data")
    assert service.call("save_settings")["error"]["code"] == "GPP-102"
    admin = service.call("register", {"username": "Alice", "password": PASSWORD})["data"]["token"]
    assert service.call("create_user", {"username": "Bobby", "password": PASSWORD}, admin)["ok"]
    assert service.call("save_settings", {"settings": {"edited": "skip"}}, admin)["ok"]
    service.call("logout", {}, admin)
    bob = service.call("login", {"username": "Bobby", "password": PASSWORD})["data"]["token"]
    assert service.call("status", {}, bob)["data"]["settings"]["edited"] == "both"
    assert service.call("status", {}, admin)["error"]["code"] == "GPP-102"
    assert service.call("users", {}, bob)["error"]["code"] == "GPP-103"
    assert service.call("item_action", {"id": 1, "action": "skip"}, bob)["error"]["code"] == "GPP-103"
