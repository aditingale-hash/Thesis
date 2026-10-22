"""M4 acceptance: every reference solution succeeds in all three pipelines with fewer actions than S2."""

from agent.config import load_yaml
from evaluation.validate_tasks import validate


def test_all_reference_solutions_pass(shop_db, shop_server, chromium):
    limit = load_yaml("limits.yaml")["max_invocations"]
    results = validate(base_url=shop_server, browser=chromium)
    assert len(results) == 84
    failures = [r for r in results if not r["success"] or r["actions"] + 1 >= limit]
    assert not failures, failures
