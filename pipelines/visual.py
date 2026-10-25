"""Visual pipeline.

Observation: screenshot of the 1280x800 viewport only (PNG). No DOM or accessibility
information of any kind reaches the agent: the history shows only the action and its
status, never page titles or notice texts.
Actions: click(x, y), type(x, y, text), press(key), scroll(direction), go_back(), finish(),
executed with page.mouse / page.keyboard only (never element handles).
"""

import base64

from playwright.sync_api import Error as PlaywrightError

from pipelines import browser
from pipelines.base import (ERROR, EXECUTED, FINISH_SPEC, INVALID, REJECTED, Action, ActionResult,
                            InteractionPipeline, Observation)

WIDTH, HEIGHT = browser.VIEWPORT["width"], browser.VIEWPORT["height"]
SCROLL_PX = 600
KEYS = {"Enter", "Tab", "Shift+Tab", "Backspace", "Delete", "Escape", "ArrowUp", "ArrowDown", "ArrowLeft",
        "ArrowRight", "PageUp", "PageDown", "Home", "End", "Control+A"}

COORDINATES = {
    "pixels": f"x and y are pixel coordinates in the screenshot ({WIDTH} x {HEIGHT}); (0, 0) is the top-left corner.",
    "normalized_1000": "x and y are normalised coordinates from 0 to 1000 on both axes; (0, 0) is the top-left corner, (1000, 1000) the bottom-right corner.",
}


class VisualPipeline(InteractionPipeline):
    name = "visual"

    def __init__(self, coordinate_mode: str = "pixels", perception: str = "none"):
        if coordinate_mode not in COORDINATES:
            raise ValueError(f"unknown coordinate_mode {coordinate_mode}")
        if perception != "none":
            raise NotImplementedError("Only perception: none is implemented (see docs/thesis_notes.md D18).")
        self.coordinate_mode = coordinate_mode
        self.context = self.page = None
        self.run_dir = None
        self.step = 0

    def attach(self, session) -> None:
        self.context, self.page = browser.open_page(session)
        self.run_dir = session.run_dir

    def action_space(self) -> str:
        return f"""You see a screenshot of the browser window. {COORDINATES[self.coordinate_mode]}
Actions:
- click(x: number, y: number): mouse click at this position.
- type(x: number, y: number, text: string): click the input field at this position and replace its content with the text. Typing does not submit; press("Enter") or click the button afterwards.
- press(key: string): press a key: {", ".join(sorted(KEYS))}.
- scroll(direction: string): scroll the page "up" or "down" by {SCROLL_PX} pixels.
- go_back(): go back to the previous page.
- finish(): the task is completed."""

    def action_specs(self) -> dict:
        return {"click": {"x": ("number", True), "y": ("number", True)},
                "type": {"x": ("number", True), "y": ("number", True), "text": ("string", True)},
                "press": {"key": ("string", True)},
                "scroll": {"direction": ("string", True)},
                "go_back": {}, **FINISH_SPEC}

    def argument_values(self) -> dict:
        return {"press": {"key": sorted(KEYS)}, "scroll": {"direction": ["up", "down"]}}

    def observe(self) -> Observation:
        png = self.page.screenshot(type="png", full_page=False)
        self.step += 1
        if self.run_dir is not None:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            (self.run_dir / f"step_{self.step}.png").write_bytes(png)
        caption = f"The screenshot of the current browser window ({WIDTH} x {HEIGHT} pixels) is attached."
        return Observation("image", base64.b64encode(png).decode(), len(png), caption)

    def to_pixels(self, x: float, y: float) -> tuple[float, float]:
        """Convert model coordinates to viewport pixels."""
        if self.coordinate_mode == "normalized_1000":
            return x * WIDTH / 1000, y * HEIGHT / 1000
        return x, y

    def execute(self, action: Action) -> ActionResult:
        args = action.args
        try:
            if action.name in ("click", "type"):
                x, y = self.to_pixels(args["x"], args["y"])
                if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
                    return ActionResult(INVALID, f"The position ({args['x']}, {args['y']}) is outside the screenshot.")
            if action.name == "click":
                navigated = browser.run_and_settle(self.page, lambda: self.page.mouse.click(x, y))
            elif action.name == "type":
                # one action like the DOM pipeline's type(ref, text): focus the field at the position,
                # select its content and replace it, all with input events (no element access)
                def type_at():
                    self.page.mouse.click(x, y)
                    self.page.keyboard.press("Control+A")
                    self.page.keyboard.type(args["text"])
                browser.run_and_settle(self.page, type_at, wait_for_navigation=False)
                navigated = False
            elif action.name == "press":
                if args["key"] not in KEYS:
                    return ActionResult(INVALID, f'Unknown key "{args["key"]}".')
                navigated = browser.run_and_settle(self.page, lambda: self.page.keyboard.press(args["key"]))
            elif action.name == "scroll":
                if args["direction"] not in ("up", "down"):
                    return ActionResult(INVALID, 'direction must be "up" or "down".')
                dy = SCROLL_PX if args["direction"] == "down" else -SCROLL_PX
                browser.run_and_settle(self.page, lambda: (self.page.mouse.wheel(0, dy), self.page.wait_for_timeout(150)),
                                       wait_for_navigation=False)
                navigated = False
            else:  # go_back
                if self.page.go_back(wait_until="load") is None:
                    return ActionResult(INVALID, "There is no previous page.")
                navigated = False
        except PlaywrightError as e:
            if browser.is_infrastructure_error(e):
                return ActionResult(ERROR, str(e))
            return ActionResult(INVALID, f"The action could not be performed: {str(e).splitlines()[0]}")
        # Rejection is detected from the page for the statistics only; the text stays out of the
        # agent's history (detail), because the visual agent may only learn it from the screenshot.
        notice = browser.notice_text(self.page) if navigated else ""
        if notice:
            return ActionResult(REJECTED, detail=notice)
        return ActionResult(EXECUTED)

    def close(self) -> None:
        if self.context:
            self.context.close()
