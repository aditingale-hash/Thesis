"""Plots for the thesis.

- success rate per pipeline (bars with Wilson 95% CI) and per task category (grouped bars)
- total tokens and execution time per pipeline (box plots)
Colours follow the pipeline (same colour in every figure); values are labelled on the bars.

Usage: python -m evaluation.analysis.plots results/<experiment>
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from evaluation.analysis.load import load_runs  # noqa: E402
from evaluation.analysis.metrics import metrics  # noqa: E402

# Validated categorical palette (blue, orange, aqua), fixed per pipeline.
COLORS = {"dom": "#2a78d6", "visual": "#eb6834", "tool": "#1baf7a"}
ORDER = ["dom", "visual", "tool"]
INK, MUTED, GRID = "#1f1f1e", "#5f5e58", "#e4e3de"


def _style(ax, ylabel: str) -> None:
    ax.set_ylabel(ylabel, color=INK)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=MUTED)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def success_by_pipeline(df, path: Path) -> None:
    m = metrics(df, ["pipeline"]).set_index("pipeline").reindex([p for p in ORDER if p in set(df["pipeline"])])
    fig, ax = plt.subplots(figsize=(5, 3.6))
    x = range(len(m))
    err = [m["success_rate"] - m["success_ci_low"], m["success_ci_high"] - m["success_rate"]]
    bars = ax.bar(x, m["success_rate"], width=0.55, color=[COLORS[p] for p in m.index],
                  yerr=err, capsize=4, error_kw={"ecolor": MUTED, "elinewidth": 1})
    for bar, rate, high, n in zip(bars, m["success_rate"], m["success_ci_high"], m["runs"]):
        ax.text(bar.get_x() + bar.get_width() / 2, high + 0.02, f"{rate:.0%} (n={n})", ha="center", va="bottom",
                color=INK, fontsize=9)
    ax.set_xticks(list(x), m.index)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    _style(ax, "Success rate (95% Wilson CI)")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def success_by_category(df, path: Path) -> None:
    m = metrics(df, ["pipeline", "category"])
    pipelines = [p for p in ORDER if p in set(df["pipeline"])]
    categories = sorted(df["category"].unique())
    width = 0.8 / len(pipelines)
    fig, ax = plt.subplots(figsize=(8, 3.8))
    for i, p in enumerate(pipelines):
        rows = m[m["pipeline"] == p].set_index("category").reindex(categories)
        xs = [c + (i - (len(pipelines) - 1) / 2) * width for c in range(len(categories))]
        ax.bar(xs, rows["success_rate"], width=width - 0.03, color=COLORS[p], label=p)
        for x, v in zip(xs, rows["success_rate"]):
            if v == v:
                ax.text(x, v + 0.02, f"{v:.0%}", ha="center", va="bottom", fontsize=7, color=MUTED)
    ax.set_xticks(range(len(categories)), categories)
    ax.set_ylim(0, 1.1)
    ax.set_yticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.legend(frameon=False, ncol=len(pipelines), loc="lower right", bbox_to_anchor=(1.0, 1.0))
    _style(ax, "Success rate")
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def box_by_pipeline(df, column: str, ylabel: str, path: Path) -> None:
    pipelines = [p for p in ORDER if p in set(df["pipeline"])]
    fig, ax = plt.subplots(figsize=(5, 3.6))
    data = [df.loc[df["pipeline"] == p, column] for p in pipelines]
    box = ax.boxplot(data, patch_artist=True, widths=0.5, medianprops={"color": INK, "linewidth": 1.5},
                     whiskerprops={"color": MUTED}, capprops={"color": MUTED},
                     flierprops={"markerfacecolor": MUTED, "markeredgecolor": "none", "markersize": 4})
    for patch, p in zip(box["boxes"], pipelines):
        patch.set_facecolor(COLORS[p])
        patch.set_edgecolor(COLORS[p])
    for i, values in enumerate(data, 1):
        if len(values):
            ax.text(i + 0.3, values.median(), f"{values.median():,.0f}", va="center", fontsize=8, color=INK)
    ax.set_xticks(range(1, len(pipelines) + 1), pipelines)
    _style(ax, ylabel)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def main(exp_dir: str) -> int:
    exp = Path(exp_dir)
    df = load_runs(exp)
    out = exp / "analysis"
    out.mkdir(exist_ok=True)
    success_by_pipeline(df, out / "success_by_pipeline.png")
    success_by_category(df, out / "success_by_category.png")
    box_by_pipeline(df, "total_tokens", "Total tokens per run", out / "tokens_by_pipeline.png")
    box_by_pipeline(df, "execution_time_s", "Execution time per run (s)", out / "time_by_pipeline.png")
    print(f"plots written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
