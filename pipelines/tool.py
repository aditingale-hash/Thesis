"""Tool pipeline.

Seven tools mirroring the frontend exactly (``tool_schemas.json``); each sends an HTTP
request to the shop's ``/api`` with the run's session cookie. Observation = JSON result
of the last call. Schema violation -> invalid; error from the shop core -> rejected.
"""

import json
from pathlib import Path

import httpx
import jsonschema

from pipelines.base import (ERROR, EXECUTED, FINISH_SPEC, INVALID, REJECTED, Action, ActionResult,
                            InteractionPipeline, Observation)

SCHEMAS = json.loads(Path(__file__).with_name("tool_schemas.json").read_text(encoding="utf-8"))
FIRST_OBSERVATION = "No tool has been called yet."


def _request(name: str, args: dict) -> tuple[str, str, dict]:
    """HTTP method, path and parameters for one tool call."""
    if name == "search_products":
        return "GET", "/api/products", {"params": args}
    if name == "get_product":
        return "GET", f"/api/products/{args['product_id']}", {}
    if name == "get_cart":
        return "GET", "/api/cart", {}
    if name == "add_to_cart":
        return "POST", "/api/cart/items", {"json": args}
    if name == "update_cart_item":
        return "PUT", f"/api/cart/items/{args['product_id']}", {"json": {"quantity": args["quantity"]}}
    if name == "remove_from_cart":
        return "DELETE", f"/api/cart/items/{args['product_id']}", {}
    if name == "checkout":
        return "POST", "/api/checkout", {}
    raise KeyError(name)


def _signature(tool: dict) -> str:
    props, required = tool["parameters"]["properties"], tool["parameters"]["required"]
    parts = []
    for arg, schema in props.items():
        kind = "one of " + ", ".join(f'"{v}"' for v in schema["enum"]) if "enum" in schema else schema["type"]
        parts.append(f"{arg}{'' if arg in required else '?'}: {kind}")
    return f"- {tool['name']}({', '.join(parts)}): {tool['description']}"


class ToolPipeline(InteractionPipeline):
    name = "tool"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self.transport = transport
        self.client = None
        self.last = FIRST_OBSERVATION
        self.last_data = None

    def attach(self, session) -> None:
        self.client = httpx.Client(base_url=session.base_url, cookies={session.cookie_name: session.cookie_value},
                                   timeout=30, transport=self.transport)

    def action_space(self) -> str:
        lines = ["You use the shop through functions. Each action calls one function; its JSON result is the next observation.",
                 "Functions (arguments marked ? are optional):"]
        lines += [_signature(t) for t in SCHEMAS]
        lines.append("- finish(): the task is completed.")
        return "\n".join(lines)

    def action_specs(self) -> dict:
        types = {"integer": "integer", "string": "string", "number": "number"}
        specs = {t["name"]: {a: (types[s["type"]], a in t["parameters"]["required"])
                             for a, s in t["parameters"]["properties"].items()} for t in SCHEMAS}
        return {**specs, **FINISH_SPEC}

    def observe(self) -> Observation:
        return Observation("text", self.last, len(self.last), self.last)

    def truncate(self, observation: Observation, max_chars: int) -> str:
        """Drop search results from the end; otherwise cut the text."""
        data = self.last_data
        note = "\n(observation truncated)"
        if isinstance(data, dict) and isinstance(data.get("results"), list):
            data = {**data, "results": list(data["results"])}
            while data["results"] and len(self._render(self._last_name, data)) + len(note) > max_chars:
                data["results"].pop()
            return self._render(self._last_name, data) + note
        return observation.prompt_text[: max(0, max_chars - len(note))] + note

    @staticmethod
    def _render(name: str, data) -> str:
        return f"Result of {name}:\n" + json.dumps(data, indent=1, ensure_ascii=False)

    def execute(self, action: Action) -> ActionResult:
        tool = next(t for t in SCHEMAS if t["name"] == action.name)
        try:
            jsonschema.validate(action.args, tool["parameters"])
        except jsonschema.ValidationError as e:
            return ActionResult(INVALID, f"{action.name}: {e.message}")
        method, path, kwargs = _request(action.name, action.args)
        try:
            r = self.client.request(method, path, **kwargs)
            data = r.json()
        except (httpx.HTTPError, ValueError) as e:
            return ActionResult(ERROR, f"shop request failed: {e}")
        if r.status_code >= 500:
            return ActionResult(ERROR, f"shop error HTTP {r.status_code}")
        self._last_name, self.last_data = action.name, data
        self.last = self._render(action.name, data)
        if r.status_code >= 400:
            return ActionResult(REJECTED, data.get("error", {}).get("message", f"HTTP {r.status_code}"))
        return ActionResult(EXECUTED)

    def close(self) -> None:
        if self.client:
            self.client.close()
