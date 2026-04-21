"""
run_formal_verification.py — Batch-verify a jsonl file of WebMall plans.

Reads one plan per line, runs compile() for syntactic validity, runs every
formal-verification property in properties.py, and writes:

  * <input>.annotated.jsonl  — same rows with added verification keys
  * <input>.summary.csv      — one row per property with pass/fail counts
  * <input>.summary.txt      — human-readable aggregate report

Usage
-----
    python run_formal_verification.py \
        --input webmall_plan_gpt-5.1_0.0_Example_True.jsonl \
        [--prompts webmall_prompts.jsonl] \
        [--expected-stores http://localhost:8081,http://localhost:8082,...] \
        [--outdir results/]

If --prompts is given, the task id on each plan row is looked up in the
prompts file so we can attach a category tag (derived from the id — e.g.
``webmall.Webmall_Find_Specific_Product_Task1`` → ``Find_Specific_Product``)
and split the summary per category.

Each jsonl plan row is expected to have keys ``id`` (required) and one of
``clean_response`` (preferred) or ``response`` (fallback).  The "clean_response"
field is extracted in the existing notebook pipeline (``get_first_valid``).

Exit code 0 on success (even if plans fail verification), nonzero on I/O error.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from dataclasses import asdict
from typing import Optional

# Local imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from properties import (  # noqa: E402
    verify,
    PropertyResult,
)


DEFAULT_EXPECTED_STORES = [
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
]


# ── helpers ────────────────────────────────────────────────────────────────────

def _task_category(task_id: str) -> str:
    """
    'webmall.Webmall_Find_Specific_Product_Task7' → 'Find_Specific_Product'.
    Falls back to the full id if the pattern doesn't match.
    """
    m = re.match(r"^webmall\.Webmall_(.+?)_Task\d+", task_id)
    return m.group(1) if m else task_id


def _extract_code(row: dict) -> str:
    """Prefer pre-cleaned Python; fall back to raw response stripped of fences."""
    code = row.get("clean_response")
    if code:
        return code
    raw = row.get("response") or ""
    # strip ```python … ``` fences if present
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if not p:
                continue
            if p.startswith("python"):
                p = p[len("python"):].strip()
            # accept the first block that compiles
            try:
                compile(p, "<plan>", "exec")
                return p
            except SyntaxError:
                continue
    return raw


def _result_to_dict(r: PropertyResult) -> dict:
    d = {
        "name": r.name,
        "passed": r.passed,
        "message": r.message,
    }
    if r.counterexample is not None:
        # serialize Action objects as "func(arg1, arg2)" strings
        d["counterexample"] = [repr(a) for a in r.counterexample]
    return d


# ── main batch routine ────────────────────────────────────────────────────────

def verify_file(
    input_path: str,
    prompts_path: Optional[str],
    expected_stores: list[str],
    outdir: str,
) -> dict:
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(input_path))[0]
    annotated_path = os.path.join(outdir, f"{base}.annotated.jsonl")
    summary_csv = os.path.join(outdir, f"{base}.summary.csv")
    summary_txt = os.path.join(outdir, f"{base}.summary.txt")

    # Optionally load per-task prompt metadata (unused right now but kept for
    # future per-task expected_stores derivation)
    _prompts_by_id: dict[str, dict] = {}
    if prompts_path and os.path.exists(prompts_path):
        with open(prompts_path) as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                    if "id" in row:
                        _prompts_by_id[row["id"]] = row
                except json.JSONDecodeError:
                    continue

    per_prop_pass: dict[str, int] = {}
    per_prop_fail: dict[str, int] = {}
    per_cat: dict[str, dict[str, dict[str, int]]] = {}  # cat → prop → {pass,fail}
    per_cat_totals: dict[str, int] = {}
    total = 0
    empty = 0
    syntax_errors = 0

    t0 = time.time()
    with open(input_path) as fh_in, open(annotated_path, "w") as fh_out:
        for line_no, line in enumerate(fh_in, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[warn] line {line_no}: bad JSON ({e}) — skipped", file=sys.stderr)
                continue

            total += 1
            code = _extract_code(row)
            task_id = row.get("id", "<unknown>")
            cat = _task_category(task_id)
            per_cat_totals[cat] = per_cat_totals.get(cat, 0) + 1

            out_row = dict(row)
            if not (code or "").strip():
                empty += 1
                out_row["valid_code"] = False
                out_row["compile_error"] = "empty"
                out_row["property_results"] = []
                fh_out.write(json.dumps(out_row) + "\n")
                continue

            # Syntactic validity
            try:
                compile(code, "<plan>", "exec")
                valid = True
                compile_err = None
            except SyntaxError as e:
                valid = False
                compile_err = f"{type(e).__name__}: {e.msg} (line {e.lineno})"
                syntax_errors += 1

            out_row["valid_code"] = valid
            if compile_err:
                out_row["compile_error"] = compile_err

            if not valid:
                out_row["property_results"] = []
                out_row["path_count"] = 0
                fh_out.write(json.dumps(out_row) + "\n")
                continue

            try:
                results, paths = verify(code, expected_stores=expected_stores)
            except Exception as e:  # last-resort safety net
                print(f"[warn] line {line_no} {task_id}: verify raised {type(e).__name__}: {e}",
                      file=sys.stderr)
                out_row["property_results"] = []
                out_row["path_count"] = 0
                out_row["verify_exception"] = str(e)
                fh_out.write(json.dumps(out_row) + "\n")
                continue

            out_row["path_count"] = len(paths)
            out_row["property_results"] = [_result_to_dict(r) for r in results]
            fh_out.write(json.dumps(out_row) + "\n")

            for r in results:
                if r.passed:
                    per_prop_pass[r.name] = per_prop_pass.get(r.name, 0) + 1
                else:
                    per_prop_fail[r.name] = per_prop_fail.get(r.name, 0) + 1
                d = per_cat.setdefault(cat, {}).setdefault(r.name, {"pass": 0, "fail": 0})
                d["pass" if r.passed else "fail"] += 1

    elapsed = time.time() - t0
    verifiable = total - empty - syntax_errors

    # ── write summary CSV ────────────────────────────────────────────────────
    prop_order = sorted(set(per_prop_pass) | set(per_prop_fail), key=_prop_sort_key)
    with open(summary_csv, "w", newline="") as fh_csv:
        w = csv.writer(fh_csv)
        w.writerow(["property", "pass", "fail", "total", "pass_pct"])
        for name in prop_order:
            p = per_prop_pass.get(name, 0)
            f_ = per_prop_fail.get(name, 0)
            tot = p + f_
            w.writerow([name, p, f_, tot, f"{100*p/max(1,tot):.2f}"])
        w.writerow([])
        w.writerow(["_syntactic_validity", verifiable, syntax_errors + empty, total,
                    f"{100*verifiable/max(1,total):.2f}"])

    # ── write human-readable txt summary ─────────────────────────────────────
    lines: list[str] = []
    lines.append(f"Input:      {input_path}")
    lines.append(f"Plans:      {total} total  ({empty} empty, {syntax_errors} syntax errors, {verifiable} verifiable)")
    lines.append(f"Valid code: {100*verifiable/max(1,total):.1f}%")
    lines.append(f"Elapsed:    {elapsed:.2f}s")
    lines.append("")
    lines.append("Property pass-rates (over verifiable plans):")
    for name in prop_order:
        p = per_prop_pass.get(name, 0)
        f_ = per_prop_fail.get(name, 0)
        tot = p + f_
        pct = 100 * p / max(1, tot)
        bar = "█" * int(pct / 5) + "·" * (20 - int(pct / 5))
        lines.append(f"  {name:<45} {bar} {pct:5.1f}%  ({p}/{tot})")

    if per_cat:
        lines.append("")
        lines.append("Per-category pass-rates:")
        for cat in sorted(per_cat):
            lines.append(f"  · {cat}  (n={per_cat_totals.get(cat, 0)})")
            for name in prop_order:
                if name not in per_cat[cat]:
                    continue
                d = per_cat[cat][name]
                p = d["pass"]; tot = p + d["fail"]
                lines.append(f"      {name:<45} {100*p/max(1,tot):5.1f}%  ({p}/{tot})")

    lines.append("")
    lines.append(f"Annotated plans → {annotated_path}")
    lines.append(f"Summary CSV    → {summary_csv}")

    report = "\n".join(lines)
    with open(summary_txt, "w") as fh_txt:
        fh_txt.write(report + "\n")
    print(report)

    return {
        "total": total,
        "empty": empty,
        "syntax_errors": syntax_errors,
        "verifiable": verifiable,
        "per_prop_pass": per_prop_pass,
        "per_prop_fail": per_prop_fail,
    }


# A deterministic sort that puts P0, P1, …  before any non-P-prefixed names
def _prop_sort_key(name: str):
    m = re.match(r"^P(\d+)", name)
    return (0, int(m.group(1))) if m else (1, name)


# ── CLI ────────────────────────────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    ap.add_argument("--input", required=True, help="jsonl of plans")
    ap.add_argument("--prompts", default=None, help="webmall_prompts.jsonl (optional)")
    ap.add_argument("--expected-stores", default=",".join(DEFAULT_EXPECTED_STORES),
                    help="comma-separated list of expected shop URLs")
    ap.add_argument("--outdir", default="results", help="output directory (default: results/)")
    args = ap.parse_args(argv)

    expected_stores = [s.strip() for s in args.expected_stores.split(",") if s.strip()]

    if not os.path.exists(args.input):
        print(f"[error] input not found: {args.input}", file=sys.stderr)
        return 2

    verify_file(args.input, args.prompts, expected_stores, args.outdir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
