"""Registration: rules live in service.register; the page shows the core's message."""

import pytest
from fastapi.testclient import TestClient

from shop import db, reset, service, state_reader
from shop.app import app
from tests.conftest import notice


def _register(client, username="alice_01", password="correct-horse", repeat=None):
    return client.post("/register", data={"username": username, "password": password,
                                          "password_repeat": password if repeat is None else repeat})


def test_register_logs_in_and_user_can_shop(shop_db):
    client = TestClient(app)
    r = _register(client)
    assert r.status_code == 200 and r.url.path == "/" and notice(r.text) is None
    cart = client.post("/api/cart/items", json={"product_id": 101, "quantity": 2}).json()
    assert cart["total"] == 39.98
    # the new user's cart is separate from the test user's cart (BR1 ownership)
    assert state_reader.cart_items() == []


def test_registered_user_can_log_in_again(shop_db):
    _register(TestClient(app))
    r = TestClient(app).post("/login", data={"username": "alice_01", "password": "correct-horse"})
    assert r.url.path == "/" and notice(r.text) is None
    r = TestClient(app).post("/login", data={"username": "alice_01", "password": "wrong-password"})
    assert notice(r.text) == "Invalid username or password."


@pytest.mark.parametrize("username, password, repeat, message", [
    ("ab", "correct-horse", None, "Username must be 3 to 30 characters: letters, digits, dot, dash or underscore."),
    ("bad name", "correct-horse", None, "Username must be 3 to 30 characters: letters, digits, dot, dash or underscore."),
    (" alice_01", "correct-horse", None, "Username must be 3 to 30 characters: letters, digits, dot, dash or underscore."),
    ("alice_01", "short", None, "Password must be at least 8 characters long."),
    ("alice_01", "correct-horse", "other-horse", "The two passwords do not match."),
    (db.TEST_USERNAME, "correct-horse", None, f"The username {db.TEST_USERNAME} is already taken."),
])
def test_register_rejections(shop_db, username, password, repeat, message):
    r = _register(TestClient(app), username, password, repeat)
    assert r.status_code == 422
    assert notice(r.text) == message
    assert f'value="{username}"' in r.text  # the typed username is kept, passwords are not


def test_old_session_cannot_open_a_new_account_after_reset(shop_db):
    """BR1: ids of deleted accounts are not reused, so a cookie from before a reset opens nothing."""
    alice = TestClient(app)
    _register(alice, "alice_01")
    alice.post("/api/cart/items", json={"product_id": 101, "quantity": 1})
    reset.reset()
    bob = TestClient(app)
    _register(bob, "bob_02")
    bob.post("/api/cart/items", json={"product_id": 502, "quantity": 3})
    r = alice.get("/api/cart")
    assert r.status_code == 401 and r.json()["error"]["rule"] == "BR1"


def test_passwords_are_salted_hashes(shop_db):
    a, b = service.hash_password("same-password"), service.hash_password("same-password")
    assert a != b and a.startswith("pbkdf2_sha256$") and "same-password" not in a


def test_no_registration_api():
    assert not any(getattr(r, "path", "").startswith("/api/register") for r in app.routes)
