"""Shared Playwright helpers of the two browser pipelines (DOM and visual).

Both pipelines use the same browser setup, the same waiting rule after actions and the
same rejection detection, so that only the representation differs between them.
"""

import time

from playwright.sync_api import Error as PlaywrightError

VIEWPORT = {"width": 1280, "height": 800}
NAVIGATION_QUIET_MS = 500   # how long to wait for a navigation to start after a click / key press
SITE_SUFFIX = " - TechDesk Shop"


def open_page(session):
    """New browser context (fresh cookies/history) with the run's session cookie; open the start page."""
    context = session.browser.new_context(viewport=VIEWPORT, base_url=session.base_url)
    context.add_cookies([{"name": session.cookie_name, "value": session.cookie_value, "url": session.base_url}])
    page = context.new_page()
    page.goto("/", wait_until="load")
    return context, page


def run_and_settle(page, fn, wait_for_navigation: bool = True) -> bool:
    """Run ``fn`` (one input action) and wait until the page is stable.

    If the action starts a navigation (link, form submit, back), wait for the new
    document's ``load`` event. Returns True if a new document was loaded.
    """
    page.evaluate("window.__agentDocument = true")
    fn()
    if not wait_for_navigation:
        return False
    deadline = time.monotonic() + NAVIGATION_QUIET_MS / 1000
    navigated = False
    while time.monotonic() < deadline:
        try:
            if page.evaluate("window.__agentDocument !== true"):
                navigated = True
                break
        except PlaywrightError:  # execution context destroyed: navigation in progress
            navigated = True
            break
        page.wait_for_timeout(25)
    page.wait_for_load_state("load")
    return navigated


def notice_text(page) -> str:
    """Text of the error notice at the top of the page, or "" (used to classify 'rejected')."""
    notice = page.query_selector('.notice[role="alert"]')
    return notice.inner_text().strip() if notice else ""


def title(page) -> str:
    t = page.title()
    return t[: -len(SITE_SUFFIX)] if t.endswith(SITE_SUFFIX) else t


def is_infrastructure_error(e: Exception) -> bool:
    """Browser/page closed or shop unreachable (-> status error, S5)."""
    text = str(e)
    return any(s in text for s in ("Target page, context or browser has been closed", "Browser has been closed",
                                   "net::ERR_CONNECTION_REFUSED", "Connection closed"))
