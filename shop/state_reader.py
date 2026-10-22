"""Read-only access to the shop state for the verifier.

Opens ``shop.db`` with SQLite's ``mode=ro`` so no write is possible. There is no
HTTP route to this module; the agent can never reach it.
"""

import sqlite3
from pathlib import Path

from shop import db


def _connect_ro(path: Path | None = None) -> sqlite3.Connection:
    """Open the database read-only."""
    uri = f"file:{(path or db.db_path()).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def cart_items(user_id: int = db.TEST_USER_ID, path: Path | None = None) -> list[dict]:
    """Cart lines of the user as ``[{"product_id", "quantity"}]`` in insertion order."""
    conn = _connect_ro(path)
    try:
        rows = conn.execute(
            "SELECT ci.product_id, ci.quantity FROM cart_items ci JOIN carts c ON c.id = ci.cart_id"
            " WHERE c.user_id = ? ORDER BY ci.rowid",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def orders(user_id: int = db.TEST_USER_ID, path: Path | None = None) -> list[dict]:
    """All orders of the user with their lines (prices in EUR)."""
    conn = _connect_ro(path)
    try:
        result = []
        for o in conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id", (user_id,)).fetchall():
            lines = conn.execute(
                "SELECT product_id, quantity, unit_price_cents FROM order_lines WHERE order_id = ? ORDER BY rowid",
                (o["id"],),
            ).fetchall()
            result.append({
                "order_id": o["id"],
                "status": o["status"],
                "created": o["created"],
                "total": round(o["total_cents"] / 100, 2),
                "lines": [
                    {"product_id": l["product_id"], "quantity": l["quantity"],
                     "unit_price": round(l["unit_price_cents"] / 100, 2)}
                    for l in lines
                ],
            })
    finally:
        conn.close()
    return result
