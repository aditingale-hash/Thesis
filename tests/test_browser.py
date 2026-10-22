"""M1: all HTML pages work in a real browser (headless Chromium, 1280x800).

Walks through the whole shopping flow with Playwright and saves the two thesis
screenshots (search results page, cart page) to docs/figures/.
"""

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from shop import db
from shop.app import app

playwright = pytest.importorskip("playwright.sync_api")

FIGURES = Path(__file__).resolve().parents[1] / "docs" / "figures"


@pytest.fixture
def base_url(shop_db):
    """Run the shop with uvicorn in a background thread on a free port."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()


@pytest.fixture
def page(base_url):
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 800}, base_url=base_url)
        page = context.new_page()
        yield page
        browser.close()


def notice(page):
    alert = page.get_by_role("alert")
    return alert.inner_text() if alert.count() else None


def test_full_flow_in_browser(page):
    page.goto("/login")
    page.get_by_label("Username").fill(db.TEST_USERNAME)
    page.get_by_label("Password").fill(db.TEST_PASSWORD)
    page.get_by_role("button", name="Log in").click()
    assert page.title() == "Home - TechDesk Shop"

    # search + category filter + sort
    page.get_by_label("Search products").fill("mouse")
    page.get_by_role("button", name="Search").click()
    page.get_by_role("link", name="Mice", exact=True).click()
    page.get_by_role("link", name="Price: low to high").click()
    names = page.locator(".results h3").all_inner_texts()
    assert names[0] == "Compact Travel Mouse" and "Gaming Mouse G5" == names[-1]
    FIGURES.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=FIGURES / "search_results.png")

    # product detail: unavailable product is rejected by the core (BR2)
    page.get_by_role("link", name="Silent Office Mouse").click()
    page.get_by_role("button", name="Add to cart").click()
    assert notice(page) == "Silent Office Mouse is not available."
    page.go_back()  # back to the product page
    page.go_back()  # back to the results

    # add two products, one of them twice (BR4)
    page.get_by_role("link", name="Wireless Mouse M2", exact=True).click()
    page.get_by_label("Quantity").fill("2")
    page.get_by_role("button", name="Add to cart").click()
    assert page.title() == "Cart - TechDesk Shop"
    page.goto("/products/502")
    page.get_by_role("button", name="Add to cart").click()
    page.goto("/products/101")
    page.get_by_role("button", name="Add to cart").click()
    assert page.locator(".cart-item").count() == 2
    assert page.get_by_label("Quantity").first.input_value() == "3"

    # update: invalid (BR5) then valid
    page.get_by_label("Quantity").first.fill("0")
    page.get_by_role("button", name="Update").first.click()
    assert notice(page).startswith("Quantity must be a whole number between 1 and 10.")
    page.get_by_label("Quantity").first.fill("4")
    page.get_by_role("button", name="Update").first.click()
    assert notice(page) is None
    assert "Total: 83.75 EUR" in page.inner_text("main")
    page.screenshot(path=FIGURES / "cart.png")

    # remove, checkout, confirm
    page.get_by_role("button", name="Remove").nth(1).click()
    assert page.locator(".cart-item").count() == 1
    page.get_by_role("button", name="Checkout").click()
    assert page.title() == "Checkout - TechDesk Shop"
    page.get_by_role("button", name="Confirm order").click()
    assert page.title() == "Order confirmed - TechDesk Shop"
    assert "Total: 79.96 EUR" in page.inner_text("main")

    # empty cart: checkout rejected (BR6)
    page.goto("/checkout")
    page.get_by_role("button", name="Confirm order").click()
    assert notice(page) == "Your cart is empty."
