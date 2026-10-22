"""Reset the shop to a task's initial state.

``reset(task)`` copies ``snapshot.db`` over ``shop.db`` and inserts the task's
pre-filled cart (``initial_state.cart``) directly into the database. The pre-filled
cart bypasses the business rules on purpose, so a task can start with e.g. an
unavailable item in the cart. Only called between runs, never during one.

Usage: ``python -m shop.reset [path/to/task.json]``
"""

import json
import os
import shutil
import sys
from pathlib import Path

from shop import db


def reset(task: dict | str | Path | None = None) -> None:
    """Restore the snapshot and apply the pre-filled cart of ``task`` (dict or task file path)."""
    if isinstance(task, (str, Path)):
        task = json.loads(Path(task).read_text(encoding="utf-8"))
    target = db.db_path()
    snapshot = db.snapshot_path()
    if not snapshot.exists():
        raise FileNotFoundError(f"{snapshot} not found; run python -m shop.build_db first")
    tmp = target.with_suffix(".tmp")
    shutil.copyfile(snapshot, tmp)
    os.replace(tmp, target)  # atomic: a request never sees a half-copied file

    cart = (task or {}).get("initial_state", {}).get("cart", [])
    if cart:
        conn = db.connect(target)
        try:
            with conn:
                cart_id = conn.execute("SELECT id FROM carts WHERE user_id = ?", (db.TEST_USER_ID,)).fetchone()["id"]
                conn.executemany(
                    "INSERT INTO cart_items (cart_id, product_id, quantity) VALUES (?, ?, ?)",
                    [(cart_id, item["product_id"], item["quantity"]) for item in cart],
                )
        finally:
            conn.close()


if __name__ == "__main__":
    reset(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"Reset {db.db_path()}")
