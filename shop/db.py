"""SQLite access for the shop.

The shop works on ``shop.db``. ``snapshot.db`` is the pristine initial state built
from ``data/catalogue.json`` by ``build_db.py``; ``reset.py`` copies it over
``shop.db`` between runs.

Paths can be overridden with the environment variables ``SHOP_DB_PATH`` and
``SHOP_SNAPSHOT_PATH`` (used by the tests). They are read on every call so that
a running server always opens the current file.
"""

import os
import sqlite3
from pathlib import Path

SHOP_DIR = Path(__file__).resolve().parent
CATALOGUE_PATH = SHOP_DIR / "data" / "catalogue.json"

# The single test user. The runner logs in with these credentials; the agent never does.
TEST_USERNAME = "testuser"
TEST_PASSWORD = "testpass"
TEST_USER_ID = 1

SCHEMA = """
CREATE TABLE categories (
    name     TEXT PRIMARY KEY,
    position INTEGER NOT NULL
);
CREATE TABLE products (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    category    TEXT NOT NULL REFERENCES categories(name),
    price_cents INTEGER NOT NULL,
    rating      REAL NOT NULL,
    available   INTEGER NOT NULL,
    stock       INTEGER NOT NULL,
    description TEXT NOT NULL,
    badge       TEXT
);
CREATE TABLE users (
    id              INTEGER PRIMARY KEY,
    username        TEXT NOT NULL UNIQUE,
    password_sha256 TEXT NOT NULL
);
CREATE TABLE carts (
    id      INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL UNIQUE REFERENCES users(id)
);
CREATE TABLE cart_items (
    cart_id    INTEGER NOT NULL REFERENCES carts(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    quantity   INTEGER NOT NULL,
    PRIMARY KEY (cart_id, product_id)
);
CREATE TABLE orders (
    id          INTEGER PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    total_cents INTEGER NOT NULL,
    status      TEXT NOT NULL,
    created     TEXT NOT NULL
);
CREATE TABLE order_lines (
    order_id         INTEGER NOT NULL REFERENCES orders(id),
    product_id       INTEGER NOT NULL REFERENCES products(id),
    quantity         INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL,
    PRIMARY KEY (order_id, product_id)
);
"""


def db_path() -> Path:
    """Path of the working database ``shop.db``."""
    return Path(os.environ.get("SHOP_DB_PATH", SHOP_DIR / "shop.db"))


def snapshot_path() -> Path:
    """Path of the pristine initial database ``snapshot.db``."""
    return Path(os.environ.get("SHOP_SNAPSHOT_PATH", SHOP_DIR / "snapshot.db"))


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a read-write connection to ``shop.db`` (or ``path``)."""
    conn = sqlite3.connect(path or db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
