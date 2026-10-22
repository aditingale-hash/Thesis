"""History manager: one line per previous step, observations are never repeated."""

import json

from pipelines.base import EXECUTED, Action, ActionResult


def format_action(action: Action) -> str:
    """``click(14)``, ``type(3, "mouse")``, ``add_to_cart(101, 1)``."""
    return f"{action.name}({', '.join(json.dumps(v, ensure_ascii=False) for v in action.args.values())})"


class History:
    def __init__(self):
        self.lines: list[str] = []

    def add_action(self, step: int, action: Action, result: ActionResult) -> None:
        line = f"{step}: {format_action(action)} -> {result.status}"
        if result.summary:
            line += f", {result.summary}"
        if result.message and result.status != EXECUTED:
            line += f': "{result.message}"'
        self.lines.append(line)

    def add_invalid_response(self, step: int, error: str) -> None:
        self.lines.append(f"{step}: invalid response -> {error}")
