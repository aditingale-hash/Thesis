"""M2: model client, prompt, action parser, history, loop with S1-S5."""

import json

import httpx
import pytest

from agent import loop
from agent.action_parser import parse_action
from agent.model_client import ACTION_SCHEMA, ModelError, OllamaClient
from agent.prompt import build_prompt, render
from pipelines.base import ERROR, INVALID, REJECTED, Observation
from tests.fakes import FakeModel, FakePipeline, reply

MODEL_CONFIG = {"model": "test-model", "ollama_url": "http://ollama.test", "num_ctx": 4096, "temperature": 0,
                "seed": 42, "max_output_tokens": 256, "request_timeout_s": 5}
LIMITS = {"max_invocations": 5, "max_consecutive_invalid": 3, "max_seconds": 600}


# ---------------------------------------------------------------- model client

def test_client_returns_text_tokens_duration_and_sends_image():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": reply("finish")}, "prompt_eval_count": 321,
                                         "eval_count": 12, "total_duration": 2_500_000_000})

    client = OllamaClient(MODEL_CONFIG, transport=httpx.MockTransport(handler))
    r = client.chat("hello", image_b64="AAAA")
    assert (r.text, r.input_tokens, r.output_tokens, r.duration_ms) == (reply("finish"), 321, 12, 2500.0)
    body = seen["body"]
    assert body["messages"] == [{"role": "user", "content": "hello", "images": ["AAAA"]}]
    assert body["format"] == ACTION_SCHEMA and body["stream"] is False
    assert body["options"] == {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 256}


def test_client_without_image_and_errors():
    def handler(request):
        assert "images" not in json.loads(request.content)["messages"][0]
        return httpx.Response(500, text="boom")

    client = OllamaClient(MODEL_CONFIG, transport=httpx.MockTransport(handler))
    with pytest.raises(ModelError):
        client.chat("hello")


# ---------------------------------------------------------------- prompt

def test_prompt_has_five_sections_in_order():
    text = render("ACTIONS", "TASK", ["1: click(3) -> executed"], "OBS")
    headings = [l for l in text.splitlines() if l.startswith("## ")]
    assert headings == ["## 1. Role and rules", "## 2. Action space", "## 3. Task", "## 4. History",
                        "## 5. Current observation"]
    assert text.index("ACTIONS") < text.index("TASK") < text.index("1: click(3)") < text.index("OBS")


def test_previous_observations_are_not_repeated():
    model = FakeModel([reply("click", ref=1), reply("click", ref=2), reply("finish")])
    loop.run_agent(FakePipeline(), model, "do it", LIMITS, MODEL_CONFIG)
    last = model.prompts[-1]
    assert "page 0 #3" in last and "page 0 #1" not in last and "page 0 #2" not in last
    assert "1: click(1) -> executed" in last and "2: click(2) -> executed" in last


def test_truncation_marks_step():
    pipeline = FakePipeline(observation_text="x" * 40_000)
    obs = pipeline.observe()
    prompt, truncated = build_prompt(pipeline, obs, "task", [], MODEL_CONFIG)
    assert truncated and len(prompt) / 3.5 <= MODEL_CONFIG["num_ctx"] - MODEL_CONFIG["max_output_tokens"]
    short = Observation("text", "short", 5, "short")
    assert build_prompt(pipeline, short, "task", [], MODEL_CONFIG)[1] is False


# ---------------------------------------------------------------- parser

SPECS = FakePipeline().action_specs()


@pytest.mark.parametrize("text, kind", [
    ("not json", "unparseable"),
    ('{"thought": "x", "action": "click", "args": {"ref": 1}', "unparseable"),
    ("[1, 2]", "unparseable"),
    ('{"thought": "x", "args": {}}', "unparseable"),
    ('{"thought": "x", "action": "click", "args": [1]}', "unparseable"),
    (reply("scroll", direction="down"), "unknown_action"),
    (reply("click"), "bad_args"),
    (reply("click", ref="14"), "bad_args"),
    (reply("click", ref=1.5), "bad_args"),
    (reply("click", ref=True), "bad_args"),
    (reply("click", ref=1, extra=2), "bad_args"),
    (reply("type", ref=1, text=5), "bad_args"),
])
def test_parser_rejects(text, kind):
    result = parse_action(text, SPECS)
    assert result.action is None and result.kind == kind and result.error


def test_parser_accepts_valid_actions():
    assert parse_action(reply("click", ref=14), SPECS).action.args == {"ref": 14}
    assert parse_action(reply("type", ref=2, text="mouse"), SPECS).action.name == "type"
    assert parse_action(reply("finish"), SPECS).action.name == "finish"
    assert parse_action('{"action": "finish", "args": {}}', SPECS).action.name == "finish"


# ---------------------------------------------------------------- loop and stopping conditions

def test_s1_finish_stops_and_one_action_per_invocation():
    pipeline = FakePipeline()
    model = FakeModel([reply("click", ref=1), reply("type", ref=2, text="a"), reply("finish")])
    r = loop.run_agent(pipeline, model, "task", LIMITS, MODEL_CONFIG)
    assert r.termination_reason == loop.S1
    assert len(model.prompts) == 3 and len(pipeline.executed) == 2  # finish is not executed


def test_s2_max_invocations():
    model = FakeModel([reply("click", ref=1)] * 10)
    r = loop.run_agent(FakePipeline(), model, "task", LIMITS, MODEL_CONFIG)
    assert r.termination_reason == loop.S2 and len(model.prompts) == LIMITS["max_invocations"]


def test_s3_consecutive_invalid_responses_and_actions():
    model = FakeModel(["garbage", reply("click", ref=1), "garbage"])
    r = loop.run_agent(FakePipeline(statuses=[INVALID]), model, "task", LIMITS, MODEL_CONFIG)
    assert r.termination_reason == loop.S3 and len(model.prompts) == 3
    assert "invalid response -> response is not valid JSON" in model.prompts[1]


def test_invalid_counter_resets_after_valid_action():
    model = FakeModel(["x", "x", reply("click", ref=1), "x", "x", reply("finish")])
    r = loop.run_agent(FakePipeline(), model, "task", {**LIMITS, "max_invocations": 10}, MODEL_CONFIG)
    assert r.termination_reason == loop.S1


def test_rejected_does_not_count_as_invalid():
    model = FakeModel([reply("click", ref=1)] * 4 + [reply("finish")])
    r = loop.run_agent(FakePipeline(statuses=[REJECTED] * 4), model, "task", LIMITS, MODEL_CONFIG)
    assert r.termination_reason == loop.S1
    assert '-> rejected, page "X": "rejected message"' in model.prompts[-1]


def test_s4_timeout():
    ticks = iter(range(0, 10_000, 400))
    r = loop.run_agent(FakePipeline(), FakeModel([reply("click", ref=1)] * 10), "task", LIMITS, MODEL_CONFIG,
                       clock=lambda: next(ticks))
    assert r.termination_reason == loop.S4


def test_s5_model_error_browser_crash_and_pipeline_error():
    assert loop.run_agent(FakePipeline(), FakeModel([], fail_at=0), "t", LIMITS, MODEL_CONFIG).termination_reason == loop.S5
    assert loop.run_agent(FakePipeline(crash_on_observe=True), FakeModel([]), "t", LIMITS,
                          MODEL_CONFIG).termination_reason == loop.S5
    r = loop.run_agent(FakePipeline(statuses=[ERROR]), FakeModel([reply("click", ref=1)]), "t", LIMITS, MODEL_CONFIG)
    assert r.termination_reason == loop.S5


def test_image_observation_is_sent_to_the_model():
    model = FakeModel([reply("finish")])
    loop.run_agent(FakePipeline(modality="image"), model, "t", LIMITS, MODEL_CONFIG)
    assert model.images == ["iVBORw0KGgo="] and "Screenshot attached." in model.prompts[0]
