"""Strict per-pipeline response schemas (structured output) and how they reach Ollama."""

import json

import httpx
import jsonschema
import pytest

from agent import loop
from agent.model_client import OllamaClient
from evaluation.validate_tasks import REF_DIR, load_tasks
from pipelines.dom import DomPipeline
from pipelines.tool import ToolPipeline
from pipelines.visual import VisualPipeline
from tests.fakes import FakeModel, FakePipeline, reply

PIPELINES = {"dom": DomPipeline(), "visual": VisualPipeline(), "tool": ToolPipeline()}


def valid(schema, response: dict) -> bool:
    try:
        jsonschema.validate(response, schema)
        return True
    except jsonschema.ValidationError:
        return False


def r(action, **args):
    return {"thought": "t", "action": action, "args": args}


@pytest.mark.parametrize("name", PIPELINES)
def test_schema_is_valid_json_schema_and_covers_all_actions(name):
    pipeline = PIPELINES[name]
    schema = pipeline.response_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    names = [v["properties"]["action"]["enum"][0] for v in schema["anyOf"]]
    assert names == list(pipeline.action_specs())
    assert valid(schema, r("finish")) and not valid(schema, r("finish", x=1))


def test_dom_schema_rejects_the_mistakes_seen_in_the_smoke_test():
    schema = PIPELINES["dom"].response_schema()
    assert valid(schema, r("click", ref=5)) and valid(schema, r("type", ref=2, text="Wireless Mouse M2"))
    assert not valid(schema, r("click", ref=[5]))     # list instead of a number
    assert not valid(schema, r("click"))              # missing ref
    assert not valid(schema, r("click", ref=5, text="x"))
    assert not valid(schema, r("select", ref=5, option="a"))
    assert not valid(schema, {"action": "click", "args": {"ref": 5}})  # thought is required


def test_visual_schema_fixed_values():
    schema = PIPELINES["visual"].response_schema()
    assert valid(schema, r("click", x=640, y=35.5)) and valid(schema, r("press", key="Enter"))
    assert valid(schema, r("scroll", direction="down"))
    assert not valid(schema, r("scroll", direction="left")) and not valid(schema, r("press", key="F13"))
    assert not valid(schema, r("click", x=640))
    assert valid(schema, r("type", x=555, y=35, text="Wireless Mouse M2"))
    assert not valid(schema, r("type", text="Wireless Mouse M2"))       # the target position is required


def test_tool_schema_accepts_all_reference_calls_and_enforces_enums():
    schema = PIPELINES["tool"].response_schema()
    for task in load_tasks():
        for step in json.loads((REF_DIR / f"{task['id']}.json").read_text())["tool"]:
            assert valid(schema, r(step["action"], **step["args"])), (task["id"], step)
    assert valid(schema, r("search_products")) and valid(schema, r("search_products", query="mouse"))
    assert not valid(schema, r("search_products", category="Phones"))
    assert not valid(schema, r("add_to_cart", product_id=101))           # quantity required
    assert not valid(schema, r("add_to_cart", product_id="101", quantity=1))


def test_loop_sends_the_pipeline_schema_and_client_forwards_it():
    pipeline = FakePipeline()
    model = FakeModel([reply("finish")])
    loop.run_agent(pipeline, model, "t", {"max_invocations": 5, "max_consecutive_invalid": 3, "max_seconds": 60},
                   {"num_ctx": 4096, "max_output_tokens": 256})
    assert model.schemas == [pipeline.response_schema()]
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": reply("finish")}, "prompt_eval_count": 1, "eval_count": 1})

    config = {"model": "m", "ollama_url": "http://x", "num_ctx": 4096, "temperature": 0, "seed": 1, "max_output_tokens": 9}
    OllamaClient(config, transport=httpx.MockTransport(handler)).chat("p", schema=pipeline.response_schema())
    assert seen["format"] == pipeline.response_schema()
