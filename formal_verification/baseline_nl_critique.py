"""
baseline_nl_critique.py — The natural-language critique baseline from the
Mar 31 research plan.

  * Prompt 1: the webmall prompt → plan_0
  * Prompt 2 (optional): if plan_0 is not valid Python, re-prompt for valid code
  * Prompt 3 (always): "Check your plan to make sure it meets all the
    requirements and contains no errors. Revise your plan."

This is the no-verifier baseline we compare our FV-guided re-plan loop
against.  Shares scaffolding with ``replan_loop.run_verified_loop``.
"""

from __future__ import annotations

from typing import Callable, Optional

from properties import PropertyResult
from replan_loop import LoopResult, IterationRecord, run_verified_loop


NL_CRITIQUE_PROMPT = (
    "Check your plan to make sure it meets all the requirements and contains "
    "no errors. Revise your plan. Output only the revised plan as Python code "
    "(no explanations)."
)


# Natural-language paraphrases of the seven structural properties. Deliberately
# free of property names (no "P1"), counterexample paths, and line numbers —
# we want to convey the SAME information content as build_fv_feedback but in
# prose so we can isolate whether the FV win is about structure or specificity.
_PROPERTY_NL_TEMPLATES: dict[str, str] = {
    "P0: Uses only DSL / builtin functions":
        "Your plan calls functions that don't exist in the action space. Every "
        "function call must resolve to one of the 14 listed DSL functions (like "
        "search_on_page, fill_text_field, press_button, etc.) or a standard "
        "Python built-in like min, float, or len. Remove or replace any "
        "function that isn't in that set.",
    "P1: Submit always called":
        "Your plan doesn't always reach the end: it is possible for execution "
        "to finish without ever calling press_button(\"Submit Final Result\"). "
        "Make sure the submit button is pressed on every code path, including "
        "the case where no results are found.",
    "P2: Solution field filled before submit":
        "Your plan presses \"Submit Final Result\" without first filling in "
        "the final-answer text field. Make sure fill_text_field is called "
        "with the solution on the solution page BEFORE pressing submit.",
    "P3: All stores searched":
        "Your plan doesn't search all of the shops the task expects. The four "
        "shops are at http://localhost:8081, http://localhost:8082, "
        "http://localhost:8083, and http://localhost:8084; every shop URL that "
        "the task requires should appear as an argument to search_on_page.",
    "P4: None-returning results guarded":
        "Some of the DSL functions you call (search_on_page, "
        "extract_information_from_page, and similar) can return None if the "
        "lookup fails. Your plan uses those return values without first "
        "checking for None, which can cause a runtime error. Add a None check "
        "(for example `if x is not None:` or `x = x or \"\"`) before using the "
        "result of every such call.",
    "P5: Solution page opened before submit":
        "Your plan submits the final result but never opens the solution page "
        "first. You need to call open_page(\"http://localhost:8085/\") before "
        "filling in the answer field and pressing submit, so that the submit "
        "button is on the page you are interacting with.",
    "P6: Top-level code actually runs":
        "Your plan wraps all of its logic inside a function definition (for "
        "example `def plan():`) but never calls that function at the top level, "
        "so when the plan is executed with exec() it will define the function "
        "and then do nothing. Either write the plan as plain top-level "
        "statements, or add a call to the function at the end.",
}


def build_oracle_nl_feedback(results: list[PropertyResult]) -> Optional[str]:
    """Oracle-NL feedback: the same set of failures as the FV-guided condition,
    but described in prose — without property IDs, counterexample paths, or
    line numbers. This isolates whether the FV loop's advantage comes from
    being *formal* (structured counterexamples, line-exact locations) or
    merely from being *specific* (naming the issue at all).

    Returns None when every property passes, so the loop short-circuits.
    """
    failures = [r for r in results if not r.passed]
    if not failures:
        return None

    lines = [
        "Your previous plan has the following issues. Revise the plan so each "
        "issue is addressed; don't introduce new problems in the process.",
        "",
    ]
    for r in failures:
        nl = _PROPERTY_NL_TEMPLATES.get(r.name)
        if nl is None:
            # Fall back to a generic sentence derived from the property name
            nl = (f"There is a problem with your plan regarding "
                  f"\"{r.name.split(':', 1)[-1].strip()}\".")
        lines.append(f"- {nl}")
    lines.append("")
    lines.append("Output only the revised plan as Python code. Do not explain.")
    return "\n".join(lines)


def build_nl_feedback(results: list[PropertyResult]) -> Optional[str]:
    """Return a generic NL critique prompt — ignoring the verifier results
    entirely.  This is the baseline behaviour: the LLM is asked to self-
    critique without being told which properties failed.

    We still return None if every property passed, so the loop can short-
    circuit (the baseline converges when the LLM chooses not to change the
    plan — this is rare).  In practice the NL baseline almost always does
    at least one revision regardless of whether properties pass.
    """
    # Unconditional re-critique: we keep returning feedback for every
    # iteration up to the loop's max, which gives the baseline the same number
    # of chances as the verified loop.  To converge early when verifier is
    # already satisfied (for the "NL-critique + verifier-aware" variant), use
    # the verifier-aware wrapper below.
    return NL_CRITIQUE_PROMPT


def build_nl_feedback_verifier_aware(results: list[PropertyResult]) -> Optional[str]:
    """Variant: same generic critique, but converges as soon as the verifier
    says the plan is good.  Used when we still want a fair "stop when
    correct" signal without telling the LLM WHAT was wrong."""
    if all(r.passed for r in results):
        return None
    return NL_CRITIQUE_PROMPT


def run_oracle_nl_loop(
    task_prompt: str,
    planner: Callable[..., str],
    *,
    max_iterations: int = 3,
    expected_stores: Optional[list[str]] = None,
) -> LoopResult:
    """Oracle-NL baseline: exactly the plan→verify→re-plan loop as FV-guided,
    but the feedback handed to the planner is the NL paraphrase produced by
    ``build_oracle_nl_feedback`` rather than the structured FV report.

    Same stopping criterion (all properties pass); same number of iterations;
    same knowledge of *which* properties failed --- just no counterexample
    paths, no line numbers, no property names. Isolates the effect of
    structure vs. specificity.
    """
    return run_verified_loop(
        task_prompt=task_prompt,
        planner=planner,
        max_iterations=max_iterations,
        expected_stores=expected_stores,
        extra_checks=None,
        feedback_builder=build_oracle_nl_feedback,
        condition="oracle-nl",
    )


def run_nl_critique_loop(
    task_prompt: str,
    planner: Callable[..., str],
    *,
    max_iterations: int = 3,
    expected_stores: Optional[list[str]] = None,
    verifier_aware: bool = False,
) -> LoopResult:
    """Run the NL-critique baseline.  No verifier feedback is fed to the
    planner; the generic critique prompt is used every iteration.

    ``verifier_aware=True`` converges early when the verifier passes (keeps
    the loop from wasting iterations on already-good plans), but still does
    not share verifier output with the planner.
    """
    builder = build_nl_feedback_verifier_aware if verifier_aware else build_nl_feedback
    return run_verified_loop(
        task_prompt=task_prompt,
        planner=planner,
        max_iterations=max_iterations,
        expected_stores=expected_stores,
        extra_checks=None,
        feedback_builder=builder,
        condition="nl-critique" + ("+vaware" if verifier_aware else ""),
    )
