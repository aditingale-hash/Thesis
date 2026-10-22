"""Metrics per pipeline, category, level and pipeline x category.

Usage: python -m evaluation.analysis.metrics results/<experiment>
Writes results/<experiment>/analysis/metrics_by_<group>.csv and prints the pipeline table.
S5 runs (infrastructure failures) are excluded from all rates and reported separately.
"""

import math
import sys
from pathlib import Path

import pandas as pd

from evaluation.analysis.load import S5, load_runs, perception_ms

GROUPS = {"pipeline": ["pipeline"], "category": ["pipeline", "category"], "level": ["pipeline", "level"]}


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% confidence interval for a proportion."""
    if n == 0:
        return float("nan"), float("nan")
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def pass_hat_k(df: pd.DataFrame, k: int) -> float:
    """pass^k: probability that k independent repetitions of a task all succeed, averaged over tasks
    (unbiased estimator C(c, k) / C(n, k) per task, c successes of n repetitions)."""
    values = []
    for _, runs in df.groupby("task_id"):
        n, c = len(runs), int(runs["success"].sum())
        if n >= k:
            values.append(math.comb(c, k) / math.comb(n, k))
    return sum(values) / len(values) if values else float("nan")


def _median_iqr(series: pd.Series) -> tuple[float, float]:
    if series.empty:
        return float("nan"), float("nan")
    return float(series.median()), float(series.quantile(0.75) - series.quantile(0.25))


def summarise(df: pd.DataFrame) -> dict:
    """All metrics of CLAUDE.md 4.5 for one group of runs."""
    n, successes = len(df), int(df["success"].sum())
    low, high = wilson(successes, n)
    ok = df[df["success"]]
    row = {"runs": n, "successes": successes, "success_rate": successes / n if n else float("nan"),
           "success_ci_low": low, "success_ci_high": high}
    for name, col in (("actions", "n_actions"), ("invocations", "n_invocations"),
                      ("time_s", "execution_time_s"), ("tokens", "total_tokens")):
        row[f"{name}_median"], row[f"{name}_iqr"] = _median_iqr(df[col])
        row[f"{name}_median_success"], row[f"{name}_iqr_success"] = _median_iqr(ok[col])
    invocations, actions = df["n_invocations"].sum(), df["n_actions"].sum()
    row["invalid_rate"] = df["n_invalid"].sum() / invocations if invocations else float("nan")
    row["rejected_rate"] = df["n_rejected"].sum() / actions if actions else float("nan")
    row["false_completion_rate"] = df["false_completion"].mean() if n else float("nan")
    row["step_limit_rate"] = df["step_limit"].mean() if n else float("nan")
    reps = int(df.groupby("task_id").size().min()) if n else 0
    row["pass^1"] = pass_hat_k(df, 1)
    row[f"pass^k (k={reps})"] = pass_hat_k(df, reps) if reps else float("nan")
    row["mean_observation_size"] = df["mean_observation_size"].mean()
    row["perception_ms_mean"] = df["perception_ms"].mean() if "perception_ms" in df else float("nan")
    return row


def metrics(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    rows = []
    for key, group in df.groupby(by, sort=True):
        key = key if isinstance(key, tuple) else (key,)
        rows.append({**dict(zip(by, key)), **summarise(group)})
    return pd.DataFrame(rows)


def main(exp_dir: str) -> int:
    exp = Path(exp_dir)
    all_runs = load_runs(exp, include_s5=True)
    df = load_runs(exp)
    df = df.join(perception_ms(exp, df["run_id"]), on="run_id")
    out = exp / "analysis"
    out.mkdir(exist_ok=True)
    for name, by in GROUPS.items():
        metrics(df, by).to_csv(out / f"metrics_by_{name}.csv", index=False)
    s5 = all_runs[all_runs["termination_reason"] == S5].groupby("pipeline").size()
    print(f"Excluded infrastructure failures (S5): {dict(s5) if len(s5) else 0}")
    table = metrics(df, ["pipeline"])
    cols = ["pipeline", "runs", "success_rate", "success_ci_low", "success_ci_high", "actions_median",
            "tokens_median", "time_s_median", "invalid_rate", "rejected_rate", "false_completion_rate", "step_limit_rate"]
    print(table[cols].to_string(index=False, float_format=lambda v: f"{v:.3f}"))
    print(f"tables written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
