"""Compute goal states of constraint tasks from catalogue.json.

A task with a ``constraints`` block (C2-C4, and C7-04) names a category, filters and an
objective. The matching product is computed from the catalogue (available products only)
and written into ``goal_state``. Exits with an error if no product or more than one
product is optimal (a tie), so a task can never have two correct answers.

Usage: python -m evaluation.goal_states          # fill goal states in evaluation/tasks/*.json
       python -m evaluation.goal_states --check  # only check, do not write
"""

import json
import sys
from pathlib import Path

from shop.build_db import load_catalogue

TASK_DIR = Path(__file__).resolve().parent / "tasks"

FILTERS = {
    "min_rating": lambda p, v: p["rating"] >= v,          # "a rating of at least v"
    "max_price": lambda p, v: p["price"] <= v,            # "a price of at most v"
    "price_below": lambda p, v: p["price"] < v,           # "costs less than v"
    "price_above": lambda p, v: p["price"] > v,           # "costs more than v"
}
OBJECTIVES = {
    "cheapest": lambda p: p["price"],
    "most_expensive": lambda p: -p["price"],
    "highest_rated": lambda p: -p["rating"],
}


class GoalStateError(Exception):
    pass


def solve(constraints: dict, products: list[dict]) -> dict:
    """Return the single product that satisfies the constraints."""
    candidates = [p for p in products if p["available"] and p["category"] == constraints["category"]]
    for key, value in constraints.items():
        if key in FILTERS:
            candidates = [p for p in candidates if FILTERS[key](p, value)]
    if not candidates:
        raise GoalStateError(f"no product matches {constraints}")
    key = OBJECTIVES[constraints["objective"]]
    best = min(key(p) for p in candidates)
    winners = [p for p in candidates if key(p) == best]
    if len(winners) > 1:
        raise GoalStateError(f"tie between products {[p['id'] for p in winners]} for {constraints}")
    return winners[0]


def goal_state(task: dict, products: list[dict]) -> dict:
    """Goal state for a constraint task: the product in the cart, or in one order for C7."""
    c = task["constraints"]
    line = {"product_id": solve(c, products)["id"], "quantity": c.get("quantity", 1)}
    if task["category"] == "C7":
        return {"cart": [], "orders": [{"lines": [line]}]}
    return {"cart": [line], "orders": []}


def main(check_only: bool = False) -> int:
    products = load_catalogue()["products"]
    errors = 0
    for path in sorted(TASK_DIR.glob("*.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        if "constraints" not in task:
            continue
        try:
            goal = goal_state(task, products)
        except GoalStateError as e:
            print(f"ERROR {task['id']}: {e}")
            errors += 1
            continue
        if task.get("goal_state") != goal:
            if check_only:
                print(f"ERROR {task['id']}: goal_state is {task.get('goal_state')}, expected {goal}")
                errors += 1
                continue
            task["goal_state"] = goal
            path.write_text(json.dumps(task, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"ok    {task['id']}: {goal}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(check_only="--check" in sys.argv))
