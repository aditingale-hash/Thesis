"""M4/M5: tasks, goal states, verifier, traces, runner (no Ollama: fake/scripted models)."""

import csv
import json
import re

import pytest

from agent.loop import S1, S2, S5, run_agent
from agent.model_client import ModelError
from evaluation import goal_states, runner
from evaluation.trace import CSV_FIELDS, TraceRecorder
from evaluation.validate_tasks import REF_DIR, load_tasks
from evaluation.verifier import check_cart, check_orders, verify
from pipelines.base import RunSession
from pipelines.dom import DomPipeline
from pipelines.tool import ToolPipeline
from shop import reset
from shop.build_db import load_catalogue
from tests.fakes import FakeModel, reply

MODEL_CONFIG = {"model": "test", "ollama_url": "http://x", "num_ctx": 16384, "temperature": 0, "seed": 42,
                "max_output_tokens": 512, "coordinate_mode": "pixels", "perception": "none"}
LIMITS = {"max_invocations": 25, "max_consecutive_invalid": 3, "max_seconds": 600}
FORBIDDEN = re.compile(r"\b(click|button|page|link|tool|coordinate|screenshot|scroll|search_products|add_to_cart)\b", re.I)


# ---------------------------------------------------------------- tasks and goal states

def test_28_tasks_7_categories_pipeline_neutral():
    tasks = load_tasks()
    assert len(tasks) == 28
    assert sorted({t["category"] for t in tasks}) == [f"C{i}" for i in range(1, 8)]
    assert all(sum(t["category"] == f"C{i}" for t in tasks) == 4 for i in range(1, 8))
    for t in tasks:
        assert not FORBIDDEN.search(t["instruction"]), t["id"]
        assert set(t) >= {"id", "category", "level", "instruction", "initial_state", "goal_state", "invariants"}
        assert (REF_DIR / f"{t['id']}.json").exists()


def test_goal_states_are_up_to_date_and_ties_fail():
    assert goal_states.main(check_only=True) == 0
    products = load_catalogue()["products"]
    tie = [dict(products[0], id=1, price=1.0), dict(products[0], id=2, price=1.0)]
    with pytest.raises(goal_states.GoalStateError, match="tie"):
        goal_states.solve({"category": products[0]["category"], "objective": "cheapest"}, tie)
    with pytest.raises(goal_states.GoalStateError, match="no product"):
        goal_states.solve({"category": "Mice", "min_rating": 5.0, "objective": "cheapest"}, products)


# ---------------------------------------------------------------- verifier

def test_check_cart_and_orders():
    goal = [{"product_id": 101, "quantity": 2}]
    assert check_cart(goal, [{"product_id": 101, "quantity": 2}]) == []
    assert check_cart(goal, []) == ["cart: missing 101 x2"]
    assert check_cart(goal, [{"product_id": 101, "quantity": 1}]) == ["cart: missing 101 x2", "cart: unexpected 101 x1"]
    assert check_cart([], [{"product_id": 5, "quantity": 1}]) == ["cart: unexpected 5 x1"]
    prices = {101: 19.99}
    order = {"order_id": 1, "lines": [{"product_id": 101, "quantity": 2, "unit_price": 19.99}]}
    assert check_orders([{"lines": goal}], [order], prices) == []
    assert check_orders([], [order], prices) == ["orders: 1 order(s) placed, none expected"]
    assert check_orders([{"lines": goal}], [], prices) == ["orders: 0 order(s) placed, 1 expected"]
    wrong = {"order_id": 1, "lines": [{"product_id": 101, "quantity": 1, "unit_price": 19.99}]}
    assert "order 1: missing 101 x2" in check_orders([{"lines": goal}], [wrong], prices)


def _task(tid):
    return next(t for t in load_tasks([tid]))


def test_verify_success_failure_and_false_completion(client):
    task = _task("C1-01")
    reset.reset(task)
    assert verify(task, S1).as_dict() == {"success": False, "differences": ["cart: missing 101 x1"], "false_completion": True}
    assert verify(task, S2).false_completion is False
    client.post("/api/cart/items", json={"product_id": 101, "quantity": 1})
    assert verify(task, S1).success
    client.post("/api/checkout")                       # order although none was asked for
    r = verify(task, S1)
    assert not r.success and "invariant no_order_created violated" in r.differences


def test_verify_c7_order_and_empty_cart(client):
    task = _task("C7-02")
    reset.reset(task)
    client.post("/api/cart/items", json={"product_id": 201, "quantity": 2})
    assert verify(task, S1).differences == ["cart: unexpected 201 x2", "orders: 0 order(s) placed, 1 expected",
                                            "invariant exactly_one_order violated (0)", "invariant cart_empty violated"]
    client.post("/api/checkout")
    assert verify(task, S1).success


# ---------------------------------------------------------------- end to end with scripted models

def test_tool_pipeline_solves_task_through_the_loop(run_session, tmp_path):
    task = _task("C4-01")
    reset.reset(task)
    steps = json.loads((REF_DIR / "C4-01.json").read_text())["tool"]
    model = FakeModel([reply(s["action"], **s["args"]) for s in steps] + [reply("finish")])
    pipeline = ToolPipeline()
    pipeline.attach(run_session)
    recorder = TraceRecorder(tmp_path / "trace.jsonl")
    result = run_agent(pipeline, model, task["instruction"], LIMITS, MODEL_CONFIG, recorder)
    assert result.termination_reason == S1 and verify(task, S1).success
    assert "No tool has been called yet." in model.prompts[0]
    assert task["instruction"] in model.prompts[0] and "goal_state" not in model.prompts[0]


class DomScriptModel(FakeModel):
    """Finds the ref of a named element in the observation of its prompt (like a perfect model)."""

    def __init__(self, steps):
        super().__init__([])
        self.steps = list(steps)

    def chat(self, prompt, image_b64=None, schema=None):
        if self.steps:
            kind, role, name, *text = self.steps.pop(0)
            observation = prompt[prompt.index("## 5. Current observation"):]
            ref = int(re.search(rf'\[(\d+)\] {role} "{re.escape(name)}"', observation).group(1))
            self.responses = [reply("click", ref=ref) if kind == "click" else reply("type", ref=ref, text=text[0])]
        return super().chat(prompt, image_b64, schema)


def test_dom_pipeline_solves_task_through_the_loop(run_session):
    task = _task("C1-03")
    reset.reset(task)
    model = DomScriptModel([("type", "searchbox", "Search products", "Notebook A5 Dotted"),
                            ("click", "button", "Search"), ("click", "link", "Notebook A5 Dotted"),
                            ("click", "button", "Add to cart")])
    pipeline = DomPipeline()
    pipeline.attach(run_session)
    try:
        result = run_agent(pipeline, model, task["instruction"], LIMITS, MODEL_CONFIG)
    finally:
        pipeline.close()
    assert result.termination_reason == S1 and verify(task, S1).success
    assert '3: click(' in model.prompts[-1] and 'page "Notebook A5 Dotted"' in model.prompts[-1]


# ---------------------------------------------------------------- runner

class FixtureBrowser:
    def __init__(self, browser): self.browser = browser
    def ensure(self): return self.browser


def test_build_runs_shuffled_with_seed():
    plan = {"tasks": ["C1-01", "C2-01"], "pipelines": ["dom", "tool"], "repetitions": 2, "seed": 7}
    a, b = runner.build_runs(plan), runner.build_runs(plan)
    assert [r["run_id"] for r in a] == [r["run_id"] for r in b] and len(a) == 8


def test_execute_run_writes_trace_and_row(shop_db, shop_server, chromium, tmp_path):
    run = {"run_id": "C1-01_dom_r1", "task": _task("C1-01"), "pipeline": "dom", "repetition": 1}
    row = runner.execute_run(run, shop_server, FixtureBrowser(chromium), runner.StubModel(), MODEL_CONFIG, LIMITS,
                             tmp_path, "cfg", retries=1)
    assert row["termination_reason"] == S1 and row["success"] is False and row["false_completion"] is True
    with open(tmp_path / "runs.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == CSV_FIELDS and rows[0]["run_id"] == "C1-01_dom_r1"
    events = [json.loads(l)["event"] for l in (tmp_path / "C1-01_dom_r1" / "trace.jsonl").read_text().splitlines()]
    assert events == ["run_start", "invocation", "action", "run_end"]


def test_s5_is_retried_and_recorded(shop_db, shop_server, tmp_path):
    class Broken:
        def chat(self, prompt, image_b64=None, schema=None): raise ModelError("ollama down")
    run = {"run_id": "C1-01_tool_r1", "task": _task("C1-01"), "pipeline": "tool", "repetition": 1}
    row = runner.execute_run(run, shop_server, None, Broken(), MODEL_CONFIG, LIMITS, tmp_path, "cfg", retries=2)
    assert row["termination_reason"] == S5 and row["attempts"] == 3 and row["success"] == ""


def test_run_experiment_is_resumable(shop_db, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    plan = tmp_path / "plan.yaml"
    plan.write_text("experiment: t\ntasks: [C1-01, C5-01]\npipelines: [tool]\nrepetitions: 2\nseed: 1\n"
                    "infrastructure_retries: 0\nshop_url: null\n")
    exp = runner.run_experiment(plan, stub=True)
    record = json.loads((exp / "config_record.json").read_text())
    assert {"packages", "python", "ollama_version", "model", "hardware", "git_commit", "sha256", "config_id"} <= set(record)
    assert len(record["sha256"]["tasks"]) == 28
    runner.run_experiment(plan, stub=True)
    with open(exp / "runs.csv", newline="") as f:
        assert len(list(csv.DictReader(f))) == 4  # second call skipped all 4 finished runs
