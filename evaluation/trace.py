"""Trace recorder: one JSON Lines file per run plus one summary row per run in runs.csv.

Events: run_start, invocation, action, run_end (see CLAUDE.md 4.5).
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from pipelines.base import INVALID, REJECTED

CSV_FIELDS = ["run_id", "task_id", "category", "level", "pipeline", "repetition", "success", "termination_reason",
              "false_completion", "n_actions", "n_invocations", "n_invalid", "n_rejected", "input_tokens",
              "output_tokens", "execution_time_ms", "mean_observation_size", "attempts"]


class TraceRecorder:
    """Writes the events of one run and counts what the summary row needs."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.file = open(path, "w", encoding="utf-8")
        self.n_invocations = self.n_actions = self.n_invalid = self.n_rejected = 0
        self.input_tokens = self.output_tokens = 0
        self.observation_sizes: list[int] = []

    def _write(self, event: str, **data) -> None:
        self.file.write(json.dumps({"event": event, **data}, ensure_ascii=False) + "\n")
        self.file.flush()

    def run_start(self, run_id, task_id, pipeline, repetition, config_id, attempt=1) -> None:
        self._write("run_start", run_id=run_id, task_id=task_id, pipeline=pipeline, repetition=repetition,
                    config_id=config_id, attempt=attempt, timestamp=datetime.now(timezone.utc).isoformat())

    def invocation(self, step, input_tokens, output_tokens, duration_ms, raw_response, observation_size,
                   truncated, perception_ms=None) -> None:
        self.n_invocations += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.observation_sizes.append(observation_size)
        self._write("invocation", step=step, input_tokens=input_tokens, output_tokens=output_tokens,
                    duration_ms=round(duration_ms, 1), raw_response=raw_response, observation_size=observation_size,
                    truncated=truncated, perception_ms=perception_ms)

    def action(self, step, name, args, status, message, duration_ms, parse_error=None) -> None:
        """One action event; name None = the response could not be parsed (no action executed)."""
        if name is not None and name != "finish":
            self.n_actions += 1
        self.n_invalid += status == INVALID
        self.n_rejected += status == REJECTED
        self._write("action", step=step, name=name, args=args, status=status, message=message,
                    duration_ms=round(duration_ms, 1), parse_error=parse_error)

    def run_end(self, termination_reason, execution_time_ms, verification: dict | None, detail="") -> None:
        self._write("run_end", termination_reason=termination_reason, execution_time_ms=round(execution_time_ms, 1),
                    verification=verification, detail=detail)
        self.file.close()

    def summary_row(self, run: dict, termination_reason: str, execution_time_ms: float, verification: dict | None,
                    attempts: int) -> dict:
        sizes = self.observation_sizes
        return {
            "run_id": run["run_id"], "task_id": run["task"]["id"], "category": run["task"]["category"],
            "level": run["task"]["level"], "pipeline": run["pipeline"], "repetition": run["repetition"],
            "success": "" if verification is None else verification["success"],
            "termination_reason": termination_reason,
            "false_completion": "" if verification is None else verification["false_completion"],
            "n_actions": self.n_actions, "n_invocations": self.n_invocations, "n_invalid": self.n_invalid,
            "n_rejected": self.n_rejected, "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "execution_time_ms": round(execution_time_ms, 1),
            "mean_observation_size": round(sum(sizes) / len(sizes), 1) if sizes else 0, "attempts": attempts,
        }


def append_row(csv_path: Path, row: dict) -> None:
    new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def completed_run_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        return {row["run_id"] for row in csv.DictReader(f)}
