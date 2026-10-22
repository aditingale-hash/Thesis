"""Inferential statistics on per-task values.

Per task and pipeline: success rate (over repetitions) and medians of tokens and time.
Friedman test across the three pipelines (tasks as blocks), then pairwise Wilcoxon
signed-rank tests with Holm correction.

Usage: python -m evaluation.analysis.stats results/<experiment>
"""

import itertools
import sys
import warnings
from pathlib import Path

import pandas as pd
from scipy import stats

from evaluation.analysis.load import load_runs

MEASURES = {"success_rate": ("success", "mean"), "tokens_median": ("total_tokens", "median"),
            "time_s_median": ("execution_time_s", "median")}


def per_task(df: pd.DataFrame) -> pd.DataFrame:
    """One row per task and pipeline."""
    table = df.groupby(["task_id", "pipeline"]).agg(**{m: spec for m, spec in MEASURES.items()}).reset_index()
    table[list(MEASURES)] = table[list(MEASURES)].astype(float)
    return table


def holm(p_values: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values (same order as given)."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def test_measure(table: pd.DataFrame, measure: str) -> tuple[dict, pd.DataFrame]:
    """Friedman + pairwise Wilcoxon (Holm) for one per-task measure."""
    wide = table.pivot(index="task_id", columns="pipeline", values=measure).dropna()
    pipelines = list(wide.columns)
    friedman = {"measure": measure, "tasks": len(wide), "statistic": float("nan"), "p": float("nan")}
    if len(pipelines) >= 3 and len(wide) >= 2:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            res = stats.friedmanchisquare(*[wide[p] for p in pipelines])
        friedman.update(statistic=float(res.statistic), p=float(res.pvalue))
    rows = []
    for a, b in itertools.combinations(pipelines, 2):
        diff = wide[a] - wide[b]
        if (diff == 0).all():
            stat, p = 0.0, 1.0           # identical on every task: no evidence of a difference
        else:
            res = stats.wilcoxon(wide[a], wide[b], zero_method="wilcox")
            stat, p = float(res.statistic), float(res.pvalue)
        rows.append({"measure": measure, "a": a, "b": b, "median_a": wide[a].median(), "median_b": wide[b].median(),
                     "W": stat, "p": p})
    pairs = pd.DataFrame(rows)
    if not pairs.empty:
        pairs["p_holm"] = holm(list(pairs["p"]))
    return friedman, pairs


def main(exp_dir: str) -> int:
    exp = Path(exp_dir)
    table = per_task(load_runs(exp))
    out = exp / "analysis"
    out.mkdir(exist_ok=True)
    table.to_csv(out / "per_task.csv", index=False)
    friedmans, pairs = [], []
    for measure in MEASURES:
        f, p = test_measure(table, measure)
        friedmans.append(f)
        pairs.append(p)
    friedman_df, pairs_df = pd.DataFrame(friedmans), pd.concat(pairs, ignore_index=True)
    friedman_df.to_csv(out / "friedman.csv", index=False)
    pairs_df.to_csv(out / "wilcoxon_holm.csv", index=False)
    print("Friedman test (tasks as blocks):")
    print(friedman_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    print("\nPairwise Wilcoxon signed-rank, Holm-corrected:")
    print(pairs_df.to_string(index=False, float_format=lambda v: f"{v:.4f}"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
