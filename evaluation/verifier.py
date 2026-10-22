"""Verifier: decides task success from the shop state only (read-only, never seen by the agent).

- cart check: the set of (product_id, quantity) in the cart equals the goal cart
- order check: C7 -> exactly one new order with the expected lines (and current prices);
  other tasks -> no order
- invariant checks from the task file
``false_completion`` = the agent issued finish (S1) but the task is not solved.
"""

from dataclasses import dataclass, field

from agent.loop import S1
from shop import state_reader
from shop.build_db import load_catalogue


@dataclass
class VerificationResult:
    success: bool
    differences: list[str] = field(default_factory=list)
    false_completion: bool = False

    def as_dict(self) -> dict:
        return {"success": self.success, "differences": self.differences, "false_completion": self.false_completion}


def _lines(items) -> set[tuple[int, int]]:
    return {(i["product_id"], i["quantity"]) for i in items}


def check_cart(goal_cart: list[dict], cart: list[dict]) -> list[str]:
    """Differences between the goal cart and the actual cart (as sets of (product_id, quantity))."""
    goal, actual = _lines(goal_cart), _lines(cart)
    diffs = [f"cart: missing {pid} x{q}" for pid, q in sorted(goal - actual)]
    diffs += [f"cart: unexpected {pid} x{q}" for pid, q in sorted(actual - goal)]
    return diffs


def check_orders(goal_orders: list[dict], orders: list[dict], prices: dict[int, float]) -> list[str]:
    """Differences between the expected orders and the orders placed during the run."""
    if not goal_orders:
        return [f"orders: {len(orders)} order(s) placed, none expected"] if orders else []
    if len(orders) != len(goal_orders):
        return [f"orders: {len(orders)} order(s) placed, {len(goal_orders)} expected"]
    diffs = []
    for expected, actual in zip(goal_orders, orders):
        diffs += [d.replace("cart:", f"order {actual['order_id']}:") for d in check_cart(expected["lines"], actual["lines"])]
        for line in actual["lines"]:
            if line["unit_price"] != prices[line["product_id"]]:
                diffs.append(f"order {actual['order_id']}: unit price of {line['product_id']} is {line['unit_price']}")
    return diffs


def check_invariants(invariants: list[str], cart: list[dict], orders: list[dict]) -> list[str]:
    checks = {
        "no_order_created": lambda: [] if not orders else ["invariant no_order_created violated"],
        "exactly_one_order": lambda: [] if len(orders) == 1 else [f"invariant exactly_one_order violated ({len(orders)})"],
        "cart_empty": lambda: [] if not cart else ["invariant cart_empty violated"],
    }
    diffs = []
    for name in invariants:
        diffs += checks[name]()
    return diffs


def verify(task: dict, termination_reason: str, db_path=None) -> VerificationResult:
    """Compare the shop state after a run with the task's goal state."""
    cart = state_reader.cart_items(path=db_path)
    orders = state_reader.orders(path=db_path)
    prices = {p["id"]: p["price"] for p in load_catalogue()["products"]}
    goal = task["goal_state"]
    differences = check_cart(goal["cart"], cart)
    differences += check_orders(goal["orders"], orders, prices)
    differences += check_invariants(task.get("invariants", []), cart, orders)
    success = not differences
    return VerificationResult(success, differences, termination_reason == S1 and not success)
