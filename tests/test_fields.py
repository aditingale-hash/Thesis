"""M1: the JSON API returns the same fields the corresponding HTML page shows."""

import re
from html import unescape

from shop import reset


def _eur(value: float) -> str:
    return f"{value:.2f} EUR"


def _text(html: str) -> str:
    """Visible text of a page, whitespace-normalised."""
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())


def test_search_results_match(client):
    for params in ({"q": "mouse", "sort": "price_asc"}, {"category": "Webcams", "sort": "rating_desc"}, {}):
        api_params = {("query" if k == "q" else k): v for k, v in params.items()}
        api = client.get("/api/products", params=api_params).json()
        page = client.get("/search", params=params).text
        items = re.findall(r'<li class="product">(.*?)</li>', page, re.S)
        assert [int(i) for i in re.findall(r'<h3><a href="/products/(\d+)"', "".join(items))] == [p["id"] for p in api["results"]]
        for p, item in zip(api["results"], items):
            text = _text(item)
            assert set(p) == {"id", "name", "category", "price", "rating", "available", "badge"}
            assert p["name"] in text and p["category"] in text
            assert _eur(p["price"]) in text
            assert f"Rating: {p['rating']:.1f} / 5" in text
            assert ("Not available" in text) == (not p["available"])
            assert (p["badge"] or "") in text


def test_product_detail_matches(client):
    for pid in (101, 106, 306):
        api = client.get(f"/api/products/{pid}").json()
        text = _text(client.get(f"/products/{pid}").text)
        assert set(api) == {"id", "name", "category", "price", "rating", "available", "badge", "stock", "description"}
        for expected in (api["name"], api["category"], _eur(api["price"]), f"{api['rating']:.1f} / 5",
                         "Available" if api["available"] else "Not available",
                         f"In stock: {api['stock']}", api["description"], api["badge"] or ""):
            assert expected in text


def test_cart_matches(client):
    reset.reset({"initial_state": {"cart": [{"product_id": 101, "quantity": 2}, {"product_id": 106, "quantity": 1}]}})
    api = client.get("/api/cart").json()
    page = client.get("/cart").text
    items = re.findall(r'<li class="cart-item">(.*?)</li>', page, re.S)
    assert len(items) == len(api["items"]) == 2
    for item, html in zip(api["items"], items):
        text = _text(html)
        assert set(item) == {"product_id", "name", "unit_price", "quantity", "line_total", "available"}
        assert item["name"] in text and _eur(item["unit_price"]) in text and _eur(item["line_total"]) in text
        assert f'value="{item["quantity"]}"' in html
        assert ("Not available" in text) == (not item["available"])
    assert f"Total: {_eur(api['total'])}" in _text(page)


def test_confirmation_matches(client):
    reset.reset({"initial_state": {"cart": [{"product_id": 101, "quantity": 2}]}})
    page = client.post("/checkout").text
    reset.reset({"initial_state": {"cart": [{"product_id": 101, "quantity": 2}]}})
    api = client.post("/api/checkout").json()
    text = _text(page)
    assert set(api) == {"order_id", "status", "created", "lines", "total"}
    assert f"Order number {api['order_id']}" in text and f"Status {api['status']}" in text
    for line in api["lines"]:
        assert f"{line['name']}: {line['quantity']} x {_eur(line['unit_price'])} = {_eur(line['line_total'])}" in text
    assert f"Total: {_eur(api['total'])}" in text


def test_no_agent_specific_attributes(client):
    """No test ids, data attributes or scripts; every field labelled; CSS without hover/animation/web fonts."""
    reset.reset({"initial_state": {"cart": [{"product_id": 101, "quantity": 1}]}})
    for url in ("/login", "/register", "/", "/search?q=mouse", "/products/101", "/cart", "/checkout"):
        html = client.get(url).text
        assert "data-testid" not in html and "data-" not in html
        assert "<script" not in html and "loading=" not in html and "<dialog" not in html
        for field_id in re.findall(r'<input type="(?:text|password|search|number)" id="([^"]+)"', html):
            assert f'<label for="{field_id}"' in html
    css = re.sub(r"/\*.*?\*/", "", client.get("/static/style.css").text, flags=re.S)  # rules only, no comments
    assert not re.search(r":hover|transition|animation|@font-face|@import|url\(", css)
