"""M1: catalogue design constraints and snapshot build."""

import copy
import sqlite3
from collections import defaultdict

import pytest

from shop import build_db


@pytest.fixture(scope="module")
def catalogue():
    return build_db.load_catalogue()


def test_catalogue_is_valid(catalogue):
    build_db.validate_catalogue(catalogue)
    assert 6 <= len(catalogue["categories"]) <= 8
    assert 60 <= len(catalogue["products"]) <= 100


def test_validation_rejects_price_duplicate(catalogue):
    bad = copy.deepcopy(catalogue)
    bad["products"][1]["price"] = bad["products"][0]["price"]
    with pytest.raises(ValueError, match="duplicate price"):
        build_db.validate_catalogue(bad)


def test_validation_rejects_rating_tie_in_category(catalogue):
    bad = copy.deepcopy(catalogue)
    bad["products"][1]["rating"] = bad["products"][0]["rating"]  # both are mice
    with pytest.raises(ValueError, match="rating tie"):
        build_db.validate_catalogue(bad)


def test_every_category_has_distractors(catalogue):
    """Each category has an unavailable product, a cheap low-rated product and a similar-name pair."""
    by_cat = defaultdict(list)
    for p in catalogue["products"]:
        by_cat[p["category"]].append(p)
    for cat, products in by_cat.items():
        assert any(not p["available"] for p in products), f"{cat}: no unavailable product"
        median_price = sorted(p["price"] for p in products)[len(products) // 2]
        assert any(p["price"] < median_price and p["rating"] < 3.5 for p in products), f"{cat}: no cheap low-rated product"
        prefixes = [" ".join(p["name"].split()[:2]) for p in products]
        assert len(set(prefixes)) < len(prefixes), f"{cat}: no similar names (shared first two words)"


def test_build_creates_snapshot(tmp_path, catalogue):
    path = build_db.build(snapshot=tmp_path / "snapshot.db")
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == len(catalogue["products"])
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM cart_items").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
    price = conn.execute("SELECT price_cents FROM products WHERE id = 101").fetchone()[0]
    assert price == 1999
    conn.close()
