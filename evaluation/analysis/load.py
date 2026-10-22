"""Load runs.csv and the traces of an experiment."""

import json
from pathlib import Path

import pandas as pd

S5 = "S5_infrastructure"
STEP_LIMITS = {"S2_max_invocations", "S3_consecutive_invalid", "S4_timeout"}


def load_runs(exp_dir: Path, include_s5: bool = False) -> pd.DataFrame:
    """runs.csv as a DataFrame with typed columns; S5 runs are excluded unless asked for."""
    df = pd.read_csv(Path(exp_dir) / "runs.csv", dtype={"success": str, "false_completion": str})
    for col in ("success", "false_completion"):
        df[col] = df[col].map({"True": True, "False": False})
    df["total_tokens"] = df["input_tokens"] + df["output_tokens"]
    df["execution_time_s"] = df["execution_time_ms"] / 1000
    df["step_limit"] = df["termination_reason"].isin(STEP_LIMITS)
    if not include_s5:
        df = df[df["termination_reason"] != S5].copy()
        df[["success", "false_completion"]] = df[["success", "false_completion"]].astype(bool)
    return df


def load_trace(exp_dir: Path, run_id: str) -> list[dict]:
    path = Path(exp_dir) / run_id / "trace.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def perception_ms(exp_dir: Path, run_ids) -> pd.Series:
    """Mean perception time per run from the traces (NaN when no perception component was used)."""
    values = {}
    for run_id in run_ids:
        if not (Path(exp_dir) / run_id / "trace.jsonl").exists():
            values[run_id] = float("nan")
            continue
        times = [e["perception_ms"] for e in load_trace(exp_dir, run_id)
                 if e["event"] == "invocation" and e.get("perception_ms") is not None]
        values[run_id] = sum(times) / len(times) if times else float("nan")
    return pd.Series(values, name="perception_ms")
