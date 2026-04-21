"""
run_spec_proposer_demo.py — Demonstrate LLM-generated task-specific properties.

For each of N sample tasks from webmall_prompts.jsonl, prompt an LLM (via
planner_adapter) to propose task-specific property checks using the prompt
template in spec_proposer.build_proposer_prompt.  Compile them in a
restricted namespace, then validate against known-good and known-bad plans
from the existing jsonl runs.

Emits:
  * results/spec_proposer/proposals.jsonl  — one line per (task_id, attempt)
    with raw LLM output + accepted/rejected status per check
  * results/spec_proposer/summary.md       — aggregate acceptance rates +
    examples of accepted checks

Usage:
    python run_spec_proposer_demo.py \\
      --prompts webmall_prompts.jsonl \\
      --good-plans webmall_plan_gpt-5.1_0.0_Example_True.jsonl \\
      --bad-plans  webmall_plan_deepseek-coder-6.7b-instruct_0.0_Example_False.jsonl \\
      --model gpt-4o-mini \\
      --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Load .env the same way the experiment runner does
def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    for c in [
        os.environ.get("FV_ENV_FILE"),
        os.path.join(os.getcwd(), ".env"),
        os.path.abspath(os.path.join(here, "..", ".env")),
        os.path.abspath(os.path.join(here, "..", "..", ".env")),
        os.path.abspath(os.path.join(here, "..", "..", "WebMall", ".env")),
    ]:
        if c and os.path.exists(c):
            load_dotenv(c, override=False)
            return

_load_dotenv_if_available()

from planner_adapter import make_openai_planner, make_anthropic_planner
from spec_proposer import (
    build_proposer_prompt,
    parse_and_compile_proposals,
    validate_checks,
)


def _make_generator(provider: str, model: str):
    """Return a generate(prompt: str) -> str callable."""
    # The planner_adapter callable signature is (task, previous, feedback); we
    # adapt to a single-prompt generator by passing the prompt as the task.
    if provider == "openai":
        p = make_openai_planner(
            model=model,
            temperature=0.2,
            system_prompt=(
                "You are a formal-verification engineer writing static checkers "
                "for LLM-generated plans. Output ONLY Python source code."
            ),
        )
    elif provider == "anthropic":
        p = make_anthropic_planner(
            model=model,
            temperature=0.2,
            system_prompt=(
                "You are a formal-verification engineer writing static checkers "
                "for LLM-generated plans. Output ONLY Python source code."
            ),
        )
    else:
        raise ValueError(f"unknown provider: {provider}")

    def gen(prompt: str) -> str:
        return p(prompt, previous_plan=None, feedback=None)
    return gen


def _load_plans_by_idx(path: str) -> list[tuple[str, str]]:
    """Load (id, clean_response) pairs from a plans jsonl."""
    out: list[tuple[str, str]] = []
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            tid = r.get("id", "")
            code = r.get("clean_response") or r.get("response") or ""
            out.append((tid, code))
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--good-plans", required=True,
                    help="jsonl whose clean_response fields are known-good plans "
                         "(typically the gpt-5.1 run)")
    ap.add_argument("--bad-plans", required=True,
                    help="jsonl whose clean_response fields are known-bad plans "
                         "(typically a deepseek-6.7b or similar failing run)")
    ap.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--outdir", default="results/spec_proposer")
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    out_jsonl = os.path.join(args.outdir, "proposals.jsonl")
    out_md    = os.path.join(args.outdir, "summary.md")
    open(out_jsonl, "w").close()

    with open(args.prompts) as f:
        prompts = [json.loads(l) for l in f if l.strip()]
    good = _load_plans_by_idx(args.good_plans)
    bad  = _load_plans_by_idx(args.bad_plans)

    generator = _make_generator(args.provider, args.model)

    n_checks_total = 0
    n_accepted = 0
    n_trivial = 0
    n_crashing = 0
    n_tasks = 0
    accepted_examples: list[dict] = []

    for i, row in enumerate(prompts[: args.limit], 1):
        task_id = row.get("id", f"idx{i}")
        task_prompt = row.get("prompt", "")
        # Use the i-th good and bad plan as validation corpus (tiny sample)
        good_sample = [(f"good_{i}", good[i - 1][1])] if i - 1 < len(good) and good[i - 1][1].strip() else []
        bad_sample  = [(f"bad_{i}",  bad[i - 1][1])]  if i - 1 < len(bad)  and bad[i - 1][1].strip()  else []
        if not good_sample or not bad_sample:
            continue

        n_tasks += 1
        proposer_prompt = build_proposer_prompt(task_prompt)
        try:
            raw = generator(proposer_prompt)
        except Exception as e:
            print(f"[{i}/{args.limit}] {task_id}: generator error: {e}", file=sys.stderr)
            continue

        candidates = parse_and_compile_proposals(raw)
        n_checks_total += len(candidates)

        reports = validate_checks(candidates, good_plans=good_sample, bad_plans=bad_sample)
        accepted = [r for r in reports if r.accepted]
        n_accepted += len(accepted)
        n_trivial += sum(1 for r in reports if r.reason.startswith("trivially"))
        n_crashing += sum(1 for r in reports if r.reason == "raises or bad return type")

        # one record per task
        with open(out_jsonl, "a") as f:
            f.write(json.dumps({
                "task_id": task_id,
                "raw": raw[:5000],
                "n_proposed": len(candidates),
                "n_accepted": len(accepted),
                "reports": [
                    {
                        "name": r.check.name,
                        "accepted": r.accepted,
                        "reason": r.reason,
                        "source": r.check.source,
                    }
                    for r in reports
                ],
            }) + "\n")

        for r in accepted[:1]:
            accepted_examples.append({
                "task_id": task_id,
                "name": r.check.name,
                "source": r.check.source,
            })

        print(f"[{i}/{args.limit}] {task_id}: proposed {len(candidates)}, "
              f"accepted {len(accepted)}")

    # ── summary markdown ─────────────────────────────────────────────────────
    lines: list[str] = []
    lines.append("# LLM-generated task-specific property checks — demo run")
    lines.append("")
    lines.append(f"Model: `{args.provider}:{args.model}`")
    lines.append(f"Tasks evaluated: {n_tasks}")
    lines.append(f"Total proposals compiled: {n_checks_total}")
    lines.append(f"Accepted (discriminates good/bad): {n_accepted} "
                 f"({100*n_accepted/max(1,n_checks_total):.1f}%)")
    lines.append(f"Rejected — trivially pass/fail: {n_trivial}")
    lines.append(f"Rejected — raises or bad return type: {n_crashing}")
    lines.append("")
    if accepted_examples:
        lines.append("## Example accepted checks")
        for ex in accepted_examples[:5]:
            lines.append(f"### `{ex['name']}` — from task `{ex['task_id']}`")
            lines.append("```python")
            lines.append(ex["source"])
            lines.append("```")
            lines.append("")

    with open(out_md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))
    print(f"\n→ {out_md}")
    print(f"→ {out_jsonl}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
