"""M1: reset restores the exact initial state; the state reader is read-only."""

import sqlite3

import pytest

from shop import db, reset, routes_api, routes_html, app as app_module, state_reader


def _dump(path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def test_reset_restores_snapshot(client, shop_db, snapshot_file):
    client.post("/api/cart/items", json={"product_id": 101, "quantity": 2})
    client.post("/api/checkout")
    client.post("/api/cart/items", json={"product_id": 502, "quantity": 1})
    assert _dump(shop_db) != _dump(snapshot_file)
    reset.reset()
    assert _dump(shop_db) == _dump(snapshot_file)


def test_reset_applies_prefilled_cart(shop_db):
    cart = [{"product_id": 106, "quantity": 1}, {"product_id": 101, "quantity": 3}]
    reset.reset({"initial_state": {"cart": cart}})
    assert state_reader.cart_items() == cart  # unavailable item allowed in pre-filled cart
    assert state_reader.orders() == []
    reset.reset({"initial_state": {"cart": []}})
    assert state_reader.cart_items() == []


def test_reset_from_task_file(shop_db, tmp_path):
    task = tmp_path / "task.json"
    task.write_text('{"id": "X", "initial_state": {"cart": [{"product_id": 502, "quantity": 2}]}}')
    reset.reset(task)
    assert state_reader.cart_items() == [{"product_id": 502, "quantity": 2}]


def test_state_reader_is_read_only(shop_db):
    conn = state_reader._connect_ro()
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        conn.execute("DELETE FROM products")
    conn.close()
    assert len(state_reader.cart_items()) == 0


def test_state_reader_not_reachable_over_http():
    for module in (routes_api, routes_html, app_module):
        assert "state_reader" not in open(module.__file__).read()


def test_business_rules_only_in_service():
    """Routes must not inspect stock, availability, quantity limits or prices."""
    for module in (routes_api, routes_html):
        source = open(module.__file__).read()
        for word in ("MAX_QTY", "stock", "available", "price", "BR1", "BR2", "BR3", "BR5", "BR6"):
            assert word not in source, f"{module.__name__} mentions {word}"
