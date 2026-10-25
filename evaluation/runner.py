"""Experiment runner.

    python -m evaluation.runner run --plan config/plan.yaml
    python -m evaluation.runner run-one --task C1-01 --pipeline dom

``run``: writes config_record.json, builds all (task x pipeline x repetition) runs, shuffles
them with the plan's seed, makes one warm-up model call (not recorded), then for each run:
reset -> login -> fresh browser context with cookie (or tool HTTP client with cookie) ->
attach -> agent loop (timed) -> verify (unless S5) -> write trace + summary row -> close.
Runs that already have a summary row are skipped (resumable). S5 runs are retried up to
``infrastructure_retries`` times; if they still fail, they are recorded with S5 and excluded
from success rates by the analysis.

``--stub`` replaces the model by a stub that always answers finish: it checks the whole
chain (shop, browser, pipelines, traces, verifier) without Ollama. It is not an experiment.
"""

import argparse
import hashlib
import json
import platform
import random
import subprocess
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from agent.config import CONFIG_DIR, ROOT, load_yaml
from agent.loop import S5, run_agent
from agent.model_client import ModelResponse, OllamaClient
from evaluation.shop_control import ShopServer, prepare_run
from evaluation.trace import TraceRecorder, append_row, completed_run_ids
from evaluation.validate_tasks import TASK_DIR, load_tasks
from evaluation.verifier import verify
from pipelines import PIPELINES, make_pipeline
from shop import build_db, db

RESULTS_DIR = ROOT / "results"
PACKAGES = ["fastapi", "starlette", "jinja2", "itsdangerous", "python-multipart", "uvicorn", "httpx", "playwright",
            "pyyaml", "jsonschema", "pandas", "scipy", "matplotlib", "numpy"]


class StubModel:
    """Always answers finish (plumbing check without Ollama)."""

    config = {"model": "stub"}

    def chat(self, prompt, image_b64=None):
        return ModelResponse('{"thought": "stub", "action": "finish", "args": {}}', 0, 0, 0.0, 0.0)

    def close(self):
        pass


# ---------------------------------------------------------------- configuration record

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _memory_gb() -> float | None:
    try:
        if sys.platform == "win32":
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return round(status.ullTotalPhys / 2**30, 1)
        import os
        return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30, 1)
    except (OSError, ValueError, AttributeError):
        return None


def _command(args: list[str]) -> str | None:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20, cwd=ROOT).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def config_record(model, model_config: dict, plan_path: Path) -> dict:
    """Everything needed to reproduce the experiment (CLAUDE.md 4.6 step 1)."""
    versions = {}
    for package in PACKAGES:
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = None
    if isinstance(model, OllamaClient):
        ollama_version, model_info = model.version(), model.model_info()
    else:
        ollama_version, model_info = None, {"name": "stub", "digest": None, "details": None}
    files = {
        "catalogue": db.CATALOGUE_PATH,
        "prompt_template": ROOT / "agent" / "prompt_template.txt",
        "tool_schemas": ROOT / "pipelines" / "tool_schemas.json",
        "dom_extract": ROOT / "pipelines" / "dom_extract.js",
        "limits": CONFIG_DIR / "limits.yaml",
        "model_config": CONFIG_DIR / "model.yaml",
        "plan": plan_path,
    }
    hashes = {name: sha256(path) for name, path in files.items()}
    hashes["tasks"] = {p.name: sha256(p) for p in sorted(TASK_DIR.glob("*.json"))}
    record = {
        "created": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "packages": versions,
        "ollama_version": ollama_version,
        "model": model_info,
        "model_config": model_config,
        "limits": load_yaml("limits.yaml"),
        "hardware": {
            "platform": platform.platform(),
            "processor": platform.processor() or platform.machine(),
            "ram_gb": _memory_gb(),
            "gpu": _command(["nvidia-smi", "--query-gpu=name,memory.total,driver_version", "--format=csv,noheader"]),
        },
        "git_commit": _command(["git", "rev-parse", "HEAD"]),
        "git_dirty": bool(_command(["git", "status", "--porcelain"])),
        "sha256": hashes,
    }
    record["config_id"] = hashlib.sha256(json.dumps(
        {"sha256": hashes, "model": model_info, "model_config": model_config}, sort_keys=True).encode()).hexdigest()[:12]
    return record


# ---------------------------------------------------------------- runs

def check_ollama(model: OllamaClient) -> None:
    """Stop with a clear message if Ollama is not running or the model is not downloaded."""
    import httpx
    url, name = model.config["ollama_url"], model.config["model"]
    try:
        tags = model.http.get("/api/tags", timeout=10).json().get("models", [])
    except httpx.HTTPError:
        raise SystemExit(f"Ollama is not reachable at {url}. Start Ollama (or run: ollama serve) and try again.")
    if not any(name in (m.get("name"), m.get("model")) for m in tags):
        raise SystemExit(f"The model {name} is not downloaded. Run: ollama pull {name}")


def check_shop(base_url: str) -> None:
    """Stop with a clear message if the separately started shop server is not reachable."""
    import httpx
    try:
        httpx.get(f"{base_url}/", timeout=5).raise_for_status()
    except httpx.HTTPError:
        raise SystemExit(f"The shop is not reachable at {base_url}. Start it first in a second terminal:\n"
                         f"    python -m uvicorn shop.app:app --port 8000")


def build_runs(plan: dict) -> list[dict]:
    """All (task x pipeline x repetition) runs in the plan's seeded random order."""
    tasks = load_tasks(None if plan["tasks"] == "all" else plan["tasks"])
    runs = [{"run_id": f"{t['id']}_{p}_r{r}", "task": t, "pipeline": p, "repetition": r}
            for t in tasks for p in plan["pipelines"] for r in range(1, plan["repetitions"] + 1)]
    random.Random(plan["seed"]).shuffle(runs)
    return runs


class Browser:
    """One Chromium for the experiment; relaunched after a crash."""

    def __init__(self, show: bool = False):
        from playwright.sync_api import sync_playwright
        self.playwright = sync_playwright().start()
        self.browser = None
        self.show = show
        self.ensure()

    def ensure(self):
        if self.browser is None or not self.browser.is_connected():
            # show=True (run-one --show only): visible window, slowed down so a person can follow it
            self.browser = self.playwright.chromium.launch(headless=not self.show, slow_mo=700 if self.show else 0)
        return self.browser

    def close(self):
        if self.browser and self.browser.is_connected():
            self.browser.close()
        self.playwright.stop()


def execute_run(run: dict, base_url: str, browser: Browser | None, model, model_config: dict, limits: dict,
                exp_dir: Path, config_id: str, retries: int) -> dict:
    """One run with S5 retries; returns the summary row (also appended to runs.csv)."""
    run_dir = exp_dir / run["run_id"]
    for attempt in range(1, retries + 2):
        for old in run_dir.glob("step_*.png"):
            old.unlink()
        recorder = TraceRecorder(run_dir / "trace.jsonl", echo=True)
        print(f"run {run['run_id']} (attempt {attempt}) ...", flush=True)
        recorder.run_start(run["run_id"], run["task"]["id"], run["pipeline"], run["repetition"], config_id, attempt)
        pipeline = make_pipeline(run["pipeline"], model_config)
        execution_ms, verification, detail = 0.0, None, ""
        try:
            # setup: outside the timer
            session = prepare_run(run["task"], base_url, browser.ensure() if browser else None, run_dir)
            pipeline.attach(session)
            # the agent loop: the only timed part
            result = run_agent(pipeline, model, run["task"]["instruction"], limits, model_config, recorder)
            reason, execution_ms, detail = result.termination_reason, result.execution_time_ms, result.detail
        except Exception as e:  # setup failed (shop down, browser crash during attach)
            reason, detail = S5, f"setup failed: {e}"
        finally:
            try:
                pipeline.close()
            except Exception:
                pass
        if reason != S5:
            verification = verify(run["task"], reason).as_dict()
        recorder.run_end(reason, execution_ms, verification, detail)
        if reason != S5 or attempt > retries:
            break
        print(f"  {run['run_id']}: infrastructure failure ({detail}), retry {attempt}/{retries}")
    row = recorder.summary_row(run, reason, execution_ms, verification, attempt)
    append_row(exp_dir / "runs.csv", row)
    return row


def run_experiment(plan_path: Path, stub: bool = False, only=None, experiment: str | None = None,
                   show: bool = False) -> Path:
    """Run a plan (or, with ``only``, a list of given runs) and return the experiment directory."""
    plan = load_yaml(plan_path)
    model_config, limits = load_yaml("model.yaml"), load_yaml("limits.yaml")
    exp_dir = RESULTS_DIR / (experiment or plan["experiment"])
    exp_dir.mkdir(parents=True, exist_ok=True)
    model = StubModel() if stub else OllamaClient(model_config)

    if isinstance(model, OllamaClient):
        check_ollama(model)
    record = config_record(model, model_config, Path(plan_path))
    (exp_dir / "config_record.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    runs = only or build_runs(plan)
    done = completed_run_ids(exp_dir / "runs.csv") if only is None else set()
    todo = [r for r in runs if r["run_id"] not in done]
    print(f"{len(runs)} runs, {len(runs) - len(todo)} already done, config {record['config_id']}")

    server = None
    if plan.get("shop_url"):
        base_url = plan["shop_url"]
        check_shop(base_url)
    else:
        if not db.snapshot_path().exists():
            build_db.build()
        server = ShopServer().start()
        base_url = server.url
    model.chat("Reply with a JSON object.")  # warm-up: loads the model, not recorded
    browser = Browser(show) if any(r["pipeline"] != "tool" for r in todo) else None
    try:
        for i, run in enumerate(todo, 1):
            row = execute_run(run, base_url, browser, model, model_config, limits, exp_dir, record["config_id"],
                              plan.get("infrastructure_retries", 0))
            print(f"[{i}/{len(todo)}] {row['run_id']:22} success={row['success']!s:5} {row['termination_reason']:24} "
                  f"actions={row['n_actions']:2} time={row['execution_time_ms'] / 1000:.1f}s")
    finally:
        if browser:
            browser.close()
        if server:
            server.stop()
        model.close()
    return exp_dir


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Experiment runner")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run an experiment plan")
    run.add_argument("--plan", default=str(CONFIG_DIR / "plan.yaml"))
    run.add_argument("--stub", action="store_true", help="model that always answers finish (plumbing check)")
    one = sub.add_parser("run-one", help="run one task in one pipeline (debugging)")
    one.add_argument("--task", required=True)
    one.add_argument("--pipeline", required=True, choices=PIPELINES)
    one.add_argument("--plan", default=str(CONFIG_DIR / "plan.yaml"))
    one.add_argument("--stub", action="store_true")
    one.add_argument("--show", action="store_true",
                     help="show the browser window, slowed down (debugging only; timings are not comparable)")
    args = parser.parse_args(argv)
    try:
        return _run_command(args, parser)
    except KeyboardInterrupt:
        print("\nStopped by you (Ctrl+C). Finished runs are saved; run the same command again to continue.")
        return 130


def _run_command(args, parser) -> int:

    if args.command == "run":
        exp_dir = run_experiment(Path(args.plan), args.stub)
        print(f"results: {exp_dir}")
        return 0
    tasks = load_tasks([args.task])
    if not tasks:
        parser.error(f"unknown task {args.task}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run = {"run_id": f"{args.task}_{args.pipeline}_{stamp}", "task": tasks[0], "pipeline": args.pipeline, "repetition": 1}
    exp_dir = run_experiment(Path(args.plan), args.stub, only=[run], experiment="debug", show=args.show)
    trace = exp_dir / run["run_id"] / "trace.jsonl"
    end = json.loads(trace.read_text(encoding="utf-8").splitlines()[-1])
    from evaluation.labelling.viewer import show as show_run
    print("\n" + show_run(str(exp_dir), run["run_id"]) + "\n")
    print(f"trace: {trace}")
    print(f"termination: {end['termination_reason']}  verification: {json.dumps(end['verification'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
