"""
run_verification.py — Formal verification over WebMall JSONL plan outputs.

Reads a .jsonl file where each line is a JSON object with at minimum:
  - "id"             : task identifier string
  - "clean_response" : the extracted Python plan code (no ```fences)

Falls back to stripping ```python ... ``` fences from "response" if
"clean_response" is absent.

For each plan, statically verifies three properties (no code executed):

  P1  press_button("Submit Final Result") appears on EVERY execution path.
  P2  fill_text_field(...) appears BEFORE submit on every execution path.
  P3  The stores list literal contains all 4 expected WebMall shop URLs.

Usage:
    python run_verification.py <path/to/plans.jsonl>
    python run_verification.py ../plan_docs/webmall_plan_gpt-5.1_0.0_Example_True.jsonl
"""

import json
import re
import sys
import textwrap
from pathlib import Path

from properties import verify, WEBMALL_STORES


# ── ANSI colours ──────────────────────────────────────────────────────────────
GREEN  = "\033[32m"
RED    = "\033[31m"
YELLOW = "\033[33m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

PASS_LABEL = f"{GREEN}PASS{RESET}"
FAIL_LABEL = f"{RED}FAIL{RESET}"
SKIP_LABEL = f"{YELLOW}SKIP{RESET}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_code(record: dict) -> str | None:
    """Return clean Python code from a JSONL record."""
    if record.get("clean_response"):
        return record["clean_response"]
    raw = record.get("response", "")
    # Strip ```python ... ``` or ``` ... ``` fences
    match = re.search(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1)
    return raw.strip() or None


def _fmt_path(path, max_actions: int = 12) -> str:
    if not path:
        return "  (empty path — no DSL actions on this path)"
    lines = [f"  {i:>2}. {a}" for i, a in enumerate(path[:max_actions])]
    if len(path) > max_actions:
        lines.append(f"  ... ({len(path) - max_actions} more actions)")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def run(jsonl_path: str) -> int:
    path = Path(jsonl_path)
    if not path.exists():
        print(f"{RED}Error:{RESET} file not found: {jsonl_path}", file=sys.stderr)
        return 2

    records = []
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"{YELLOW}Warning:{RESET} skipping malformed JSON on line {lineno}: {e}")

    if not records:
        print("No records found in file.")
        return 1

    total_tasks   = 0
    total_checks  = 0
    total_pass    = 0
    skipped       = 0

    for record in records:
        task_id = record.get("id", "<unknown>")
        code    = _extract_code(record)

        print(f"\n{'='*70}")
        print(f"{BOLD}{task_id}{RESET}")
        print(f"{'='*70}")

        if not code:
            print(f"  [{SKIP_LABEL}] No code found in record — skipping.")
            skipped += 1
            continue

        try:
            results, paths = verify(code, expected_stores=WEBMALL_STORES)
        except SyntaxError as e:
            print(f"  [{SKIP_LABEL}] SyntaxError parsing plan: {e}")
            skipped += 1
            continue

        total_tasks += 1
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

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    failed = total_checks - total_pass
    colour = GREEN if failed == 0 else RED
    print(
        f"{BOLD}Tasks verified: {total_tasks}  |  Skipped: {skipped}{RESET}"
    )
    print(
        f"{BOLD}Checks: {colour}{total_pass}/{total_checks} passed"
        f"  ({failed} failed){RESET}"
    )
    print(f"{'='*70}\n")

    print(textwrap.dedent("""\
    Verification method
    -------------------
    1. Parse each plan to an AST (no execution).
    2. Build a CFG: every if/else creates two branches;
       every for/while loop creates a "skip" path and a "body" path.
    3. Enumerate all paths through the CFG (Cartesian product of branch choices).
    4. Check each property exhaustively across ALL paths:
         P1 — every path contains press_button("Submit Final Result")
         P2 — every path has fill_text_field(...) before submit
         P3 — the stores literal contains all 4 expected shop URLs

    A PASS means the property holds for every possible execution.
    A FAIL provides a concrete counterexample path.
    """))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python {Path(sys.argv[0]).name} <path/to/plans.jsonl>")
        sys.exit(1)
    sys.exit(run(sys.argv[1]))
