"""
spec_proposer.py — Ask an LLM to generate task-specific formal-verification
properties for a given WebMall task, then safely compile and load them so they
can run alongside the hard-coded P0..P6 checks.

The LLM sees:
  * the task prompt (so it knows what the plan is supposed to achieve)
  * the DSL signatures (so it knows what calls to look for)
  * the PropertyResult dataclass + the signature of a check function
  * one or two example hard-coded checks (few-shot)

It returns one or more functions of the form

    def check_<name>(paths: list[list[Action]], code: str) -> PropertyResult:
        ...

which we:
  * exec inside a restricted namespace (only ast, re, verifier.Action, and the
    PropertyResult dataclass are exposed — no file / network builtins),
  * dry-run against known-good and known-bad plans to reject brittle checks.

The module is LLM-agnostic: pass any callable ``generate(prompt) -> str``. A
``MockLLM`` is provided for tests.
"""

from __future__ import annotations

import ast
import inspect
import re
import textwrap
import traceback
from dataclasses import dataclass
from typing import Callable, Optional

from verifier import Action, DSL_SIGNATURES, DSL_RETURNS_OPTIONAL
from properties import PropertyResult


# ── Prompt template ───────────────────────────────────────────────────────────

SPEC_PROPOSER_SYSTEM_PROMPT = """\
You are a formal-verification expert. Given a WebMall task prompt and the DSL
the planner uses, propose one or more Python properties that a *correct* plan
for that task must satisfy.

Each property is a Python function:

    def check_<short_name>(paths, code) -> PropertyResult:
        ...

where
  * `paths` is a list of execution paths, each path is a list of Action named-
    tuples with fields `.func` (str, one of the DSL function names) and
    `.args` (tuple of literals, where each literal is a str / int / None; an
    argument that is a variable reference shows up as the string "<varname>"),
  * `code` is the raw plan source as a string,
  * `PropertyResult(name, passed, message, counterexample=None)` is the return
    type.

Rules:
1. Base every check on structural evidence (which DSL calls appear in which
   order, with which literal args), NOT on runtime values — we do not execute
   the plan.
2. Your checks must run on EVERY plan (no Python syntax errors, no crashes).
3. Return passed=True if the plan structurally satisfies the property and
   passed=False with an informative message otherwise.
4. Keep each check focused on a single property derived from the task prompt.
   Prefer multiple small checks over one giant one.
5. Do NOT redefine PropertyResult or Action — import semantics are handled for
   you.
6. Do NOT import anything.  The only names available are: ast, re, Action,
   PropertyResult, and Python built-ins (len, any, all, min, max, range,
   enumerate, sorted, set, tuple, list, str, int, float, bool, isinstance).

Output format: **only** Python source code containing one or more `def
check_*` functions, separated by blank lines. No explanations, no markdown
fences.
"""


FEW_SHOT_EXAMPLE = """\
Example task prompt:
    "Find the cheapest offer for product P across all four shops."

Example output:

def check_computes_min_price(paths, code):
    # structural check: the plan must contain a reference to `min(` with a
    # collection of prices, OR sort/sorted, OR an inline comparison.
    has_min_or_sort = ("min(" in code) or ("sorted(" in code)
    if has_min_or_sort:
        return PropertyResult(
            name="T1: Plan selects a minimum over collected prices",
            passed=True,
            message="Plan uses min() or sorted() over a collection.",
        )
    return PropertyResult(
        name="T1: Plan selects a minimum over collected prices",
        passed=False,
        message="No min()/sorted() call found; cannot guarantee selection of the cheapest offer.",
    )

def check_extracts_price_per_store(paths, code):
    # Every path that searches a store and finds a URL should follow with an
    # extract_information_from_page or prompt call (so a price can be obtained).
    for path in paths:
        for i, a in enumerate(path):
            if a.func in ("search_on_page", "search"):
                # look ahead for an extract-like call before the next search
                saw_extract = False
                for b in path[i+1 : i+8]:
                    if b.func in ("extract_information_from_page", "prompt", "generic_action"):
                        saw_extract = True
                        break
                    if b.func in ("search_on_page", "search"):
                        break
                if not saw_extract:
                    return PropertyResult(
                        name="T2: Each search is followed by a price extraction",
                        passed=False,
                        message="A search_on_page call is not followed by a price extraction before the next search.",
                        counterexample=path,
                    )
    return PropertyResult(
        name="T2: Each search is followed by a price extraction",
        passed=True,
        message="Every search_on_page call is followed by a price extraction.",
    )
"""


def build_proposer_prompt(task_prompt: str, *, extra_hints: str = "") -> str:
    dsl_lines = []
    for fn, params in DSL_SIGNATURES.items():
        sig = ", ".join(params)
        optional = " (returns Optional — may be None)" if fn in DSL_RETURNS_OPTIONAL else ""
        dsl_lines.append(f"  * {fn}({sig}){optional}")
    dsl_block = "\n".join(dsl_lines)

    pieces = [
        SPEC_PROPOSER_SYSTEM_PROMPT,
        "",
        "DSL signatures:",
        dsl_block,
        "",
        FEW_SHOT_EXAMPLE,
        "",
        "Now propose properties for the following task:",
        "",
        task_prompt.strip(),
    ]
    if extra_hints:
        pieces += ["", "Additional hints:", extra_hints.strip()]
    return "\n".join(pieces)


# ── Safe execution of generated check code ───────────────────────────────────

_SAFE_BUILTINS = {
    "len": len, "any": any, "all": all, "min": min, "max": max,
    "range": range, "enumerate": enumerate, "sorted": sorted,
    "set": set, "tuple": tuple, "list": list, "dict": dict,
    "str": str, "int": int, "float": float, "bool": bool,
    "isinstance": isinstance, "abs": abs, "print": print,
    "getattr": getattr, "hasattr": hasattr, "zip": zip,
    "map": map, "filter": filter, "next": next, "iter": iter,
    "True": True, "False": False, "None": None,
    "Exception": Exception, "ValueError": ValueError,
}


@dataclass
class ProposedCheck:
    name: str                                   # function name
    source: str                                 # raw source (one def)
    func: Callable[[list, str], PropertyResult] # bound callable


def parse_and_compile_proposals(source: str) -> list[ProposedCheck]:
    """Parse the LLM output, extract each top-level `def check_*`, compile &
    bind them in a restricted namespace. Returns only the functions that
    compiled and are callable.  Never raises.

    Strips markdown fences defensively (the LLM sometimes ignores the no-fence
    instruction).
    """
    source = source.strip()
    # strip ``` fences if present
    if source.startswith("```"):
        parts = source.split("```")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p.startswith("python"):
                p = p[len("python"):].strip()
            if "def check_" in p:
                source = p
                break

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    # Collect top-level `def check_*` functions only
    keep_defs: list[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("check_"):
            keep_defs.append(node)

    if not keep_defs:
        return []

    checks: list[ProposedCheck] = []
    for fn_def in keep_defs:
        # Render just this one function as source for exec'ing
        fn_src = ast.unparse(fn_def)

        namespace: dict = {
            "__builtins__": _SAFE_BUILTINS,
            "Action": Action,
            "PropertyResult": PropertyResult,
            "ast": ast,
            "re": re,
        }
        try:
            exec(fn_src, namespace)
        except Exception:
            continue
        fn = namespace.get(fn_def.name)
        if not callable(fn):
            continue
        # validate signature
        try:
            sig = inspect.signature(fn)
            if len(sig.parameters) != 2:
                continue
        except (TypeError, ValueError):
            continue
        checks.append(ProposedCheck(name=fn_def.name, source=fn_src, func=fn))

    return checks


# ── Dry-run validation ────────────────────────────────────────────────────────

@dataclass
class ValidationReport:
    check: ProposedCheck
    behaviour: dict          # plan_label → PropertyResult or exception-string
    accepted: bool
    reason: str


def validate_checks(
    checks: list[ProposedCheck],
    good_plans: list[tuple[str, str]],
    bad_plans:  list[tuple[str, str]],
) -> list[ValidationReport]:
    """Run each check against known-good (should pass) and known-bad plans.

    Accept a check if:
      * it never raises
      * it does not return PASS on every single input (trivially-pass → useless)
      * it does not return FAIL on every single input (trivially-fail → noisy)

    Returns one ValidationReport per check.  Callers typically filter to
    .accepted=True.
    """
    from verifier import get_all_paths  # lazy import

    reports: list[ValidationReport] = []
    for c in checks:
        behaviour: dict = {}
        any_err = False
        results: list[bool] = []
        for label, code in good_plans + bad_plans:
            try:
                paths = get_all_paths(code)
            except Exception as e:
                behaviour[label] = f"<could not parse plan: {e}>"
                continue
            try:
                r = c.func(paths, code)
            except Exception as e:
                behaviour[label] = f"<raised {type(e).__name__}: {e}>"
                any_err = True
                continue
            if not isinstance(r, PropertyResult):
                behaviour[label] = f"<returned non-PropertyResult: {type(r).__name__}>"
                any_err = True
                continue
            behaviour[label] = r
            results.append(bool(r.passed))

        if any_err:
            reports.append(ValidationReport(c, behaviour, False, "raises or bad return type"))
            continue
        if not results:
            reports.append(ValidationReport(c, behaviour, False, "no inputs evaluated"))
            continue
        if all(results):
            reports.append(ValidationReport(c, behaviour, False, "trivially passes all inputs"))
            continue
        if not any(results):
            reports.append(ValidationReport(c, behaviour, False, "trivially fails all inputs"))
            continue
        reports.append(ValidationReport(c, behaviour, True, "discriminates good from bad"))

    return reports


# ── Mock LLM for tests ────────────────────────────────────────────────────────

class MockLLM:
    """A stub `generate(prompt) -> str` that returns a canned check. Useful for
    unit-testing the spec-proposer pipeline without an API key."""

    def __init__(self, canned: Optional[str] = None):
        self.canned = canned or textwrap.dedent("""\
            def check_has_submit(paths, code):
                from_code = "press_button" in code and "Submit Final Result" in code
                if from_code:
                    return PropertyResult(
                        name="mock: code mentions submit",
                        passed=True,
                        message="code contains 'Submit Final Result' literal.",
                    )
                return PropertyResult(
                    name="mock: code mentions submit",
                    passed=False,
                    message="code does not contain 'Submit Final Result' literal.",
                )
        """)

    def __call__(self, prompt: str) -> str:
        return self.canned


# ── End-to-end helper ────────────────────────────────────────────────────────

def propose_and_validate(
    task_prompt: str,
    generate: Callable[[str], str],
    good_plans: list[tuple[str, str]],
    bad_plans: list[tuple[str, str]],
    extra_hints: str = "",
) -> list[ProposedCheck]:
    """One-shot: prompt LLM → parse → validate → return only accepted checks."""
    prompt = build_proposer_prompt(task_prompt, extra_hints=extra_hints)
    raw = generate(prompt)
    candidates = parse_and_compile_proposals(raw)
    if not candidates:
        return []
    reports = validate_checks(candidates, good_plans, bad_plans)
    return [r.check for r in reports if r.accepted]
