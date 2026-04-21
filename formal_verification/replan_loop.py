"""
replan_loop.py — Verified re-planning loop.

    plan_0 = planner(task_prompt)
    while not all_checks_pass(plan_k) and k < K:
        feedback = failure_report(plan_k)
        plan_{k+1} = planner(task_prompt, previous_plan=plan_k, feedback=feedback)
        k += 1

Two conditions share this loop:

  * **FV-guided (ours)**    — feedback is a structured report of which P0..P6
                              (and optionally LLM-proposed) properties failed,
                              with counterexample paths.
  * **NL-critique baseline** — feedback is the LLM's own natural-language
                              critique of its plan (no verifier involved).

The planner is supplied as a callable:

    def planner(task_prompt: str, previous_plan: Optional[str],
                feedback: Optional[str]) -> str: ...

so the loop is model-agnostic.  Each iteration is logged to a trace list so
the caller can write convergence data to disk for later analysis.
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from typing import Callable, Optional

from properties import verify, PropertyResult
from spec_proposer import ProposedCheck


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class IterationRecord:
    iteration: int
    plan: str
    property_results: list[dict]  # serialized PropertyResult dicts
    path_count: int
    fed_back_feedback: Optional[str] = None  # feedback used to produce THIS plan (None for iter 0)


@dataclass
class LoopResult:
    task_prompt: str
    final_plan: str
    converged: bool                           # True if all properties passed at the end
    iterations: list[IterationRecord] = field(default_factory=list)
    condition: str = "fv-guided"              # or "nl-critique", "vanilla"

    def to_dict(self) -> dict:
        return {
            "task_prompt": self.task_prompt,
            "final_plan": self.final_plan,
            "converged": self.converged,
            "condition": self.condition,
            "iterations": [vars(it) for it in self.iterations],
        }


# ── Feedback builders ─────────────────────────────────────────────────────────

def _result_to_dict(r: PropertyResult) -> dict:
    d = {"name": r.name, "passed": r.passed, "message": r.message}
    if r.counterexample is not None:
        d["counterexample"] = [repr(a) for a in r.counterexample]
    return d


def build_fv_feedback(results: list[PropertyResult]) -> Optional[str]:
    """Format a structured failure report for the planner LLM.  Returns None
    if every property passed (nothing to fix)."""
    failures = [r for r in results if not r.passed]
    if not failures:
        return None
    lines = [
        "Your previous plan failed the following formal-verification checks. "
        "Revise the plan so that every check passes. Do not introduce new bugs.",
        "",
    ]
    for r in failures:
        lines.append(f"- {r.name}")
        # indent the message two spaces deeper for readability
        lines.append(textwrap.indent(r.message.strip(), "    "))
        if r.counterexample is not None:
            lines.append("    Counterexample path:")
            for i, a in enumerate(r.counterexample[:10]):
                lines.append(f"      {i:>2}. {a}")
            if len(r.counterexample) > 10:
                lines.append(f"      ... ({len(r.counterexample) - 10} more actions)")
        lines.append("")
    return "\n".join(lines).rstrip()


# ── Main loop ────────────────────────────────────────────────────────────────

def run_verified_loop(
    task_prompt: str,
    planner: Callable[..., str],
    *,
    max_iterations: int = 3,
    expected_stores: Optional[list[str]] = None,
    extra_checks: Optional[list[ProposedCheck]] = None,
    feedback_builder: Callable[[list[PropertyResult]], Optional[str]] = build_fv_feedback,
    condition: str = "fv-guided",
) -> LoopResult:
    """Run plan → verify → re-plan loop until all properties pass or max_iterations is reached.

    Parameters
    ----------
    task_prompt
        The original WebMall task prompt.
    planner
        Callable ``planner(task_prompt, previous_plan=None, feedback=None) -> plan_src``.
    max_iterations
        Upper bound on the number of re-plans (counts iter 0 as the initial plan).
        So max_iterations=3 means at most plan_0, plan_1, plan_2.
    expected_stores
        Optional list of URLs used by ``check_all_stores_searched`` (P3).
    extra_checks
        LLM-proposed checks from spec_proposer (already validated).
    feedback_builder
        Function mapping property results to the feedback string handed back
        to the planner.  Use ``build_fv_feedback`` (default) for FV-guided
        mode or ``build_nl_feedback`` in ``baseline_nl_critique.py`` for the NL
        baseline.
    condition
        Free-form label stored on the returned LoopResult.
    """
    assert max_iterations >= 1

    trace: list[IterationRecord] = []
    plan = planner(task_prompt, previous_plan=None, feedback=None)

    for k in range(max_iterations):
        # Run all checks
        try:
            base_results, paths = verify(plan, expected_stores=expected_stores)
        except SyntaxError as e:
            # Treat syntax error as a distinguished failure
            synth = PropertyResult(
                name="P-syntax: plan is valid Python",
                passed=False,
                message=f"SyntaxError: {e.msg} at line {e.lineno}. Rewrite the plan as valid Python.",
            )
            base_results, paths = [synth], []

        extra_results: list[PropertyResult] = []
        if extra_checks:
            for c in extra_checks:
                try:
                    extra_results.append(c.func(paths, plan))
                except Exception as e:
                    extra_results.append(PropertyResult(
                        name=f"(LLM-proposed) {c.name}",
                        passed=False,
                        message=f"Check raised {type(e).__name__}: {e}",
                    ))

        all_results = list(base_results) + list(extra_results)

        trace.append(IterationRecord(
            iteration=k,
            plan=plan,
            property_results=[_result_to_dict(r) for r in all_results],
            path_count=len(paths),
            fed_back_feedback=trace[-1].fed_back_feedback if k > 0 else None,
        ))

        feedback = feedback_builder(all_results)
        if feedback is None:
            # All checks passed → done
            return LoopResult(
                task_prompt=task_prompt,
                final_plan=plan,
                converged=True,
                iterations=trace,
                condition=condition,
            )

        # If we've exhausted our budget, stop without re-planning once more.
        if k == max_iterations - 1:
            break

        # Re-plan
        revised = planner(task_prompt, previous_plan=plan, feedback=feedback)
        if not isinstance(revised, str) or not revised.strip():
            break
        plan = revised
        # Record the feedback alongside the NEXT iteration it is about to produce.
        # We set fed_back_feedback on the soon-to-be-appended record at the top of
        # the next loop turn; simplest: attach to trace[-1] retroactively.
        trace[-1].fed_back_feedback = feedback

    return LoopResult(
        task_prompt=task_prompt,
        final_plan=plan,
        converged=False,
        iterations=trace,
        condition=condition,
    )


# ── Convenience serializer ────────────────────────────────────────────────────

def dump_loop_result_jsonl(result: LoopResult, out_path: str, task_id: str = "") -> None:
    with open(out_path, "a") as fh:
        fh.write(json.dumps({"task_id": task_id, **result.to_dict()}) + "\n")
