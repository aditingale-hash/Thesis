"""M6: metrics, statistics, plots, auto labels and viewer on synthetic results with known answers."""

import csv
import json
import math

import pytest

from evaluation.analysis import metrics, plots, stats
from evaluation.analysis.load import load_runs
from evaluation.labelling import auto_labels, viewer
from evaluation.trace import CSV_FIELDS

TASKS = [("C1-01", "C1", "simple"), ("C1-02", "C1", "simple"), ("C4-01", "C4", "medium"), ("C7-01", "C7", "complex"),
         ("C5-01", "C5", "medium"), ("C6-01", "C6", "medium")]
# successes out of 3 repetitions per task: tool > dom > visual
SUCCESSES = {"tool": [3, 3, 3, 2, 3, 3], "dom": [3, 2, 1, 1, 2, 2], "visual": [1, 1, 0, 0, 1, 0]}


def _row(run_id, task, pipeline, rep, success, reason, tokens):
    return {"run_id": run_id, "task_id": task[0], "category": task[1], "level": task[2], "pipeline": pipeline,
            "repetition": rep, "success": success, "termination_reason": reason,
            "false_completion": (reason == "S1_finish") and not success, "n_actions": 4, "n_invocations": 5,
            "n_invalid": 1, "n_rejected": 0, "input_tokens": tokens, "output_tokens": 50,
            "execution_time_ms": tokens * 2, "mean_observation_size": 1000, "attempts": 1}


def _trace(exp, run_id, actions, reason):
    lines = [{"event": "run_start", "run_id": run_id, "task_id": "C1-01", "pipeline": "dom", "repetition": 1,
              "config_id": "x"}]
    for step, (name, args, status, message, parse_error) in enumerate(actions, 1):
        lines.append({"event": "invocation", "step": step, "input_tokens": 10, "output_tokens": 5, "duration_ms": 1.0,
                      "raw_response": "{}", "observation_size": 10, "truncated": False, "perception_ms": None})
        lines.append({"event": "action", "step": step, "name": name, "args": args, "status": status,
                      "message": message, "duration_ms": 1.0, "parse_error": parse_error})
    lines.append({"event": "run_end", "termination_reason": reason, "execution_time_ms": 10.0,
                  "verification": {"success": False}, "detail": ""})
    (exp / run_id).mkdir(parents=True, exist_ok=True)
    (exp / run_id / "trace.jsonl").write_text("\n".join(json.dumps(l) for l in lines))


@pytest.fixture
def experiment(tmp_path):
    exp = tmp_path / "exp"
    exp.mkdir()
    rows = []
    for pipeline, successes in SUCCESSES.items():
        base = {"tool": 1000, "dom": 3000, "visual": 6000}[pipeline]
        for t, task in enumerate(TASKS):
            for rep in range(1, 4):
                ok = rep <= successes[t]
                run_id = f"{task[0]}_{pipeline}_r{rep}"
                rows.append(_row(run_id, task, pipeline, rep, ok, "S1_finish" if ok or rep == 3 else "S2_max_invocations",
                                 base + 100 * t + rep))
                if not ok:
                    _trace(exp, run_id, [("click", {"ref": 3}, "executed", "", None)], rows[-1]["termination_reason"])
    rows.append(_row("C1-01_tool_r9", TASKS[0], "tool", 9, "", "S5_infrastructure", 0))  # excluded
    with open(exp / "runs.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return exp


def test_wilson_and_pass_hat_k():
    low, high = metrics.wilson(8, 10)
    assert math.isclose(low, 0.4902, abs_tol=1e-3) and math.isclose(high, 0.9433, abs_tol=1e-3)
    import pandas as pd
    runs = pd.DataFrame({"task_id": ["a"] * 3 + ["b"] * 3, "success": [True, True, False, True, True, True]})
    assert math.isclose(metrics.pass_hat_k(runs, 1), (2 / 3 + 1) / 2)
    assert math.isclose(metrics.pass_hat_k(runs, 2), (1 / 3 + 1) / 2)
    assert math.isclose(metrics.pass_hat_k(runs, 3), (0 + 1) / 2)


def test_metrics_tables(experiment):
    assert metrics.main(str(experiment)) == 0
    import pandas as pd
    by_pipeline = pd.read_csv(experiment / "analysis" / "metrics_by_pipeline.csv").set_index("pipeline")
    assert by_pipeline.loc["tool", "runs"] == 18  # the S5 run is excluded
    assert math.isclose(by_pipeline.loc["tool", "success_rate"], 17 / 18)
    assert math.isclose(by_pipeline.loc["visual", "success_rate"], 3 / 18)
    assert by_pipeline.loc["dom", "success_ci_low"] < by_pipeline.loc["dom", "success_rate"] < by_pipeline.loc["dom", "success_ci_high"]
    assert math.isclose(by_pipeline.loc["tool", "pass^k (k=3)"], 5 / 6)
    for name in ("category", "level"):
        assert (experiment / "analysis" / f"metrics_by_{name}.csv").exists()


def test_stats_friedman_and_holm(experiment):
    assert stats.holm([0.01, 0.04, 0.03]) == [0.03, 0.06, 0.06]
    assert stats.main(str(experiment)) == 0
    import pandas as pd
    friedman = pd.read_csv(experiment / "analysis" / "friedman.csv").set_index("measure")
    assert friedman.loc["tokens_median", "p"] < 0.01 and friedman.loc["success_rate", "p"] < 0.05
    pairs = pd.read_csv(experiment / "analysis" / "wilcoxon_holm.csv")
    assert set(pairs["measure"]) == {"success_rate", "tokens_median", "time_s_median"}
    assert (pairs["p_holm"] >= pairs["p"]).all()


def test_plots_are_written(experiment):
    assert plots.main(str(experiment)) == 0
    for name in ("success_by_pipeline", "success_by_category", "tokens_by_pipeline", "time_by_pipeline"):
        assert (experiment / "analysis" / f"{name}.png").stat().st_size > 10_000


def test_auto_labels_rules_and_merge(experiment):
    exp = experiment
    _trace(exp, "C7-01_visual_r1", [(None, None, "invalid", "not JSON", "unparseable")] * 3, "S3_consecutive_invalid")
    _trace(exp, "C7-01_visual_r2", [("click", {"ref": 99}, "invalid", "There is no element [99] on the current page.", None)] * 3,
           "S3_consecutive_invalid")
    _trace(exp, "C7-01_visual_r3", [("add_to_cart", {"product_id": 1, "quantity": 1}, "rejected", "x", None)] * 3,
           "S2_max_invocations")
    assert auto_labels.label_run(json.loads(f"[{','.join((exp / 'C7-01_visual_r1' / 'trace.jsonl').read_text().splitlines())}]")) == ("G1", 1)
    auto_labels.main(str(exp))
    with open(exp / "labels.csv", newline="") as f:
        labels = {r["run_id"]: r for r in csv.DictReader(f)}
    assert labels["C7-01_visual_r1"]["auto_label"] == "G1"
    assert labels["C7-01_visual_r2"]["auto_label"] == "D2"
    assert labels["C7-01_visual_r3"]["auto_label"] == "G4"
    assert labels["C4-01_visual_r3"]["auto_label"] == "G3"          # finished without success
    assert labels["C4-01_visual_r1"]["auto_label"] == ""            # S2 without a pattern: manual
    # manual labels survive regeneration
    rows = list(labels.values())
    rows[0]["final_label"], rows[0]["note"] = "V2", "clicked next to the button"
    with open(exp / "labels.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=auto_labels.FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    auto_labels.main(str(exp))
    with open(exp / "labels.csv", newline="") as f:
        again = {r["run_id"]: r for r in csv.DictReader(f)}
    assert again[rows[0]["run_id"]]["final_label"] == "V2" and again[rows[0]["run_id"]]["note"]


def test_viewer(experiment):
    (experiment / "C7-01_visual_r2").mkdir(exist_ok=True)
    (experiment / "C7-01_visual_r2" / "step_1.png").write_bytes(b"png")
    text = viewer.show(str(experiment), "C7-01_visual_r2")
    assert "--- step 1" in text and "action: click" in text and "End: S2_max_invocations" in text and "step_1.png" in text
