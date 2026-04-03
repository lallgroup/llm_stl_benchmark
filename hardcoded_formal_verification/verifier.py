"""
verifier.py — AST + CFG path enumerator for WebMall planner code.

Adapted from llm_stl_benchmark/formal_verification/verifier.py to use
the WebMall DSL function vocabulary (search_on_page, open_page,
extract_information_from_page, etc.) instead of the benchmark's smaller set.

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

# ── DSL vocabulary (WebMall planner functions) ────────────────────────────────
DSL_FUNCTIONS = {
    "search_on_page",
    "open_page",
    "close_page",
    "go_back",
    "go_forward",
    "navigate_to_page",
    "extract_information_from_page",
    "fill_text_field",
    "press_button",
    "select_option",
    "generic_action",
    "add_to_cart",
    "checkout",
    "noop",
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
            action = Action(
                func=expr.func.id,
                args=tuple(_literal(a) for a in expr.args),
            )
            return arg_calls + [action]

        # Non-DSL call — recurse into args only
        if isinstance(expr.func, ast.Attribute):
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
def _stmt_paths(stmt: ast.stmt) -> list[list[Action]]:
    """
    Return the set of possible action sequences produced by one statement.
    Each element of the returned list is one possible path (list of Actions).
    """
    if isinstance(stmt, ast.Expr):
        return [_calls_in_expr(stmt.value)]

    if isinstance(stmt, ast.Assign):
        calls = _calls_in_expr(stmt.value)
        return [calls]

    if isinstance(stmt, ast.AugAssign):
        return [_calls_in_expr(stmt.value)]

    if isinstance(stmt, ast.AnnAssign):
        if stmt.value:
            return [_calls_in_expr(stmt.value)]
        return [[]]

    if isinstance(stmt, ast.If):
        cond_calls = _calls_in_expr(stmt.test)
        then_paths = _block_paths(stmt.body)
        else_paths = _block_paths(stmt.orelse) if stmt.orelse else [[]]
        return [cond_calls + p for p in then_paths + else_paths]

    if isinstance(stmt, ast.For):
        body_paths = _block_paths(stmt.body)
        return [[]] + body_paths  # skip ∪ one-iteration

    if isinstance(stmt, ast.While):
        cond_calls = _calls_in_expr(stmt.test)
        body_paths = _block_paths(stmt.body)
        return [[]] + [cond_calls + p for p in body_paths]

    if isinstance(stmt, ast.Return):
        if stmt.value:
            return [_calls_in_expr(stmt.value)]
        return [[]]

    if isinstance(stmt, ast.Try):
        paths: list[list[Action]] = _block_paths(stmt.body)
        for handler in stmt.handlers:
            paths.extend(_block_paths(handler.body))
        if stmt.orelse:
            paths.extend(_block_paths(stmt.orelse))
        if stmt.finalbody:
            paths.extend(_block_paths(stmt.finalbody))
        return paths if paths else [[]]

    if isinstance(stmt, ast.With):
        return _block_paths(stmt.body)

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
def get_all_paths(code: str) -> list[list[Action]]:
    """
    Parse ``code`` and return every possible execution path as a list of
    Actions.  Each path is a list[Action]; the full return value is a
    list of all such paths.
    """
    tree = ast.parse(code)
    return _block_paths(tree.body)


def get_all_store_literals(code: str) -> list[str]:
    """
    Walk the AST and collect every string found in list literals assigned
    to variables whose name contains 'store'.
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
                                for item in lit:
                                    if isinstance(item, str):
                                        stores.append(item)
    return stores
