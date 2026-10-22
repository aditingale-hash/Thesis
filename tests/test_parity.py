"""M1 parity tests: every business rule once via the HTML routes and once via /api.

Each case runs on a freshly reset shop, first through the HTML forms (string
values, as a browser sends them), then through the JSON API (typed values, as the
tool pipeline sends them). Both must give the same outcome: same HTTP status,
same error message (or no error), same resulting cart and orders.
"""

import pytest
from fastapi.testclient import TestClient

from shop import reset, state_reader
from shop.app import app
from shop.service import MAX_QTY
from tests.conftest import login, notice

# (case id, expected rule or None, logged in, pre-filled cart, html steps, api steps)
# A step is (method, url, payload); the outcome of the LAST step is compared.
CASES = [
    ("BR1 add without login", "BR1", False, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "1"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": 1})]),
    ("BR1 view cart without login", "BR1", False, [],
     [("GET", "/cart", None)],
     [("GET", "/api/cart", None)]),
    ("BR1 update without login", "BR1", False, [{"product_id": 101, "quantity": 1}],
     [("POST", "/cart/update", {"product_id": "101", "quantity": "2"})],
     [("PUT", "/api/cart/items/101", {"quantity": 2})]),
    ("BR1 remove without login", "BR1", False, [{"product_id": 101, "quantity": 1}],
     [("POST", "/cart/remove", {"product_id": "101"})],
     [("DELETE", "/api/cart/items/101", None)]),
    ("BR1 checkout without login", "BR1", False, [{"product_id": 101, "quantity": 1}],
     [("POST", "/checkout", None)],
     [("POST", "/api/checkout", None)]),
    ("BR1 wrong password", "BR1", False, [],
     [("POST", "/login", {"username": "testuser", "password": "wrong"})],
     [("POST", "/api/login", {"username": "testuser", "password": "wrong"})]),
    ("BR2 add unavailable product", "BR2", True, [],
     [("POST", "/cart/add", {"product_id": "106", "quantity": "1"})],
     [("POST", "/api/cart/items", {"product_id": 106, "quantity": 1})]),
    ("BR3 quantity above maximum", "BR3", True, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": str(MAX_QTY + 1)})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": MAX_QTY + 1})]),
    ("BR3 quantity zero", "BR3", True, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "0"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": 0})]),
    ("BR3 quantity not a number", "BR3", True, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "two"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": "two"})]),
    ("BR3 quantity not an integer", "BR3", True, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "2.5"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": 2.5})]),
    ("BR3 quantity missing", "BR3", True, [],
     [("POST", "/cart/add", {"product_id": "101"})],
     [("POST", "/api/cart/items", {"product_id": 101})]),
    ("BR3 quantity above stock", "BR3", True, [],
     [("POST", "/cart/add", {"product_id": "305", "quantity": "4"})],
     [("POST", "/api/cart/items", {"product_id": 305, "quantity": 4})]),
    ("BR3 accumulated quantity above maximum", "BR3", True, [{"product_id": 101, "quantity": 6}],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "5"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": 5})]),
    ("BR4 adding twice increases quantity", None, True, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "1"}),
      ("POST", "/cart/add", {"product_id": "101", "quantity": "2"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": 1}),
      ("POST", "/api/cart/items", {"product_id": 101, "quantity": 2})]),
    ("BR5 update to zero", "BR5", True, [{"product_id": 101, "quantity": 2}],
     [("POST", "/cart/update", {"product_id": "101", "quantity": "0"})],
     [("PUT", "/api/cart/items/101", {"quantity": 0})]),
    ("BR5 update above maximum", "BR5", True, [{"product_id": 101, "quantity": 2}],
     [("POST", "/cart/update", {"product_id": "101", "quantity": str(MAX_QTY + 1)})],
     [("PUT", "/api/cart/items/101", {"quantity": MAX_QTY + 1})]),
    ("BR5 valid update", None, True, [{"product_id": 101, "quantity": 2}],
     [("POST", "/cart/update", {"product_id": "101", "quantity": "5"})],
     [("PUT", "/api/cart/items/101", {"quantity": 5})]),
    ("BR5 removal is a separate operation", None, True,
     [{"product_id": 101, "quantity": 2}, {"product_id": 502, "quantity": 1}],
     [("POST", "/cart/remove", {"product_id": "101"})],
     [("DELETE", "/api/cart/items/101", None)]),
    ("BR3 update above stock", "BR3", True, [{"product_id": 305, "quantity": 1}],
     [("POST", "/cart/update", {"product_id": "305", "quantity": "4"})],
     [("PUT", "/api/cart/items/305", {"quantity": 4})]),
    ("BR6 checkout empty cart", "BR6", True, [],
     [("POST", "/checkout", None)],
     [("POST", "/api/checkout", None)]),
    ("BR6 checkout with unavailable item", "BR6", True,
     [{"product_id": 101, "quantity": 1}, {"product_id": 106, "quantity": 1}],
     [("POST", "/checkout", None)],
     [("POST", "/api/checkout", None)]),
    ("BR7 checkout creates order and empties cart", None, True,
     [{"product_id": 101, "quantity": 2}, {"product_id": 502, "quantity": 3}],
     [("POST", "/checkout", None)],
     [("POST", "/api/checkout", None)]),
    ("BR8 client cannot set a price", None, True, [],
     [("POST", "/cart/add", {"product_id": "101", "quantity": "1", "price": "0.01", "unit_price": "0.01"}),
      ("POST", "/checkout", {"total": "0.01"})],
     [("POST", "/api/cart/items", {"product_id": 101, "quantity": 1, "price": 0.01, "unit_price": 0.01}),
      ("POST", "/api/checkout", {"total": 0.01})]),
    ("NOT_FOUND unknown product", "NOT_FOUND", True, [],
     [("POST", "/cart/add", {"product_id": "9999", "quantity": "1"})],
     [("POST", "/api/cart/items", {"product_id": 9999, "quantity": 1})]),
    ("NOT_FOUND update item not in cart", "NOT_FOUND", True, [],
     [("POST", "/cart/update", {"product_id": "101", "quantity": "2"})],
     [("PUT", "/api/cart/items/101", {"quantity": 2})]),
    ("INVALID_INPUT unknown category", "INVALID_INPUT", True, [],
     [("GET", "/search?category=Phones", None)],
     [("GET", "/api/products?category=Phones", None)]),
]


def _state():
    """Cart and orders, without the order timestamp (differs between the two runs)."""
    orders = [{k: v for k, v in o.items() if k != "created"} for o in state_reader.orders()]
    return state_reader.cart_items(), orders


def _run(steps, logged_in, initial_cart, is_api):
    """Reset, run the steps on a fresh client and return (status, message, rule, state)."""
    reset.reset({"initial_state": {"cart": initial_cart}})
    client = TestClient(app)
    if logged_in:
        login(client)
    for method, url, payload in steps:
        if is_api:
            r = client.request(method, url, json=payload)
        else:
            r = client.request(method, url, data=payload, follow_redirects=True)
    if is_api:
        error = r.json().get("error") if isinstance(r.json(), dict) else None
        return r.status_code, error and error["message"], error and error["rule"], _state()
    return r.status_code, notice(r.text), None, _state()


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
def test_html_and_api_parity(shop_db, case):
    _, rule, logged_in, initial_cart, html_steps, api_steps = case
    html_status, html_msg, _, html_state = _run(html_steps, logged_in, initial_cart, is_api=False)
    api_status, api_msg, api_rule, api_state = _run(api_steps, logged_in, initial_cart, is_api=True)

    assert api_rule == rule
    assert html_msg == api_msg
    assert html_status == api_status
    assert html_state == api_state
    if rule is not None:
        assert api_msg, "a rejected request must carry a message"
        cart, orders = api_state
        assert cart == initial_cart and orders == [], "a rejected request must not change the state"


def test_br4_never_two_lines(client):
    client.post("/api/cart/items", json={"product_id": 101, "quantity": 1})
    client.post("/cart/add", data={"product_id": "101", "quantity": "1"})
    assert state_reader.cart_items() == [{"product_id": 101, "quantity": 2}]


def test_br7_br8_order_uses_core_prices(client):
    reset.reset({"initial_state": {"cart": [{"product_id": 101, "quantity": 2}, {"product_id": 502, "quantity": 3}]}})
    order = client.post("/api/checkout", json={"total": 0.01}).json()
    assert order["total"] == round(2 * 19.99 + 3 * 3.79, 2)
    assert [(l["product_id"], l["quantity"], l["unit_price"]) for l in order["lines"]] == [(101, 2, 19.99), (502, 3, 3.79)]
    assert state_reader.cart_items() == []
    stored = state_reader.orders()
    assert len(stored) == 1 and stored[0]["total"] == order["total"] and stored[0]["status"] == "confirmed"
