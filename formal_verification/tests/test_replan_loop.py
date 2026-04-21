"""
Smoke-test the replan loop + spec_proposer without calling any real LLM.

Run with:  python tests/test_replan_loop.py
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from replan_loop import run_verified_loop
from baseline_nl_critique import run_nl_critique_loop
from spec_proposer import (
    MockLLM, build_proposer_prompt, parse_and_compile_proposals,
    validate_checks, propose_and_validate,
)


# ── test 1: replan loop converges when planner fixes the bug on retry ─────────

BROKEN_PLAN = '''
stores = ["http://localhost:8081/", "http://localhost:8082/", "http://localhost:8083/", "http://localhost:8084/"]
results = []
for store in stores:
    url = search_on_page(store, "Widget")
    if url is not None:
        results.append(url)
# BUG: never opens solution page, never fills, never submits
'''.strip()

FIXED_PLAN = '''
stores = ["http://localhost:8081/", "http://localhost:8082/", "http://localhost:8083/", "http://localhost:8084/"]
results = []
for store in stores:
    url = search_on_page(store, "Widget")
    if url is not None:
        results.append(url)
final = "###".join(results) if results else "Done"
open_page("http://localhost:8085/")
fill_text_field("Type your final answer here...", final)
press_button("Submit Final Result")
'''.strip()


def make_healing_planner(broken, fixed):
    """Returns broken on first call, fixed thereafter."""
    state = {"calls": 0}
    def planner(task_prompt, previous_plan=None, feedback=None):
        state["calls"] += 1
        return broken if state["calls"] == 1 else fixed
    return planner, state


def test_replan_converges():
    planner, state = make_healing_planner(BROKEN_PLAN, FIXED_PLAN)
    result = run_verified_loop(
        task_prompt="Find all Widget offers across the four shops.",
        planner=planner,
        max_iterations=3,
        expected_stores=["http://localhost:8081", "http://localhost:8082",
                         "http://localhost:8083", "http://localhost:8084"],
    )
    assert result.converged, f"expected convergence; got iterations={len(result.iterations)} trace: {[ (it.iteration, [r['name'] for r in it.property_results if not r['passed']]) for it in result.iterations]}"
    assert len(result.iterations) == 2, f"expected 2 iterations (broken → fix); got {len(result.iterations)}"
    assert state["calls"] == 2, f"planner should be called twice, got {state['calls']}"
    print("  [PASS] replan loop converges after one fix iteration")


def test_replan_stops_at_budget():
    # Never-healing planner
    def planner(task_prompt, previous_plan=None, feedback=None):
        return BROKEN_PLAN
    result = run_verified_loop(
        task_prompt="…",
        planner=planner,
        max_iterations=3,
        expected_stores=["http://localhost:8081", "http://localhost:8082",
                         "http://localhost:8083", "http://localhost:8084"],
    )
    assert not result.converged, "should not converge on a broken planner"
    assert len(result.iterations) == 3, f"should run 3 iterations, got {len(result.iterations)}"
    print("  [PASS] replan loop respects iteration budget")


def test_nl_critique_baseline_runs():
    planner, state = make_healing_planner(BROKEN_PLAN, FIXED_PLAN)
    result = run_nl_critique_loop(
        task_prompt="Find all Widget offers.",
        planner=planner,
        max_iterations=3,
        expected_stores=["http://localhost:8081", "http://localhost:8082",
                         "http://localhost:8083", "http://localhost:8084"],
        verifier_aware=True,
    )
    assert result.condition.startswith("nl-critique"), f"unexpected condition: {result.condition}"
    # With verifier_aware=True, it stops early when plan is good
    assert result.converged, f"expected convergence with verifier_aware=True"
    print("  [PASS] nl-critique baseline loop runs end-to-end")


# ── test 2: spec_proposer parses + validates a canned check ──────────────────

def test_spec_proposer_mock():
    prompt = build_proposer_prompt("Find the cheapest offer across the four shops.")
    assert "search_on_page" in prompt
    assert "PropertyResult" in prompt

    raw = MockLLM()(prompt)
    candidates = parse_and_compile_proposals(raw)
    assert len(candidates) == 1, f"expected 1 check; got {len(candidates)}"
    assert candidates[0].name == "check_has_submit"

    reports = validate_checks(
        candidates,
        good_plans=[("good", FIXED_PLAN)],
        bad_plans=[("bad", BROKEN_PLAN)],
    )
    # MockLLM's canned check discriminates good (passes) from bad (fails)
    # FIXED_PLAN has Submit Final Result; BROKEN_PLAN does not.
    assert reports[0].accepted, f"should be accepted; reason={reports[0].reason}"
    print("  [PASS] spec_proposer parses + validates a canned check")


def test_spec_proposer_rejects_trivial_check():
    # A check that always passes — should be rejected by validate_checks
    trivial = '''
def check_always_pass(paths, code):
    return PropertyResult(name="trivial", passed=True, message="")
'''
    candidates = parse_and_compile_proposals(trivial)
    assert len(candidates) == 1
    reports = validate_checks(candidates, good_plans=[("g", FIXED_PLAN)], bad_plans=[("b", BROKEN_PLAN)])
    assert not reports[0].accepted
    assert "trivially" in reports[0].reason
    print("  [PASS] spec_proposer rejects trivially-passing checks")


def test_spec_proposer_rejects_crashing_check():
    crashy = '''
def check_raises(paths, code):
    return 1 / 0
'''
    candidates = parse_and_compile_proposals(crashy)
    assert len(candidates) == 1
    reports = validate_checks(candidates, good_plans=[("g", FIXED_PLAN)], bad_plans=[("b", BROKEN_PLAN)])
    assert not reports[0].accepted
    print("  [PASS] spec_proposer rejects crashing checks")


if __name__ == "__main__":
    print("Running replan_loop + spec_proposer smoke tests…")
    test_replan_converges()
    test_replan_stops_at_budget()
    test_nl_critique_baseline_runs()
    test_spec_proposer_mock()
    test_spec_proposer_rejects_trivial_check()
    test_spec_proposer_rejects_crashing_check()
    print("\nAll tests passed.")
