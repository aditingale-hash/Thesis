"""Turn the model's raw response into an Action, or mark it invalid.

Valid = a JSON object with a known action name and arguments of the right types
(no missing required, no unknown arguments). Everything else is an invalid response:
no action is executed and an error line is added to the history.
"""

import json
from dataclasses import dataclass

from pipelines.base import Action

_TYPE_CHECKS = {
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "string": lambda v: isinstance(v, str),
}


@dataclass
class ParseResult:
    action: Action | None
    error: str = ""          # reason if invalid
    kind: str = ""           # "unparseable" | "unknown_action" | "bad_args" (for failure labels)


def parse_action(text: str, specs: dict) -> ParseResult:
    """Parse ``{"thought": str, "action": str, "args": object}`` against the pipeline's action specs."""
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return ParseResult(None, "response is not valid JSON", "unparseable")
    if not isinstance(data, dict) or not isinstance(data.get("action"), str) or not isinstance(data.get("args", {}), dict):
        return ParseResult(None, 'response must be {"thought": ..., "action": "<name>", "args": {...}}', "unparseable")
    name, args = data["action"], data.get("args", {})
    if name not in specs:
        return ParseResult(None, f'unknown action "{name}"', "unknown_action")
    spec = specs[name]
    unknown = sorted(set(args) - set(spec))
    if unknown:
        return ParseResult(None, f"{name}: unknown argument(s) {', '.join(unknown)}", "bad_args")
    for arg, (json_type, required) in spec.items():
        if arg not in args:
            if required:
                return ParseResult(None, f"{name}: missing argument {arg}", "bad_args")
            continue
        if not _TYPE_CHECKS[json_type](args[arg]):
            return ParseResult(None, f"{name}: argument {arg} must be of type {json_type}", "bad_args")
    return ParseResult(Action(name, args))
