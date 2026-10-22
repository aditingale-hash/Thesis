"""Start the shop on localhost and log in as the test user (runner setup, outside the timer)."""

import socket
import threading
import time

import httpx
import uvicorn

from pipelines.base import RunSession
from shop import db, reset
from shop.app import SESSION_COOKIE, app


class ShopServer:
    """The shop running with uvicorn in a background thread on a free localhost port."""

    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> "ShopServer":
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)
        return self

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


def login_cookie(base_url: str) -> tuple[str, str]:
    """Log in as the test user via the API; return (cookie name, cookie value)."""
    with httpx.Client(base_url=base_url, timeout=30) as client:
        r = client.post("/api/login", json={"username": db.TEST_USERNAME, "password": db.TEST_PASSWORD})
        r.raise_for_status()
        return SESSION_COOKIE, client.cookies[SESSION_COOKIE]


def prepare_run(task: dict, base_url: str, browser=None, run_dir=None) -> RunSession:
    """Reset the shop to the task's initial state and log in (setup, outside the timer)."""
    reset.reset(task)
    name, value = login_cookie(base_url)
    return RunSession(base_url, name, value, browser, run_dir)
