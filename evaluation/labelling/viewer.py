"""Print one run step by step and list its screenshots (for manual failure labelling).

Usage: python -m evaluation.labelling.viewer results/<experiment> <run_id>
"""

import json
import sys
import textwrap
from pathlib import Path

from agent.config import ROOT
from evaluation.analysis.load import load_trace


def show(exp_dir: str, run_id: str) -> str:
    exp = Path(exp_dir)
    lines = []
    for e in load_trace(exp, run_id):
        if e["event"] == "run_start":
            lines.append(f"Run {e['run_id']}  task {e['task_id']}  pipeline {e['pipeline']}  "
                         f"repetition {e['repetition']}  attempt {e.get('attempt', 1)}  config {e['config_id']}")
            task = ROOT / "evaluation" / "tasks" / f"{e['task_id']}.json"
            if task.exists():
                lines.append(f"Task: {json.loads(task.read_text(encoding='utf-8'))['instruction']}")
        elif e["event"] == "invocation":
            lines.append(f"\n--- step {e['step']}  tokens in/out {e['input_tokens']}/{e['output_tokens']}  "
                         f"{e['duration_ms']:.0f} ms  observation {e['observation_size']}"
                         f"{'  TRUNCATED' if e['truncated'] else ''}")
            lines.append(textwrap.indent(e["raw_response"], "  model: "))
        elif e["event"] == "action":
            name = e["name"] or "(no action: invalid response)"
            lines.append(f"  action: {name} {json.dumps(e['args']) if e['args'] else ''} -> {e['status']}"
                         f"{': ' + e['message'] if e['message'] else ''}")
        elif e["event"] == "run_end":
            lines.append(f"\nEnd: {e['termination_reason']}  {e['execution_time_ms'] / 1000:.1f} s  "
                         f"verification: {json.dumps(e['verification'])}  {e.get('detail') or ''}")
    shots = sorted((exp / run_id).glob("step_*.png"), key=lambda p: int(p.stem.split("_")[1]))
    if shots:
        lines.append("Screenshots:\n" + "\n".join(f"  {p}" for p in shots))
    return "\n".join(lines)


if __name__ == "__main__":
    print(show(sys.argv[1], sys.argv[2]))
