"""Run every reference solution through the pipeline interfaces WITHOUT the model.

For each task and pipeline: reset -> login -> attach -> execute the reference actions
(observing before every action, like the agent loop) -> verify. All must succeed with
fewer actions than S2 (max_invocations; the final finish counts as one invocation).

DOM and visual share one browser script per task ("browser" in reference_solutions/<task>.json),
compiled at run time into the pipeline's own actions: the target element is found with
Playwright to read its [ref] (DOM) or its position on screen (visual, with scroll actions
if it is outside the viewport). This reads the browser and is allowed for validation only.

Usage: python -m evaluation.validate_tasks [--tasks C1-01 C4-02] [--pipelines dom tool]
"""

import argparse
import json
import sys
from pathlib import Path

from agent.config import load_yaml
from agent.loop import S1
from evaluation.shop_control import ShopServer, prepare_run
from evaluation.verifier import verify
from pipelines import PIPELINES, make_pipeline
from pipelines.base import EXECUTED, Action
from shop import build_db, db

EVAL_DIR = Path(__file__).resolve().parent
TASK_DIR, REF_DIR = EVAL_DIR / "tasks", EVAL_DIR / "reference_solutions"


def load_tasks(ids=None) -> list[dict]:
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(TASK_DIR.glob("*.json"))]
    return [t for t in tasks if not ids or t["id"] in ids]


def _locate(page, target: dict):
    if "css" in target:
        return page.locator(target["css"]).first
    return page.get_by_role(target["role"], name=target["name"], exact=True).nth(target.get("nth", 0))


def compile_browser_step(pipeline, step: dict) -> list[Action]:
    """Turn one browser step into pipeline actions for the CURRENT page state.

    Visual steps may need scrolling first; scroll actions are executed here directly and
    returned too, so they are counted.
    """
    kind, target = next(iter(step.items()))
    element = _locate(pipeline.page, target)
    element.wait_for(state="attached", timeout=5000)
    if pipeline.name == "dom":
        ref = int(element.get_attribute("data-agent-ref").split(":")[1])
        return [Action("click", {"ref": ref})] if kind == "click" else [Action("type", {"ref": ref, "text": target["text"]})]
    scrolls = []
    box = element.bounding_box()
    while box["y"] < 0 or box["y"] + box["height"] > 800:
        direction = "down" if box["y"] + box["height"] > 800 else "up"
        scrolls.append(Action("scroll", {"direction": direction}))
        pipeline.execute(scrolls[-1])
        pipeline.observe()
        box = element.bounding_box()
    x, y = round(box["x"] + box["width"] / 2), round(box["y"] + box["height"] / 2)
    if kind == "click":
        return scrolls + [Action("click", {"x": x, "y": y})]
    return scrolls + [Action("type", {"x": x, "y": y, "text": target["text"]})]


def run_reference(task: dict, pipeline_name: str, base_url: str, browser, model_config: dict) -> dict:
    """Execute one reference solution; return outcome and action count."""
    ref = json.loads((REF_DIR / f"{task['id']}.json").read_text(encoding="utf-8"))
    session = prepare_run(task, base_url, browser)
    pipeline = make_pipeline(pipeline_name, model_config)
    pipeline.attach(session)
    n_actions, problems = 0, []
    try:
        if pipeline_name == "tool":
            for step in ref["tool"]:
                pipeline.observe()
                r = pipeline.execute(Action(step["action"], step["args"]))
                n_actions += 1
                if r.status != EXECUTED:
                    problems.append(f"{step['action']}: {r.status} {r.message}")
        else:
            for step in ref["browser"]:
                pipeline.observe()
                try:
                    actions = compile_browser_step(pipeline, step)
                except Exception as e:  # target not on the page: the solution went wrong earlier
                    problems.append(f"step {step}: {str(e).splitlines()[0]} (page: {pipeline.page.url})")
                    break
                n_actions += sum(a.name == "scroll" for a in actions)
                for action in (a for a in actions if a.name != "scroll"):
                    r = pipeline.execute(action)
                    n_actions += 1
                    if r.status != EXECUTED:
                        problems.append(f"{action.name}{action.args}: {r.status} {r.message or r.detail}")
                    pipeline.observe()
    finally:
        pipeline.close()
    result = verify(task, S1)
    return {"task": task["id"], "pipeline": pipeline_name, "actions": n_actions,
            "success": result.success and not problems, "problems": problems + result.differences}


def validate(task_ids=None, pipelines=PIPELINES, base_url=None, browser=None) -> list[dict]:
    """Validate the reference solutions; starts the shop and Chromium if not given."""
    model_config = load_yaml("model.yaml")
    server = playwright = None
    if base_url is None:
        if not db.snapshot_path().exists():
            build_db.build()
        server = ShopServer().start()
        base_url = server.url
    if browser is None and any(p != "tool" for p in pipelines):
        from playwright.sync_api import sync_playwright
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch()
    try:
        return [run_reference(t, p, base_url, browser, model_config) for t in load_tasks(task_ids) for p in pipelines]
    finally:
        if playwright:
            browser.close()
            playwright.stop()
        if server:
            server.stop()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tasks", nargs="*")
    parser.add_argument("--pipelines", nargs="*", default=list(PIPELINES))
    args = parser.parse_args()
    limit = load_yaml("limits.yaml")["max_invocations"]
    results = validate(args.tasks, args.pipelines)
    failed = 0
    for r in results:
        ok = r["success"] and r["actions"] + 1 < limit
        failed += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {r['task']:6} {r['pipeline']:6} actions={r['actions']:2}  {'; '.join(r['problems'])}")
    print(f"{len(results) - failed}/{len(results)} reference solutions succeed with fewer than {limit} invocations")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
