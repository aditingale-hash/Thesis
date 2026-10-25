"""M1: all HTML pages work in a real browser (headless Chromium, 1280x800).

Walks through the whole shopping flow with Playwright and saves the two thesis
screenshots (search results page, cart page) to docs/figures/.
"""

from pathlib import Path

import pytest

from shop import db

FIGURES = Path(__file__).resolve().parents[1] / "docs" / "figures"


@pytest.fixture
def page(shop_db, shop_server, chromium):
    context = chromium.new_context(viewport={"width": 1280, "height": 800}, base_url=shop_server)
    yield context.new_page()
    context.close()


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
    page.get_by_role("navigation", name="Category filter").get_by_role("link", name="Mice", exact=True).click()
    page.get_by_role("link", name="Price: low to high").click()
    names = page.locator(".results h3").all_inner_texts()
    assert names[0] == "Compact Travel Mouse" and "Gaming Mouse G5" == names[-1]
    FIGURES.mkdir(parents=True, exist_ok=True)
    page.wait_for_load_state("load")  # images loaded before the figure is taken
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
    page.wait_for_load_state("load")
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


def test_registration_in_browser(page):
    page.goto("/login")
    page.get_by_role("link", name="Create an account").click()
    page.get_by_label("Username").fill("maria.k")
    page.get_by_label("Password", exact=True).fill("short")
    page.get_by_label("Repeat password").fill("short")
    page.get_by_role("button", name="Create account").click()
    assert notice(page) == "Password must be at least 8 characters long."
    page.get_by_label("Password", exact=True).fill("long-enough-pw")
    page.get_by_label("Repeat password").fill("long-enough-pw")
    page.get_by_role("button", name="Create account").click()
    assert page.title() == "Home - TechDesk Shop"
    page.goto("/products/502")
    page.get_by_role("button", name="Add to cart").click()
    assert "Total: 3.79 EUR" in page.inner_text("main")
