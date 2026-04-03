"""
properties.py — Static property checkers for WebMall planner code.

Adapted from llm_stl_benchmark/formal_verification/properties.py for the
WebMall JSONL plan output format.  Property definitions mirror the original
three checks but use WebMall's DSL and submission conventions:

  P1  press_button("Submit Final Result") appears on EVERY execution path.
  P2  fill_text_field(...) appears BEFORE submit on every execution path.
  P3  The stores list literal contains ALL expected shop URLs.

Each checker takes the list of paths from verifier.get_all_paths()
(and optionally the raw code string) and returns a PropertyResult.
"""

from dataclasses import dataclass
from typing import Optional
from verifier import Action, get_all_paths, get_all_store_literals

# ── WebMall shop URLs expected in every plan ─────────────────────────────────
WEBMALL_STORES = [
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
]


@dataclass
class PropertyResult:
    name: str
    passed: bool
    message: str
    counterexample: Optional[list[Action]] = None


# ── helpers ────────────────────────────────────────────────────────────────────

def _is_submit(action: Action) -> bool:
    return action.func == "press_button" and action.args == ("Submit Final Result",)


def _is_fill(action: Action) -> bool:
    """Any fill_text_field call counts as filling an answer field."""
    return action.func == "fill_text_field"


# ── Property 1: Submit Final Result is always called ─────────────────────────

def check_submit_always_called(paths: list[list[Action]]) -> PropertyResult:
    """
    Every execution path must contain press_button('Submit Final Result').
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


# ── Property 2: Answer field filled BEFORE submit ────────────────────────────

def check_fill_before_submit(paths: list[list[Action]]) -> PropertyResult:
    """
    On every execution path, fill_text_field(...) must appear at least once
    and must precede press_button('Submit Final Result').
    """
    for path in paths:
        submit_indices = [i for i, a in enumerate(path) if _is_submit(a)]
        fill_indices   = [i for i, a in enumerate(path) if _is_fill(a)]

        if not submit_indices:
            # P1 already catches this; skip here to avoid duplicate reports
            continue

        first_submit = submit_indices[0]

        if not fill_indices:
            return PropertyResult(
                name="P2: Answer field filled before submit",
                passed=False,
                message="Found a path that calls submit WITHOUT any fill_text_field.",
                counterexample=path,
            )

        last_fill_before_submit = max(
            (i for i in fill_indices if i < first_submit), default=None
        )
        if last_fill_before_submit is None:
            return PropertyResult(
                name="P2: Answer field filled before submit",
                passed=False,
                message=(
                    "Found a path where fill_text_field only appears "
                    "AFTER press_button('Submit Final Result')."
                ),
                counterexample=path,
            )

    return PropertyResult(
        name="P2: Answer field filled before submit",
        passed=True,
        message=f"All {len(paths)} paths fill a text field before submitting.",
    )


# ── Property 3: All expected stores are referenced ───────────────────────────

def check_all_stores_searched(
    code: str,
    expected: list[str] = WEBMALL_STORES,
) -> PropertyResult:
    """
    Structural check: the 'stores' list literal in the code must contain
    every entry in ``expected`` (URL prefix match).
    """
    found = get_all_store_literals(code)

    missing = [e for e in expected if not any(e in s for s in found)]

    if missing:
        return PropertyResult(
            name="P3: All stores referenced",
            passed=False,
            message=(
                f"stores literal contains {found}.\n"
                f"    Missing entries: {missing}"
            ),
        )

    return PropertyResult(
        name="P3: All stores referenced",
        passed=True,
        message=f"All {len(expected)} expected stores present in the stores literal.",
    )


# ── Convenience: run all properties ──────────────────────────────────────────

def verify(
    code: str,
    expected_stores: Optional[list[str]] = None,
) -> tuple[list[PropertyResult], list[list[Action]]]:
    paths = get_all_paths(code)
    results = [
        check_submit_always_called(paths),
        check_fill_before_submit(paths),
        check_all_stores_searched(code, expected=expected_stores or WEBMALL_STORES),
    ]
    return results, paths
