"""Automatic failure labels for failed runs (first pass before manual labelling).

Rules (first match wins, in this order):
- G1 unparseable response: the run ended by S3 and most invalid steps were unparseable responses
- D2 invalid reference: the run ended by S3 and most invalid steps referred to an element that
  does not exist on the current page (DOM pipeline)
- G4 repeated identical state-changing action: the same state-changing tool call, or the same
  browser click/type, three times in a row
- G3 false completion: the agent issued finish but the task was not solved
Runs that match no rule get an empty auto_label and must be labelled manually
(full taxonomy G1-G5, T1-T2, D1-D3, V1-V4).

Writes results/<experiment>/labels.csv (run_id, auto_label, final_label, first_failing_step, note).
Existing final_label and note values are kept when the file is regenerated.

Usage: python -m evaluation.labelling.auto_labels results/<experiment>
"""

import csv
import sys
from pathlib import Path

from evaluation.analysis.load import load_runs, load_trace

STATE_CHANGING_TOOLS = {"add_to_cart", "update_cart_item", "remove_from_cart", "checkout"}
REPEAT = 3
FIELDS = ["run_id", "auto_label", "final_label", "first_failing_step", "note"]


def label_run(events: list[dict]) -> tuple[str, int | None]:
    """Return (auto_label, first_failing_step) for one failed run."""
    end = next(e for e in events if e["event"] == "run_end")
    actions = [e for e in events if e["event"] == "action"]
    invalid = [a for a in actions if a["status"] == "invalid"]
    if end["termination_reason"] == "S3_consecutive_invalid" and invalid:
        unparseable = [a for a in invalid if a.get("parse_error") == "unparseable"]
        bad_refs = [a for a in invalid if a["name"] is not None and "There is no element" in (a["message"] or "")]
        if len(unparseable) * 2 >= len(invalid):
            return "G1", unparseable[0]["step"]
        if len(bad_refs) * 2 >= len(invalid):
            return "D2", bad_refs[0]["step"]
    run, previous = 0, None
    for a in actions:
        key = (a["name"], repr(a["args"]))
        state_changing = a["name"] in STATE_CHANGING_TOOLS or a["name"] in ("click", "type")
        run = run + 1 if key == previous and state_changing else 1
        previous = key
        if run >= REPEAT:
            return "G4", a["step"] - REPEAT + 1
    if end["termination_reason"] == "S1_finish":
        return "G3", actions[-1]["step"] if actions else None
    return "", None


def main(exp_dir: str) -> int:
    exp = Path(exp_dir)
    runs = load_runs(exp)
    failed = runs[runs["success"] == False]  # noqa: E712 (NaN-safe comparison)
    path = exp / "labels.csv"
    existing = {}
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            existing = {r["run_id"]: r for r in csv.DictReader(f)}
    rows = []
    for run_id in failed["run_id"]:
        label, step = label_run(load_trace(exp, run_id))
        old = existing.get(run_id, {})
        rows.append({"run_id": run_id, "auto_label": label, "final_label": old.get("final_label") or label,
                     "first_failing_step": "" if step is None else step, "note": old.get("note", "")})
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["auto_label"] or "(manual)"] = counts.get(r["auto_label"] or "(manual)", 0) + 1
    print(f"{len(rows)} failed runs labelled: {counts} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
