"""
verifier.py — AST + CFG path enumerator for WebMall planner code.

Parses Python planner code and returns all possible action sequences
(execution paths) by modelling:
  - Sequential statements  → concatenation of paths
  - if/else branches        → union of then-paths and else-paths
  - for loops               → 0 iterations (skip) ∪ 1 iteration (body)
  - Assignments w/ calls    → same as an expression call

Only calls to the WebMall DSL functions are tracked as "Actions".
All other expressions are treated as side-effect-free for path purposes.
"""

import ast
from dataclasses import dataclass
from typing import Optional


def _calls_in_expr_args_only(expr: ast.expr) -> list["Action"]:
    """Return DSL calls inside the args/keywords of a Call expression
    (skipping the call itself). Used when inlining: we still want DSL calls
    evaluated as arguments to recorded before the inlined body runs."""
    if not isinstance(expr, ast.Call):
        return []
    out: list = []
    for a in expr.args:
        out.extend(_calls_in_expr(a))
    for kw in expr.keywords:
        out.extend(_calls_in_expr(kw.value))
    return out

# ── DSL vocabulary ─────────────────────────────────────────────────────────────
# The 14 functions exposed to planner code by AgentLab's webmall PlanningAgent
# (see WebMall/AgentLab/.../planning_agent.py execute_plan namespace). We also
# keep the legacy names (`search`, `prompt`) so historical examples still parse.
DSL_FUNCTIONS = {
    # current WebMall DSL
    "noop",
    "search_on_page",
    "open_page", "close_page",
    "go_back", "go_forward",
    "navigate_to_page",
    "extract_information_from_page",
    "fill_text_field", "press_button", "select_option",
    "generic_action",
    "add_to_cart", "checkout",
    # legacy names (pre-Apr 2026 planner prompt)
    "search", "prompt",
}

# Subset that returns an Optional value (used by the None-handling linter in
# properties.py::check_none_guarded). Bool-returning calls are Optional[bool],
# string-returning are Optional[str]; treating both as "may-be-None" is what
# matters for the linter.
DSL_RETURNS_OPTIONAL = {
    "search_on_page",
    "extract_information_from_page",
    "navigate_to_page",
    "generic_action",
    "fill_text_field",
    "press_button",
    "select_option",
    "add_to_cart",
    "checkout",
    # legacy
    "search",
    "prompt",
}

# Parameter-name ordering as advertised to the planner LLM (see the prompt in
# webmall_prompts.jsonl "# Functions:" section). We use these to normalize
# keyword-argument calls like ``press_button(button_description="…")`` back
# into their positional form so property checks only need to look at positions.
DSL_SIGNATURES: dict[str, list[str]] = {
    "noop": ["wait_ms"],
    "search_on_page": ["search_page_url", "search_text"],
    "open_page": ["url"],
    "close_page": [],
    "go_back": [],
    "go_forward": [],
    "navigate_to_page": ["description"],
    "extract_information_from_page": ["description"],
    "fill_text_field": ["field_description", "text"],
    "press_button": ["button_description"],
    "select_option": ["bid", "options"],
    "generic_action": ["description"],
    "add_to_cart": ["url", "item_description"],
    "checkout": ["payment_and_shipping_information"],
    # legacy
    "search": ["store", "product"],
    "prompt": ["instructions"],
}


# ── Action dataclass ───────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Action:
    func: str
    args: tuple  # string literals where extractable; "<var:name>" otherwise

    def __repr__(self) -> str:
        args_str = ", ".join(repr(a) if a is not None else "?" for a in self.args)
        return f"{self.func}({args_str})"


# ── Literal extraction ─────────────────────────────────────────────────────────
def _literal(node: ast.expr) -> object:
    """Return the Python literal value of an AST expression, or a placeholder."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return f"<{node.id}>"
    if isinstance(node, ast.List):
        return [_literal(elt) for elt in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_literal(elt) for elt in node.elts)
    return None


# ── Expression call extractor ─────────────────────────────────────────────────
def _calls_in_expr(expr: ast.expr) -> list[Action]:
    """
    Extract DSL calls from an expression in left-to-right evaluation order.
    Arguments are evaluated before the call itself.
    """
    if not isinstance(expr, ast.expr):
        return []

    if isinstance(expr, ast.Call):
        # Evaluate arguments first
        arg_calls: list[Action] = []
        for arg in expr.args:
            arg_calls.extend(_calls_in_expr(arg))
        for kw in expr.keywords:
            arg_calls.extend(_calls_in_expr(kw.value))

        # Then the call itself
        if isinstance(expr.func, ast.Name) and expr.func.id in DSL_FUNCTIONS:
            name = expr.func.id
            # Merge positional args + keyword args into the advertised positional
            # order.  LLMs often write e.g. press_button(button_description="X"),
            # which we want to be indistinguishable from press_button("X") for
            # property-checking purposes.
            sig = DSL_SIGNATURES.get(name, [])
            # start from positional
            positional = [_literal(a) for a in expr.args]
            if expr.keywords and sig:
                # pad to signature length with None
                slots: list[object] = list(positional) + [None] * max(
                    0, len(sig) - len(positional)
                )
                extras: list[tuple[str, object]] = []
                for kw in expr.keywords:
                    val = _literal(kw.value)
                    if kw.arg is None:
                        # **kwargs unpacking — ignore
                        continue
                    if kw.arg in sig:
                        slots[sig.index(kw.arg)] = val
                    else:
                        # unknown kwarg name — keep at tail so it isn't lost
                        extras.append((kw.arg, val))
                # trim trailing None if all-None (keeps args tight for simple calls)
                while slots and slots[-1] is None and len(slots) > len(positional):
                    slots.pop()
                final = tuple(slots) + tuple(v for _, v in extras)
            else:
                final = tuple(positional)
            action = Action(func=name, args=final)
            return arg_calls + [action]

        # Non-DSL call (e.g., float(), min(), len()) — recurse into args only
        if isinstance(expr.func, ast.Attribute):
            # e.g.  results.append(...)  — not a DSL call
            obj_calls = _calls_in_expr(expr.func.value)
            return obj_calls + arg_calls

        return arg_calls

    if isinstance(expr, (ast.BoolOp,)):
        calls: list[Action] = []
        for val in expr.values:
            calls.extend(_calls_in_expr(val))
        return calls

    if isinstance(expr, ast.BinOp):
        return _calls_in_expr(expr.left) + _calls_in_expr(expr.right)

    if isinstance(expr, ast.UnaryOp):
        return _calls_in_expr(expr.operand)

    if isinstance(expr, ast.Compare):
        calls = _calls_in_expr(expr.left)
        for comp in expr.comparators:
            calls.extend(_calls_in_expr(comp))
        return calls

    if isinstance(expr, ast.IfExp):
        # Condition is always evaluated; treat as producing calls from test only
        # (both branches nondeterministic — handled at statement level)
        return _calls_in_expr(expr.test)

    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        calls = []
        for elt in expr.elts:
            calls.extend(_calls_in_expr(elt))
        return calls

    if isinstance(expr, ast.Dict):
        calls = []
        for k in expr.keys:
            if k:
                calls.extend(_calls_in_expr(k))
        for v in expr.values:
            calls.extend(_calls_in_expr(v))
        return calls

    return []


# ── Statement → paths ─────────────────────────────────────────────────────────
def _inline_local_call(expr: ast.expr) -> Optional[list[list[Action]]]:
    """If ``expr`` is a bare-name call to a locally-defined function, return
    that function's body paths (each path being a list[Action]). Otherwise
    return None.  Recursion is guarded via ``_INLINE_STACK``.
    """
    if not isinstance(expr, ast.Call):
        return None
    if not isinstance(expr.func, ast.Name):
        return None
    callee = expr.func.id
    if callee not in _FUNC_INLINE_MAP:
        return None
    if callee in _INLINE_STACK:
        # recursion — break with a single empty path
        return [[]]
    return _FUNC_INLINE_MAP[callee]


def _stmt_paths(stmt: ast.stmt) -> list[list[Action]]:
    """
    Return the set of possible action sequences produced by one statement.
    Each element of the returned list is one possible path (list of Actions).
    """
    # ── expression statement (bare function call) ──
    if isinstance(stmt, ast.Expr):
        # INLINE: expression is a call to a locally-defined function
        inlined = _inline_local_call(stmt.value)
        if inlined is not None:
            # evaluate args first (usually none for bare `plan()`)
            arg_actions = _calls_in_expr_args_only(stmt.value)
            return [arg_actions + p for p in inlined] if inlined else [arg_actions]
        return [_calls_in_expr(stmt.value)]

    # ── assignment (x = expr) ──
    if isinstance(stmt, ast.Assign):
        # INLINE: RHS is a call to a locally-defined function
        inlined = _inline_local_call(stmt.value)
        if inlined is not None:
            arg_actions = _calls_in_expr_args_only(stmt.value)
            return [arg_actions + p for p in inlined] if inlined else [arg_actions]
        calls = _calls_in_expr(stmt.value)
        return [calls]

    if isinstance(stmt, ast.AugAssign):
        return [_calls_in_expr(stmt.value)]

    if isinstance(stmt, ast.AnnAssign):
        if stmt.value:
            return [_calls_in_expr(stmt.value)]
        return [[]]

    # ── if / elif / else ──
    if isinstance(stmt, ast.If):
        cond_calls = _calls_in_expr(stmt.test)
        then_paths = _block_paths(stmt.body)
        else_paths = _block_paths(stmt.orelse) if stmt.orelse else [[]]
        # Both branches are reachable (condition is nondeterministic)
        return [cond_calls + p for p in then_paths + else_paths]

    # ── for loop ──
    if isinstance(stmt, ast.For):
        # Soundly model as: skip the loop entirely (0 iterations)
        # OR execute the body exactly once (≥1 iterations, representative)
        body_paths = _block_paths(stmt.body)
        return [[]] + body_paths  # skip ∪ one-iteration

    # ── while loop ──
    if isinstance(stmt, ast.While):
        cond_calls = _calls_in_expr(stmt.test)
        body_paths = _block_paths(stmt.body)
        return [[]] + [cond_calls + p for p in body_paths]

    # ── return ──
    if isinstance(stmt, ast.Return):
        if stmt.value:
            return [_calls_in_expr(stmt.value)]
        return [[]]

    # ── try/except ──
    if isinstance(stmt, ast.Try):
        paths: list[list[Action]] = _block_paths(stmt.body)
        for handler in stmt.handlers:
            paths.extend(_block_paths(handler.body))
        if stmt.orelse:
            paths.extend(_block_paths(stmt.orelse))
        if stmt.finalbody:
            paths.extend(_block_paths(stmt.finalbody))
        return paths if paths else [[]]

    # ── with ──
    if isinstance(stmt, ast.With):
        return _block_paths(stmt.body)

    # ── everything else (pass, break, continue, global, …) ──
    return [[]]


def _block_paths(stmts: list[ast.stmt]) -> list[list[Action]]:
    """
    Return all possible action sequences for a *sequence* of statements.
    Paths from each statement are combined by Cartesian product (concatenation).
    """
    if not stmts:
        return [[]]

    head_paths = _stmt_paths(stmts[0])
    tail_paths = _block_paths(stmts[1:])

    return [h + t for h in head_paths for t in tail_paths]


# ── Public API ─────────────────────────────────────────────────────────────────
# Thread-local-ish scratch for function inlining. We build a {name: body_paths}
# map from top-level FunctionDefs before enumerating paths, and _calls_in_expr
# consults it when it sees a bare-name call whose callee is locally defined.
# Recursion is guarded to prevent infinite loops.
_FUNC_INLINE_MAP: dict[str, list[list["Action"]]] = {}
_INLINE_STACK: list[str] = []


def get_all_paths(code: str) -> list[list[Action]]:
    """
    Parse ``code`` and return every possible execution path as a list of
    Actions.  Each path is a list[Action]; the full return value is a
    list of all such paths.

    Function handling: if the plan defines top-level functions (``def f(): …``)
    and invokes them at the top level (``f()``), we INLINE each called
    function's body paths at the call site.  This is essential because many
    LLM plans wrap their logic in ``def plan(): …; plan()``; without inlining
    we would report the top-level as empty.
    """
    tree = ast.parse(code)

    # Build name → body_paths map for all top-level function definitions.
    # We build this WITHOUT inlining nested calls first, then re-run with
    # inlining enabled — a single fixpoint step handles plan() calling
    # helper() calling another DSL function.
    global _FUNC_INLINE_MAP, _INLINE_STACK
    saved_map = _FUNC_INLINE_MAP
    saved_stack = _INLINE_STACK
    try:
        _FUNC_INLINE_MAP = {}
        _INLINE_STACK = []
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _FUNC_INLINE_MAP[n.name] = _block_paths(n.body)
        # Second pass: now that the map exists, function calls can be inlined.
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _FUNC_INLINE_MAP[n.name] = _block_paths(n.body)
        return _block_paths(tree.body)
    finally:
        _FUNC_INLINE_MAP = saved_map
        _INLINE_STACK = saved_stack


def get_all_store_literals(code: str) -> list[str]:
    """
    Walk the AST and collect every string that looks like a store URL or name
    found in list literals assigned to variables whose name contains 'store'.
    Used for Property 3 analysis.
    """
    tree = ast.parse(code)
    stores: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and "store" in target.id.lower():
                    val = node.value
                    if isinstance(val, ast.List):
                        for elt in val.elts:
                            lit = _literal(elt)
                            if isinstance(lit, str):
                                stores.append(lit)
                            elif isinstance(lit, (list, tuple)):
                                # e.g. ("Shop Name", "http://...")
                                for item in lit:
                                    if isinstance(item, str):
                                        stores.append(item)
    return stores
