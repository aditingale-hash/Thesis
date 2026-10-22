"""Build ``snapshot.db`` from ``data/catalogue.json``.

Usage: ``python -m shop.build_db``

The catalogue is validated first (unique ids/names/prices, unique ratings within a
category, value ranges) so that constraint tasks can never have ties.
"""

import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from shop import db


def load_catalogue(path: Path = db.CATALOGUE_PATH) -> dict:
    """Read the catalogue JSON file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_catalogue(catalogue: dict) -> None:
    """Raise ``ValueError`` if the catalogue breaks a design constraint.

    - ids, names and prices are unique across the whole catalogue
    - ratings are unique within each category (no rating ties when sorting a category)
    - price has at most 2 decimals, rating is 0.0-5.0 with 1 decimal
    - unavailable products have stock 0, available ones stock >= 1
    - every product belongs to a listed category
    """
    categories = catalogue["categories"]
    products = catalogue["products"]
    for field in ("id", "name", "price"):
        values = [p[field] for p in products]
        duplicates = {v for v in values if values.count(v) > 1}
        if duplicates:
            raise ValueError(f"duplicate {field}: {sorted(duplicates)}")
    ratings_by_category = defaultdict(list)
    for p in products:
        if p["category"] not in categories:
            raise ValueError(f"product {p['id']}: unknown category {p['category']!r}")
        if p["price"] <= 0 or abs(p["price"] * 100 - round(p["price"] * 100)) > 1e-6:
            raise ValueError(f"product {p['id']}: price has more than 2 decimals")
        if not (0.0 <= p["rating"] <= 5.0) or abs(round(p["rating"], 1) - p["rating"]) > 1e-9:
            raise ValueError(f"product {p['id']}: invalid rating {p['rating']}")
        if p["available"] != (p["stock"] > 0):
            raise ValueError(f"product {p['id']}: available={p['available']} but stock={p['stock']}")
        ratings_by_category[p["category"]].append(p["rating"])
    for category, ratings in ratings_by_category.items():
        if len(ratings) != len(set(ratings)):
            raise ValueError(f"rating tie in category {category!r}")


def build(catalogue_path: Path = db.CATALOGUE_PATH, snapshot: Path | None = None) -> Path:
    """Create a fresh snapshot database from the catalogue and return its path."""
    snapshot = snapshot or db.snapshot_path()
    catalogue = load_catalogue(catalogue_path)
    validate_catalogue(catalogue)
    snapshot.unlink(missing_ok=True)
    conn = sqlite3.connect(snapshot)
    try:
        conn.executescript(db.SCHEMA)
        conn.executemany(
            "INSERT INTO categories (name, position) VALUES (?, ?)",
            [(name, i) for i, name in enumerate(catalogue["categories"])],
        )
        conn.executemany(
            "INSERT INTO products (id, name, category, price_cents, rating, available, stock, description, badge)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (p["id"], p["name"], p["category"], round(p["price"] * 100), p["rating"],
                 int(p["available"]), p["stock"], p["description"], p["badge"])
                for p in catalogue["products"]
            ],
        )
        password_hash = hashlib.sha256(db.TEST_PASSWORD.encode()).hexdigest()
        conn.execute(
            "INSERT INTO users (id, username, password_sha256) VALUES (?, ?, ?)",
            (db.TEST_USER_ID, db.TEST_USERNAME, password_hash),
        )
        conn.execute("INSERT INTO carts (id, user_id) VALUES (1, ?)", (db.TEST_USER_ID,))
        conn.commit()
    finally:
        conn.close()
    return snapshot


if __name__ == "__main__":
    path = build()
    print(f"Built {path}")
