"""DOM / accessibility pipeline.

Observation: page title + URL + reduced accessibility tree of the whole page
(``dom_extract.js``), interactive elements numbered ``[n]``.
Actions: click(ref), type(ref, text), go_back(), finish().
(``select(ref, option)`` of the specification is not offered: the shop has no
<select> element, see docs/thesis_notes.md D3.)
"""

from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from pipelines import browser
from pipelines.base import (ERROR, EXECUTED, FINISH_SPEC, INVALID, REJECTED, Action, ActionResult,
                            InteractionPipeline, Observation)

EXTRACT_JS = Path(__file__).with_name("dom_extract.js").read_text(encoding="utf-8")
FILLABLE = {"textbox", "searchbox", "spinbutton"}

ACTION_SPACE = """You see the current web page as a list of its elements. Interactive elements have a number in brackets, e.g. [7] button "OK".
Indentation shows which elements belong together.
Actions (numbers refer to the CURRENT page only):
- click(ref: integer): click the element with this number (links, buttons, fields).
- type(ref: integer, text: string): replace the content of the input field with this number by the text. Typing does not submit; click the corresponding button afterwards.
- go_back(): go back to the previous page.
- finish(): the task is completed."""


class DomPipeline(InteractionPipeline):
    name = "dom"

    def __init__(self):
        self.context = self.page = None
        self.epoch = 0
        self.items: list[dict] = []

    def attach(self, session) -> None:
        self.context, self.page = browser.open_page(session)

    def action_space(self) -> str:
        return ACTION_SPACE

    def action_specs(self) -> dict:
        return {"click": {"ref": ("integer", True)},
                "type": {"ref": ("integer", True), "text": ("string", True)},
                "go_back": {}, **FINISH_SPEC}

    # ------------------------------------------------------------ observation

    def observe(self) -> Observation:
        self.epoch += 1
        self.items = self.page.evaluate(EXTRACT_JS, self.epoch)
        text = self._format(self.items)
        return Observation("text", text, len(text), text)

    def _header(self) -> list[str]:
        return [f"Page title: {self.page.title()}", f"URL: {self.page.url}"]

    @staticmethod
    def _line(item: dict) -> str:
        indent = "  " * item["depth"]
        name = item["name"].replace('"', "'")
        if "ref" in item:
            line = f'{indent}[{item["ref"]}] {item["role"]} "{name}"'
            if "value" in item:
                line += f' value="{item["value"]}"'
            if item.get("current"):
                line += " (current)"
            return line
        return f'{indent}{item["role"]} "{name}"' if name else f'{indent}{item["role"]}'

    def _format(self, items: list[dict]) -> str:
        return "\n".join(self._header() + [self._line(i) for i in items])

    def truncate(self, observation: Observation, max_chars: int) -> str:
        """Remove non-interactive text nodes from the end first, interactive elements last."""
        items = list(self.items)
        note = "(observation truncated)"
        def fits(lst):
            return len(self._format(lst)) + len(note) + 1 <= max_chars
        i = len(items) - 1
        while not fits(items) and i >= 0:
            if "ref" not in items[i]:
                items.pop(i)
            i -= 1
        while not fits(items) and items:
            items.pop()
        return self._format(items) + "\n" + note

    # ------------------------------------------------------------ actions

    def _element(self, ref: int):
        return self.page.query_selector(f'[data-agent-ref="{self.epoch}:{ref}"]')

    def execute(self, action: Action) -> ActionResult:
        try:
            if action.name == "go_back":
                if self.page.go_back(wait_until="load") is None:
                    return ActionResult(INVALID, "There is no previous page.")
                return ActionResult(EXECUTED, summary=f'page "{browser.title(self.page)}"')
            ref = action.args["ref"]
            element = self._element(ref)
            item = next((i for i in self.items if i.get("ref") == ref), None)
            if element is None or item is None:
                return ActionResult(INVALID, f"There is no element [{ref}] on the current page.")
            if action.name == "type":
                if item["role"] not in FILLABLE:
                    return ActionResult(INVALID, f"Element [{ref}] is not an input field.")
                browser.run_and_settle(self.page, lambda: element.fill(action.args["text"], timeout=3000),
                                       wait_for_navigation=False)
                return ActionResult(EXECUTED, summary=f'page "{browser.title(self.page)}"')
            navigated = browser.run_and_settle(self.page, lambda: element.click(timeout=3000))
        except PlaywrightError as e:
            if browser.is_infrastructure_error(e):
                return ActionResult(ERROR, str(e))
            return ActionResult(INVALID, f"The action could not be performed: {str(e).splitlines()[0]}")
        summary = f'page "{browser.title(self.page)}"'
        notice = browser.notice_text(self.page) if navigated else ""
        if notice:
            return ActionResult(REJECTED, notice, summary)
        return ActionResult(EXECUTED, summary=summary)

    def close(self) -> None:
        if self.context:
            self.context.close()
