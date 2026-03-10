"""
run_demo.py — Formal verification demo for WebMall planner code.

Statically verifies three properties on LLM-generated planner scripts:

  P1  press_button("Submit Final Result") appears on EVERY execution path.
  P2  fill_text_field("Solution field", …) appears BEFORE submit on every path.
  P3  The stores list literal contains ALL expected shop URLs / names.

Verification is done purely on the AST — no code is executed.
"""

import sys
import textwrap
from properties import verify
from planner_examples import ALL_EXAMPLES


# ── pretty-printing ────────────────────────────────────────────────────────────

GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS_LABEL = f"{GREEN}PASS{RESET}"
FAIL_LABEL = f"{RED}FAIL{RESET}"


def _fmt_path(path, max_actions=12) -> str:
    if not path:
        return "  (empty path — code reaches this state having called no DSL actions)"
    lines = [f"  {i:>2}. {a}" for i, a in enumerate(path[:max_actions])]
    if len(path) > max_actions:
        lines.append(f"  ... ({len(path) - max_actions} more actions)")
    return "\n".join(lines)


def run_demo():
    total_checks = 0
    total_pass   = 0

    for example in ALL_EXAMPLES:
        name      = example["name"]
        code      = example["code"]
        stores    = example.get("expected_stores")
        is_mutant = name.startswith("[MUTANT]")

        print(f"\n{'='*70}")
        label = f"{YELLOW}[MUTANT]{RESET} " if is_mutant else ""
        print(f"{BOLD}{label}{name}{RESET}")
        print(f"{'='*70}")

        results, paths = verify(code, expected_stores=stores)

        print(f"  Execution paths found (via CFG): {len(paths)}\n")

        for r in results:
            total_checks += 1
            status = PASS_LABEL if r.passed else FAIL_LABEL

            print(f"  [{status}] {r.name}")
            print(f"         {r.message}")

            if not r.passed:
                if r.counterexample is not None:
                    print(f"\n         Counterexample path:")
                    print(_fmt_path(r.counterexample))
                    print()
            else:
                total_pass += 1

    # ── summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    failed = total_checks - total_pass
    colour = GREEN if failed == 0 else RED
    print(
        f"{BOLD}Result: {colour}{total_pass}/{total_checks} checks passed"
        f"  ({failed} failed){RESET}"
    )
    print(f"{'='*70}\n")

    # ── explain the approach ──────────────────────────────────────────────────
    print(textwrap.dedent("""\
    Verification method
    -------------------
    1. Parse each planner script to an AST (no execution).
    2. Build a Control Flow Graph: every if/else creates two branches;
       every for loop creates a "skip" path and a "body" path.
    3. Enumerate all paths through the CFG (Cartesian product of branch choices).
    4. Check each property exhaustively across ALL paths:
         P1 — every path contains press_button("Submit Final Result")
         P2 — every path has fill_text_field("Solution field", …) before submit
         P3 — the stores literal contains all expected shop identifiers (static)

    This is sound: a PASS guarantee means the property holds for every
    possible execution, regardless of what search() / prompt() return.
    A FAIL provides a concrete counterexample path.
    """))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_demo())
