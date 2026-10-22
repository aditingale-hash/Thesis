"""Shared fixtures: every test works on its own temporary shop.db."""

import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from shop import build_db, db, reset
from shop.app import app


@pytest.fixture(scope="session")
def snapshot_file(tmp_path_factory):
    """Build snapshot.db once per test session in a temporary directory."""
    return build_db.build(snapshot=tmp_path_factory.mktemp("snapshot") / "snapshot.db")


@pytest.fixture
def shop_db(snapshot_file, tmp_path, monkeypatch):
    """Point the shop at a fresh temporary shop.db reset from the snapshot."""
    monkeypatch.setenv("SHOP_SNAPSHOT_PATH", str(snapshot_file))
    monkeypatch.setenv("SHOP_DB_PATH", str(tmp_path / "shop.db"))
    reset.reset()
    return tmp_path / "shop.db"


def login(client: TestClient) -> TestClient:
    """Log the client in as the test user (as the runner does)."""
    r = client.post("/api/login", json={"username": db.TEST_USERNAME, "password": db.TEST_PASSWORD})
    assert r.status_code == 200
    return client


@pytest.fixture
def client(shop_db):
    """A logged-in test client."""
    return login(TestClient(app))


def notice(html: str) -> str | None:
    """Text of the error notice area of an HTML page, or None if there is none."""
    m = re.search(r'<div class="notice" role="alert"><p>(.*?)</p></div>', html, re.S)
    return unescape(m.group(1)) if m else None


@pytest.fixture(scope="session")
def shop_server():
    """The shop on a free localhost port for the whole test session (reads SHOP_DB_PATH per request)."""
    from evaluation.shop_control import ShopServer
    server = ShopServer().start()
    yield server.url
    server.stop()


@pytest.fixture(scope="session")
def chromium():
    """One headless Chromium for the whole test session."""
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def run_session(shop_db, shop_server, chromium, tmp_path):
    """A logged-in RunSession like the runner creates it."""
    from evaluation.shop_control import login_cookie
    from pipelines.base import RunSession
    name, value = login_cookie(shop_server)
    return RunSession(shop_server, name, value, chromium, tmp_path / "run")
