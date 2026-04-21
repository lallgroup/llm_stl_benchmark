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
