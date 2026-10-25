"""M3: the three pipelines against the real shop (headless Chromium for DOM and visual)."""

import base64
import json
import re
from pathlib import Path

import pytest

from pipelines.base import ERROR, EXECUTED, INVALID, REJECTED, Action, Observation, RunSession
from pipelines.dom import DomPipeline
from pipelines.tool import FIRST_OBSERVATION, SCHEMAS, ToolPipeline
from pipelines.visual import VisualPipeline
from shop import build_db, state_reader

DOCS = Path(__file__).resolve().parents[1] / "docs"


def ref_of(observation_text: str, role: str, name: str) -> int:
    m = re.search(rf'\[(\d+)\] {role} "{re.escape(name)}"', observation_text)
    assert m, f'{role} "{name}" not in observation'
    return int(m.group(1))


# ---------------------------------------------------------------- DOM

@pytest.fixture
def dom(run_session):
    p = DomPipeline()
    p.attach(run_session)
    yield p
    p.close()


def test_dom_starts_logged_in_on_start_page(dom):
    text = dom.observe().content
    assert text.startswith("Page title: Home - TechDesk Shop\nURL: ")
    assert "Log in" not in text and "Password" not in text
    assert '[2] searchbox "Search products" value=""' in text
    assert 'text "Search products"' not in text  # the visually hidden label is the field's name, not text


def test_dom_search_flow_tree_and_example(dom):
    obs = dom.observe().content
    assert dom.execute(Action("type", {"ref": ref_of(obs, "searchbox", "Search products"), "text": "mouse m2"})).status == EXECUTED
    r = dom.execute(Action("click", {"ref": ref_of(obs, "button", "Search")}))
    assert r.status == EXECUTED and r.summary == 'page "Search results"'
    text = dom.observe().content
    # one link per product (the aria-hidden image link is dropped), indented card text below it
    assert text.count('link "Wireless Mouse M2"') == 1
    assert re.search(r'\n(\s+)listitem\n\1  text "Bestseller"\n\1  text "Mice"\n\1  \[\d+\] link "Wireless Mouse M2"\n'
                     r'\1  text "Rating: 3.9 / 5"\n\1  text "19.99 EUR"\n\1  text "Available"\n\1listitem', text)
    assert '[' in text and 'link "Price: low to high"' in text
    (DOCS / "dom_observation_example.txt").write_text(text + "\n", encoding="utf-8")


def test_dom_stale_and_unknown_refs_are_invalid(dom):
    obs = dom.observe().content
    mice = ref_of(obs, "link", "Mice")
    assert dom.execute(Action("click", {"ref": mice})).status == EXECUTED
    # same number again without a new observation: the page changed, the ref is stale
    assert dom.execute(Action("click", {"ref": mice})).status == INVALID
    dom.observe()
    assert dom.execute(Action("click", {"ref": 9999})).status == INVALID


def test_dom_type_into_non_field_and_go_back(dom):
    obs = dom.observe().content
    assert dom.execute(Action("go_back")).status == INVALID  # fresh context: no previous page
    assert dom.execute(Action("type", {"ref": ref_of(obs, "link", "Cart"), "text": "x"})).status == INVALID


def test_dom_rejected_shows_core_message(dom):
    dom.page.goto("/products/106")
    obs = dom.observe().content
    r = dom.execute(Action("click", {"ref": ref_of(obs, "button", "Add to cart")}))
    assert (r.status, r.message) == (REJECTED, "Silent Office Mouse is not available.")


def test_dom_truncation_removes_text_first(dom):
    dom.page.goto("/search")
    obs = dom.observe()
    n_refs = obs.content.count("] ")
    truncated = dom.truncate(obs, len(obs.content) // 2)
    assert len(truncated) <= len(obs.content) // 2 and truncated.endswith("(observation truncated)")
    assert truncated.count("] ") == n_refs  # all interactive elements kept while text could be removed
    tiny = dom.truncate(obs, 400)
    assert len(tiny) <= 400 and tiny.count("] ") < n_refs


# ---------------------------------------------------------------- visual

@pytest.fixture
def visual(run_session):
    p = VisualPipeline()
    p.attach(run_session)
    yield p
    p.close()


def center(page, selector):
    box = page.locator(selector).first.bounding_box()  # test helper only, never used by the pipeline
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def test_visual_observation_is_viewport_png_only(visual, run_session):
    obs = visual.observe()
    png = base64.b64decode(obs.content)
    assert obs.modality == "image" and png[:8] == b"\x89PNG\r\n\x1a\n"
    assert int.from_bytes(png[16:20], "big") == 1280 and int.from_bytes(png[20:24], "big") == 800
    assert (run_session.run_dir / "step_1.png").read_bytes() == png
    assert "TechDesk" not in obs.prompt_text and "Home" not in obs.prompt_text


def test_visual_click_coordinates_pixels_and_normalised(visual):
    x, y = center(visual.page, "header nav a")
    r = visual.execute(Action("click", {"x": x, "y": y}))
    assert r.status == EXECUTED and r.summary == "" and visual.page.title() == "Cart - TechDesk Shop"
    visual.page.goto("/")
    visual.coordinate_mode = "normalized_1000"
    x, y = center(visual.page, "header nav a")
    visual.execute(Action("click", {"x": x / 1280 * 1000, "y": y / 800 * 1000}))
    assert visual.page.title() == "Cart - TechDesk Shop"


def test_visual_off_screen_and_bad_args_are_invalid(visual):
    assert visual.execute(Action("click", {"x": 1280, "y": 10})).status == INVALID
    assert visual.execute(Action("click", {"x": 10, "y": -1})).status == INVALID
    assert visual.execute(Action("press", {"key": "F13"})).status == INVALID
    assert visual.execute(Action("scroll", {"direction": "left"})).status == INVALID
    assert visual.execute(Action("scroll", {"direction": "down"})).status == EXECUTED


def test_visual_type_and_enter_and_rejection_without_dom_text(visual):
    x, y = center(visual.page, "#q")
    assert visual.execute(Action("type", {"x": x, "y": y, "text": "mouse"})).status == EXECUTED
    assert visual.execute(Action("type", {"x": x, "y": y, "text": "notebook a5"})).status == EXECUTED  # replaces
    assert visual.page.input_value("#q") == "notebook a5" and "/search" not in visual.page.url  # no submit
    assert visual.execute(Action("press", {"key": "Enter"})).status == EXECUTED
    assert "q=notebook+a5" in visual.page.url
    assert visual.execute(Action("type", {"x": 2000, "y": y, "text": "x"})).status == INVALID
    visual.page.goto("/products/106")
    x, y = center(visual.page, ".add-form button")
    r = visual.execute(Action("click", {"x": x, "y": y}))
    assert r.status == REJECTED and r.message == "" and r.summary == ""          # nothing from the DOM for the agent
    assert r.detail == "Silent Office Mouse is not available."                    # trace only


# ---------------------------------------------------------------- tool

@pytest.fixture
def tool(run_session):
    p = ToolPipeline()
    p.attach(run_session)
    yield p
    p.close()


def test_tool_schemas_match_frontend_and_catalogue():
    assert [t["name"] for t in SCHEMAS] == ["search_products", "get_product", "get_cart", "add_to_cart",
                                            "update_cart_item", "remove_from_cart", "checkout"]
    category = SCHEMAS[0]["parameters"]["properties"]["category"]["enum"]
    assert category == build_db.load_catalogue()["categories"]


def test_tool_first_observation_executed_rejected_invalid(tool):
    assert tool.observe().content == FIRST_OBSERVATION
    r = tool.execute(Action("add_to_cart", {"product_id": 101, "quantity": 2}))
    assert r.status == EXECUTED and json.loads(tool.observe().content.split("\n", 1)[1])["total"] == 39.98
    assert state_reader.cart_items() == [{"product_id": 101, "quantity": 2}]
    r = tool.execute(Action("add_to_cart", {"product_id": 106, "quantity": 1}))
    assert (r.status, r.message) == (REJECTED, "Silent Office Mouse is not available.")
    assert '"rule": "BR2"' in tool.observe().content
    assert tool.execute(Action("search_products", {"category": "Phones"})).status == INVALID
    assert tool.execute(Action("get_cart", {"extra": 1})).status == INVALID


def test_tool_search_truncation_and_shop_down(tool, run_session):
    tool.execute(Action("search_products", {"query": ""}))
    obs = tool.observe()
    short = tool.truncate(obs, 2000)
    assert len(short) <= 2000 and short.endswith("(observation truncated)") and '"id": 101' in short
    down = ToolPipeline()
    down.attach(RunSession("http://127.0.0.1:9", run_session.cookie_name, run_session.cookie_value))
    assert down.execute(Action("get_cart", {})).status == ERROR
