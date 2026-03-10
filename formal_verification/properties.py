"""
properties.py — Static property checkers for WebMall planner code.

Each checker takes the list of paths produced by verifier.get_all_paths()
(and optionally the raw code string) and returns a PropertyResult.
"""

from dataclasses import dataclass, field
from typing import Optional
from verifier import Action, get_all_paths, get_all_store_literals


@dataclass
class PropertyResult:
    name: str
    passed: bool
    message: str
    counterexample: Optional[list[Action]] = None  # path that violated the property


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_submit(action: Action) -> bool:
    return action.func == "press_button" and action.args == ("Submit Final Result",)


def _is_fill_solution(action: Action) -> bool:
    return (
        action.func == "fill_text_field"
        and len(action.args) >= 1
        and isinstance(action.args[0], str)
        and "solution" in action.args[0].lower()
    )


# ── Property 1: Submit Final Result is always called ─────────────────────────

def check_submit_always_called(paths: list[list[Action]]) -> PropertyResult:
    """
    Every execution path must contain a call to press_button('Submit Final Result').
    """
    for path in paths:
        if not any(_is_submit(a) for a in path):
            return PropertyResult(
                name="P1: Submit always called",
                passed=False,
                message=f"Found a path with NO submit call ({len(path)} actions).",
                counterexample=path,
            )
    return PropertyResult(
        name="P1: Submit always called",
        passed=True,
        message=f"All {len(paths)} paths contain press_button('Submit Final Result').",
    )


# ── Property 2: Solution field filled BEFORE submit ──────────────────────────

def check_solution_filled_before_submit(paths: list[list[Action]]) -> PropertyResult:
    """
    On every execution path, fill_text_field('Solution field', ...) must appear
    at least once, and must precede press_button('Submit Final Result').
    """
    for path in paths:
        submit_indices = [i for i, a in enumerate(path) if _is_submit(a)]
        fill_indices   = [i for i, a in enumerate(path) if _is_fill_solution(a)]

        if not submit_indices:
            # P1 already catches this; skip here to avoid duplicate reports
            continue

        first_submit = submit_indices[0]

        if not fill_indices:
            return PropertyResult(
                name="P2: Solution field filled before submit",
                passed=False,
                message="Found a path that submits WITHOUT filling the solution field.",
                counterexample=path,
            )

        last_fill_before_submit = max(
            (i for i in fill_indices if i < first_submit), default=None
        )
        if last_fill_before_submit is None:
            return PropertyResult(
                name="P2: Solution field filled before submit",
                passed=False,
                message=(
                    "Found a path where fill_text_field('Solution field') "
                    "only appears AFTER press_button('Submit Final Result')."
                ),
                counterexample=path,
            )

    return PropertyResult(
        name="P2: Solution field filled before submit",
        passed=True,
        message=f"All {len(paths)} paths fill the solution field before submitting.",
    )


# ── Property 3: All expected stores are searched ─────────────────────────────

def check_all_stores_searched(
    code: str,
    expected: list[str],
) -> PropertyResult:
    """
    Static data-flow check: the 'stores' list literal in the code must contain
    every entry in ``expected`` (URL or name).

    This is a purely structural check — we look at what the LLM hardcoded,
    not at runtime behaviour.
    """
    found = get_all_store_literals(code)

    missing = [e for e in expected if not any(e in s for s in found)]

    if missing:
        return PropertyResult(
            name="P3: All stores searched",
            passed=False,
            message=(
                f"stores literal contains {found}.\n"
                f"    Missing entries: {missing}"
            ),
        )

    return PropertyResult(
        name="P3: All stores searched",
        passed=True,
        message=f"All {len(expected)} expected stores present in the stores literal.",
    )


# ── Convenience: run all properties ──────────────────────────────────────────

def verify(
    code: str,
    expected_stores: Optional[list[str]] = None,
) -> list[PropertyResult]:
    paths = get_all_paths(code)
    results = [
        check_submit_always_called(paths),
        check_solution_filled_before_submit(paths),
    ]
    if expected_stores is not None:
        results.append(check_all_stores_searched(code, expected_stores))
    return results, paths
