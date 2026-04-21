"""
properties.py — Static property checkers for WebMall planner code.

Each checker takes the list of paths produced by verifier.get_all_paths()
(and optionally the raw code string) and returns a PropertyResult.
"""

import ast
import re
from dataclasses import dataclass
from typing import Optional

from verifier import (
    Action,
    get_all_paths,
    get_all_store_literals,
    DSL_FUNCTIONS,
    DSL_RETURNS_OPTIONAL,
)

# Built-in callables that are always fine to appear in a plan in addition to
# DSL functions. This list is intentionally small: we want to flag LLM
# hallucinations (e.g. ``go_to_checkout``) while not complaining about
# ``float``, ``min``, ``len``, etc.
_ALLOWED_BUILTINS = {
    "abs", "all", "any", "ascii", "bool", "bytes", "chr", "dict", "divmod",
    "enumerate", "filter", "float", "format", "frozenset", "getattr", "hasattr",
    "hash", "hex", "id", "int", "isinstance", "issubclass", "iter", "len",
    "list", "map", "max", "min", "next", "oct", "ord", "pow", "print", "range",
    "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum",
    "tuple", "type", "zip", "dict", "Exception", "ValueError", "TypeError",
    "KeyError", "IndexError",
}


@dataclass
class PropertyResult:
    name: str
    passed: bool
    message: str
    counterexample: Optional[list[Action]] = None  # path that violated the property


# ── helpers ────────────────────────────────────────────────────────────────────

# Known literals for "the final submit button" and "the solution text field".
# Accept both the current WebMall prompts and the legacy examples so we don't
# spuriously fail old hardcoded plans.
_SUBMIT_LITERALS = {
    "Submit Final Result",
}

# Field descriptions that, when present in the FIRST argument of fill_text_field,
# mean "this is the solution/final-answer field".
_SOLUTION_FIELD_SUBSTRINGS = (
    "type your final answer",   # current WebMall prompt wording
    "solution field",           # legacy wording
    "solution",                 # fallback
    "final answer",             # fallback
    "final result",             # fallback
)


def _as_str(x: object) -> str:
    """Return x as a lowercase string if possible, else ''. Handles AST placeholders."""
    return x.lower() if isinstance(x, str) else ""


def _is_submit(action: Action) -> bool:
    if action.func != "press_button":
        return False
    if not action.args:
        return False
    first = action.args[0]
    if not isinstance(first, str):
        return False
    return first in _SUBMIT_LITERALS


def _is_fill_solution(action: Action) -> bool:
    if action.func != "fill_text_field":
        return False
    if not action.args:
        return False
    first = _as_str(action.args[0])
    return any(tok in first for tok in _SOLUTION_FIELD_SUBSTRINGS)


def _names_tested_for_none(test: ast.expr) -> list[str]:
    """Return names x for which `test` is equivalent to `x is None` (or
    `x == None`) — possibly in the context of `or`-joined conditions like
    `x is None or x == ""`.  Used to detect `if x is None: x = default`."""
    names: list[str] = []
    if isinstance(test, ast.Compare):
        def _check(left, right):
            if isinstance(left, ast.Name) and isinstance(right, ast.Constant) and right.value is None:
                return left.id
            return None
        left = test.left
        for op, right in zip(test.ops, test.comparators):
            if isinstance(op, (ast.Is, ast.Eq)):
                n = _check(left, right) or _check(right, left)
                if n:
                    names.append(n)
    elif isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
        # if x is None or <something>: — first disjunct triggers sanitization
        for v in test.values:
            names.extend(_names_tested_for_none(v))
    return names


def _normalize_url(u: str) -> str:
    """Strip scheme + trailing slash so 'http://localhost:8081/' == 'localhost:8081'."""
    u = u.strip().rstrip("/")
    u = re.sub(r"^https?://", "", u)
    return u


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
    On every execution path, fill_text_field('<solution-field-description>', ...)
    must appear at least once, and must precede press_button('Submit Final Result').
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
                message=(
                    "Found a path that submits WITHOUT ever filling the solution "
                    "field (no fill_text_field matching 'solution'/'final answer')."
                ),
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
                    "Found a path where fill_text_field(solution-field, …) "
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

def _search_on_page_urls(code: str) -> list[str]:
    """Collect every literal string URL that is passed as the first arg to a
    search_on_page() / search() call anywhere in the code, including inside
    `for x in [urls…]: search_on_page(x, …)` loops (we unroll that statically)."""
    tree = ast.parse(code)
    urls: list[str] = []

    # 1) direct calls with a string literal first arg
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("search_on_page", "search") and node.args:
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    urls.append(first.value)
                # for tuple unpack like ("name", "url") passed as single arg —
                # not common, skip.

    # 2) for-loop pattern: for store in [url1, url2, …]: search_on_page(store, …)
    #    We attribute every literal in the iterable to a search_on_page call if
    #    the loop body contains such a call on the loop variable.
    for node in ast.walk(tree):
        if not isinstance(node, ast.For):
            continue
        # loop var name
        if not isinstance(node.target, ast.Name):
            continue
        var = node.target.id
        # collect literal URLs from the iterable
        loop_urls: list[str] = []
        if isinstance(node.iter, (ast.List, ast.Tuple, ast.Set)):
            for elt in node.iter.elts:
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                    loop_urls.append(elt.value)
                elif isinstance(elt, ast.Tuple):
                    # e.g. ("E-Store Athletes", "http://localhost:8081/")
                    for sub in elt.elts:
                        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                            loop_urls.append(sub.value)
        if not loop_urls:
            continue
        # does the body contain search_on_page(var, …) ?
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Name)
                and sub.func.id in ("search_on_page", "search")
                and sub.args
                and isinstance(sub.args[0], ast.Name)
                and sub.args[0].id == var
            ):
                urls.extend(loop_urls)
                break

    return urls


def check_all_stores_searched(
    code: str,
    expected: list[str],
) -> PropertyResult:
    """
    Static data-flow check: every URL in ``expected`` must appear (after URL
    normalization — strip scheme + trailing slash) as an argument to a
    search_on_page/search call. Also accepts the legacy ``stores`` list-literal
    pattern.

    This is a purely structural check — we look at what the LLM hardcoded, not
    at runtime behaviour.
    """
    # Collect URLs from search_on_page call sites.
    call_urls = _search_on_page_urls(code)
    # Collect URLs from any `stores*` list literal (legacy fallback).
    literal_urls = get_all_store_literals(code)

    found_norm = {_normalize_url(u) for u in call_urls + literal_urls}

    missing = [e for e in expected if _normalize_url(e) not in found_norm]

    if missing:
        return PropertyResult(
            name="P3: All stores searched",
            passed=False,
            message=(
                f"Found store references: {sorted(found_norm)}.\n"
                f"    Missing (normalized): {[_normalize_url(m) for m in missing]}"
            ),
        )

    return PropertyResult(
        name="P3: All stores searched",
        passed=True,
        message=f"All {len(expected)} expected stores present in the plan.",
    )


# ── Property 4: Optional-returning DSL calls are None-guarded ────────────────

def check_none_guarded(code: str) -> PropertyResult:
    """
    For every assignment ``x = f(...)`` where f is in DSL_RETURNS_OPTIONAL, every
    subsequent read of x must be either:
      (a) inside the True-branch of a None/truthy-guard on x (``if x:``,
          ``if x is not None:``, ``if x != None:`` or equivalent), OR
      (b) the expression being tested in such a guard, OR
      (c) passed to a "safe sink" (print/log/append to results list — we're
          lenient here).

    We also flag direct-use-at-call-site: ``open_page(search_on_page(...))``
    where the inner DSL call could return None but is used without a guard.

    This is sound-ish but not complete; it's a lint, not a theorem prover.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PropertyResult(
            name="P4: None-returning results guarded",
            passed=False,
            message=f"Cannot lint: syntax error ({e}).",
        )

    violations: list[str] = []

    # Collect "tainted" variable names: x such that x = f(...) with f Optional.
    # Map var → list of (lineno, func) for reporting.
    tainted: dict[str, list[tuple[int, str]]] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if not isinstance(node.value.func, ast.Name):
            continue
        if node.value.func.id not in DSL_RETURNS_OPTIONAL:
            continue
        # only track simple single-target assignments
        for tgt in node.targets:
            if isinstance(tgt, ast.Name):
                tainted.setdefault(tgt.id, []).append((node.lineno, node.value.func.id))

    # "Sanitized after line L": variables which, after a specific line, have
    # been provably de-Optional-ified by the
    #
    #    if x is None: x = <non-None default>
    #
    # idiom. We compute sanitization_lineno[var] = earliest line after which
    # subsequent reads are safe. Reads at earlier lines still need a guard.
    sanitization_lineno: dict[str, int] = {}

    def _assigns_non_none(body: list[ast.stmt], var: str) -> bool:
        """True if the body unconditionally assigns a non-None value to var."""
        for s in body:
            if isinstance(s, ast.Assign):
                for tgt in s.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == var:
                        # consider the assignment safe if the RHS is not the
                        # literal None and not another Optional DSL call.
                        rhs = s.value
                        if isinstance(rhs, ast.Constant) and rhs.value is None:
                            return False
                        if (
                            isinstance(rhs, ast.Call)
                            and isinstance(rhs.func, ast.Name)
                            and rhs.func.id in DSL_RETURNS_OPTIONAL
                        ):
                            return False
                        return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # test: x is None   /   x == None   /   not (x is not None)   /   x is None or …
        names_tested = _names_tested_for_none(node.test)
        if not names_tested:
            continue
        # True branch is the "x is None" branch — if it assigns a non-None value
        # to x, subsequent code has x definitely-non-None.
        for var in names_tested:
            if var in tainted and _assigns_non_none(node.body, var):
                # take the earliest applicable line
                prev = sanitization_lineno.get(var)
                if prev is None or node.end_lineno is not None and node.end_lineno < prev:
                    sanitization_lineno[var] = node.end_lineno or node.lineno

    if not tainted:
        # nothing to check — vacuously true
        return PropertyResult(
            name="P4: None-returning results guarded",
            passed=True,
            message="No Optional-returning DSL results bound to variables.",
        )

    # Walk the tree tracking the set of currently-guarded names in scope.
    def _guard_names(test: ast.expr) -> set[str]:
        """Names proven non-None inside the True-branch of `if test:`."""
        out: set[str] = set()
        # `if x:`
        if isinstance(test, ast.Name):
            out.add(test.id)
        # `if x is not None:` / `if x != None:` / `if None is not x:`
        if isinstance(test, ast.Compare):
            def _both(a, b):
                if isinstance(a, ast.Name) and isinstance(b, ast.Constant) and b.value is None:
                    return a.id
                return None
            left = test.left
            for op, right in zip(test.ops, test.comparators):
                if isinstance(op, (ast.IsNot, ast.NotEq)):
                    n = _both(left, right) or _both(right, left)
                    if n:
                        out.add(n)
        # `if x is not None and …` / `if x and …`
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.And):
            for v in test.values:
                out |= _guard_names(v)
        return out

    # Check direct nested use: open_page(search_on_page(...)) etc.
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in DSL_RETURNS_OPTIONAL  # e.g. open_page is optional-bool
            # actually open_page is in our optional set too; we only flag the
            # DANGEROUS case where the call's result is an arg to something that
            # expects a real value (len, str, concatenation, subscript, etc.)
        ):
            pass  # handled per-arg below

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # flag any argument that is itself a DSL_RETURNS_OPTIONAL call, because
        # the OUTER call (or operation) cannot distinguish None from a real value
        for arg in node.args:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id in DSL_RETURNS_OPTIONAL
            ):
                # allowed if the outer call is print/logger/append-like
                outer = getattr(node.func, "id", None) or getattr(node.func, "attr", None) or ""
                if outer in ("print", "append", "extend"):
                    continue
                violations.append(
                    f"line {node.lineno}: result of {arg.func.id}(…) is used "
                    f"directly as an argument to {outer or '<call>'}(…) "
                    f"without a None-check."
                )

    # For each tainted var, walk its usages.  We do a scope-oblivious pass: a
    # read counts as "guarded" if it is lexically inside an `if` whose test
    # names the var in a truthy/non-None way.  Good enough for lint.
    class GuardTracker(ast.NodeVisitor):
        def __init__(self):
            self.guard_stack: list[set[str]] = []

        def currently_guarded(self) -> set[str]:
            out: set[str] = set()
            for g in self.guard_stack:
                out |= g
            return out

        def visit_If(self, node: ast.If):
            guards = _guard_names(node.test)
            # test may itself read the name (that's always fine)
            self.guard_stack.append(guards)
            for s in node.body:
                self.visit(s)
            self.guard_stack.pop()
            # orelse is NOT guarded
            for s in node.orelse:
                self.visit(s)

        def visit_IfExp(self, node: ast.IfExp):
            # conditional expression: `body if test else orelse`.
            # The truthy branch sees non-None guarantees from the test; the
            # orelse branch does not.  The test itself is always safe (names
            # tested there are added to in_test in the pre-pass).
            guards = _guard_names(node.test)
            self.visit(node.test)
            self.guard_stack.append(guards)
            self.visit(node.body)
            self.guard_stack.pop()
            self.visit(node.orelse)

        def visit_Name(self, node: ast.Name):
            if not isinstance(node.ctx, ast.Load):
                return
            if node.id not in tainted:
                return
            # allowed: reads inside any if-test (we allow these unconditionally)
            # allowed: inside currently-guarded scope
            if node.id in self.currently_guarded():
                return
            # also allow assignments of the form `x_was_none = x is None` etc.
            # which we approximate by checking if the parent is a Compare/BoolOp.
            # We don't have parent pointers here, so accept Compare.left/right
            # reads by just being lenient about direct-in-Compare in another
            # pass:
            violations.append(
                f"line {node.lineno}: variable {node.id!r} "
                f"(assigned from Optional DSL result) read without None-guard."
            )

        # Treat the test expression of an If as safe reads (it IS the guard).
        def _skip_test(self, node):
            pass

    # Pre-pass: collect the `Name` nodes that appear inside `If.test` (these
    # are the guard expressions themselves and should not be flagged).
    in_test: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                in_test.add(id(sub))
        # also accept reads inside Compare / BoolOp inside a While test
        if isinstance(node, ast.While):
            for sub in ast.walk(node.test):
                in_test.add(id(sub))
        # conditional expressions: `x if x is not None else ""`
        if isinstance(node, ast.IfExp):
            for sub in ast.walk(node.test):
                in_test.add(id(sub))

    tracker = GuardTracker()
    tracker.visit(tree)

    # Drop violations whose AST node was inside a test expression.
    filtered: list[str] = []
    name_nodes_by_line: dict[int, list[ast.Name]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            name_nodes_by_line.setdefault(node.lineno, []).append(node)

    def _is_test_use(varname: str, lineno: int) -> bool:
        for n in name_nodes_by_line.get(lineno, []):
            if n.id == varname and id(n) in in_test:
                return True
        return False

    for v in violations:
        # parse "line L: variable 'x' ..." back out
        m = re.match(r"line (\d+): variable '([^']+)'", v)
        if m:
            lno = int(m.group(1))
            var = m.group(2)
            if _is_test_use(var, lno):
                continue
            # Skip reads that come AFTER an `if x is None: x = default` block
            san_line = sanitization_lineno.get(var)
            if san_line is not None and lno > san_line:
                continue
        filtered.append(v)

    if filtered:
        # show at most 5
        preview = "\n      ".join(filtered[:5])
        more = f"\n      ... (+{len(filtered) - 5} more)" if len(filtered) > 5 else ""
        return PropertyResult(
            name="P4: None-returning results guarded",
            passed=False,
            message=f"{len(filtered)} unguarded use(s) of Optional results:\n      {preview}{more}",
        )

    return PropertyResult(
        name="P4: None-returning results guarded",
        passed=True,
        message=f"All reads of Optional-bound vars are None-guarded ({len(tainted)} vars).",
    )


# ── Property 5: Solution page opened before submit ──────────────────────────

SOLUTION_PAGE_URLS = ("http://localhost:8085", "http://localhost:3000")


def check_solution_page_opened(paths: list[list[Action]]) -> PropertyResult:
    """
    Every path that submits must first open the solution page.

    We check for open_page("http://localhost:8085/...") or legacy
    open_page("http://localhost:3000/...") appearing before the submit.
    """
    def _is_solution_open(a: Action) -> bool:
        if a.func != "open_page" or not a.args:
            return False
        first = a.args[0]
        if not isinstance(first, str):
            return False
        return any(first.rstrip("/").startswith(u) for u in SOLUTION_PAGE_URLS)

    for path in paths:
        submit_indices = [i for i, a in enumerate(path) if _is_submit(a)]
        if not submit_indices:
            continue  # P1 catches this
        first_submit = submit_indices[0]
        opens = [i for i, a in enumerate(path) if _is_solution_open(a) and i < first_submit]
        if not opens:
            return PropertyResult(
                name="P5: Solution page opened before submit",
                passed=False,
                message="Path submits without ever opening the solution page (localhost:8085).",
                counterexample=path,
            )

    return PropertyResult(
        name="P5: Solution page opened before submit",
        passed=True,
        message=f"All {len(paths)} submitting paths open the solution page first.",
    )


# ── Property 0: Only known DSL / builtin functions are called ───────────────

def check_dsl_only(code: str) -> PropertyResult:
    """
    Flag any top-level call to a function that is neither in DSL_FUNCTIONS nor
    in a small allow-list of builtins. This catches LLM hallucinations like
    ``go_to_checkout(...)`` (observed in deepseek-coder-6.7b plans) where the
    LLM invents a DSL function that does not exist.

    Method-style calls (``list.append``, ``str.strip``) are ignored — we only
    check bare-name calls, which is where plan-level hallucinations surface.

    Also ignores names that are bound inside the plan itself (assignments,
    function/class defs, comprehension/for targets) so utility helpers are OK.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PropertyResult(
            name="P0: Uses only DSL / builtin functions",
            passed=False,
            message=f"Cannot check: syntax error ({e}).",
        )

    # Names defined by the plan itself — OK to call.
    defined: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    defined.add(tgt.id)
                elif isinstance(tgt, (ast.Tuple, ast.List)):
                    for e in tgt.elts:
                        if isinstance(e, ast.Name):
                            defined.add(e.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, (ast.For, ast.comprehension)):
            tgt = node.target if isinstance(node, ast.For) else node.target
            if isinstance(tgt, ast.Name):
                defined.add(tgt.id)
            elif isinstance(tgt, (ast.Tuple, ast.List)):
                for e in tgt.elts:
                    if isinstance(e, ast.Name):
                        defined.add(e.id)
        elif isinstance(node, ast.Lambda):
            for arg in node.args.args:
                defined.add(arg.arg)
        elif isinstance(node, ast.withitem):
            if node.optional_vars and isinstance(node.optional_vars, ast.Name):
                defined.add(node.optional_vars.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            defined.add(node.name)

    bad: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not isinstance(fn, ast.Name):
            continue  # method call or complex expression — skip
        name = fn.id
        if name in DSL_FUNCTIONS:
            continue
        if name in _ALLOWED_BUILTINS:
            continue
        if name in defined:
            continue
        bad.append((node.lineno, name))

    if bad:
        dedup: dict[str, int] = {}
        for _, name in bad:
            dedup[name] = dedup.get(name, 0) + 1
        listing = ", ".join(f"{k} ({v}×)" for k, v in sorted(dedup.items()))
        first = bad[0]
        return PropertyResult(
            name="P0: Uses only DSL / builtin functions",
            passed=False,
            message=f"Calls to unknown functions: {listing}. First at line {first[0]}: {first[1]}(...).",
        )

    return PropertyResult(
        name="P0: Uses only DSL / builtin functions",
        passed=True,
        message="All bare-name calls resolve to DSL / builtin / locally-defined functions.",
    )


# ── Property 6: No "dead" function definitions wrapping the whole plan ──────

def check_top_level_executes(code: str) -> PropertyResult:
    """
    The WebMall executor runs the plan with bare ``exec(plan, globals)`` — any
    logic wrapped in a ``def plan(): ...`` that is never called at the top
    level is a no-op and the task silently does nothing.  This check flags
    plans where every DSL call is buried inside a function definition that is
    never invoked at the module level.

    Pattern observed frequently in GPT-5.1 plans (Apr 2026).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return PropertyResult(
            name="P6: Top-level code actually runs",
            passed=False,
            message=f"Cannot check: syntax error ({e}).",
        )

    # Which function names are defined at the module top level?
    defined_fns = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

    # Which functions get called at module top level?
    top_called: set[str] = set()
    for n in tree.body:
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name):
            top_called.add(n.value.func.id)
        elif isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name):
            top_called.add(n.value.func.id)

    # Does the top level include ANY DSL call (directly, not inside a def)?
    def _has_dsl_call(node: ast.AST) -> bool:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id in {
                "noop", "search_on_page", "open_page", "close_page", "go_back",
                "go_forward", "navigate_to_page", "extract_information_from_page",
                "fill_text_field", "press_button", "select_option",
                "generic_action", "add_to_cart", "checkout",
                "search", "prompt",
            }:
                return True
        return False

    top_level_dsl_calls = False
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if _has_dsl_call(n):
            top_level_dsl_calls = True
            break

    if top_level_dsl_calls:
        return PropertyResult(
            name="P6: Top-level code actually runs",
            passed=True,
            message="Top-level code contains direct DSL calls (not just function definitions).",
        )

    # No top-level DSL calls.  Is there a def whose body has DSL calls, and is
    # that def called at the top level?
    defs_with_dsl = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _has_dsl_call(n)
    ]
    if not defs_with_dsl:
        return PropertyResult(
            name="P6: Top-level code actually runs",
            passed=False,
            message="No DSL calls at module top level and no function definitions containing DSL calls. Plan appears empty.",
        )

    called_defs = [fn.name for fn in defs_with_dsl if fn.name in top_called]
    if called_defs:
        return PropertyResult(
            name="P6: Top-level code actually runs",
            passed=True,
            message=f"Plan wrapped in function(s) {called_defs}, but they are invoked at the top level.",
        )

    uncalled = [fn.name for fn in defs_with_dsl]
    return PropertyResult(
        name="P6: Top-level code actually runs",
        passed=False,
        message=(
            f"Plan defines function(s) {uncalled} containing all the DSL logic, "
            f"but none are called at the top level. exec(plan) will be a no-op."
        ),
    )


# ── Convenience: run all properties ──────────────────────────────────────────

def verify(
    code: str,
    expected_stores: Optional[list[str]] = None,
) -> tuple[list[PropertyResult], list[list[Action]]]:
    paths = get_all_paths(code)
    results = [
        check_dsl_only(code),
        check_top_level_executes(code),
        check_submit_always_called(paths),
        check_solution_filled_before_submit(paths),
        check_solution_page_opened(paths),
        check_none_guarded(code),
    ]
    if expected_stores is not None:
        results.append(check_all_stores_searched(code, expected_stores))
    return results, paths
