"""
run_replan_experiment.py — End-to-end experiment runner.

For each task in a webmall_prompts.jsonl file, runs one of three conditions:
  * ``vanilla``        — single plan, no re-planning
  * ``nl-critique``    — generic "check your plan and revise" baseline (Mar 31)
  * ``fv-guided``      — our approach: plan → verify → re-plan with property
                         counterexamples until convergence or max_iterations

Writes one jsonl per task id to the output directory: full iteration trace,
final plan, convergence flag.  Aggregate stats are written to summary.csv.

Example
-------
    export OPENAI_API_KEY=sk-...
    python run_replan_experiment.py \\
        --prompts "/home/ray/Downloads/drive-download-.../webmall_prompts.jsonl" \\
        --model gpt-5.1 --provider openai \\
        --condition fv-guided --max-iterations 3 \\
        --outdir results/experiments/gpt51_fv \\
        --limit 20             # start small; drop --limit for full 273-task run

Rely on ``--dry-run`` to verify plumbing without spending tokens; uses a mock
planner that returns a deterministic broken plan then a fixed one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Auto-load .env so OPENAI_API_KEY / ANTHROPIC_API_KEY flow in without
# requiring the user to source anything.  We look in (first hit wins):
#   1. $FV_ENV_FILE (explicit override)
#   2. ./.env                            (cwd)
#   3. <this file>/../.env               (formal_verification/../.env)
#   4. <this file>/../../.env            (llm_stl_benchmark/../.env — project root)
#   5. <this file>/../../../WebMall/.env (sibling WebMall checkout)
def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.environ.get("FV_ENV_FILE"),
        os.path.join(os.getcwd(), ".env"),
        os.path.abspath(os.path.join(here, "..", ".env")),
        os.path.abspath(os.path.join(here, "..", "..", ".env")),
        os.path.abspath(os.path.join(here, "..", "..", "WebMall", ".env")),
    ]
    for c in candidates:
        if c and os.path.exists(c):
            load_dotenv(c, override=False)
            return

_load_dotenv_if_available()

from replan_loop import run_verified_loop, dump_loop_result_jsonl
from baseline_nl_critique import run_nl_critique_loop


DEFAULT_EXPECTED_STORES = [
    "http://localhost:8081",
    "http://localhost:8082",
    "http://localhost:8083",
    "http://localhost:8084",
]


def _load_prompts(path: str, limit: Optional[int]) -> list[dict]:
    rows: list[dict] = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
    return rows


def _build_planner(provider: str, model: str, temperature: float, dry_run: bool) -> Callable[..., str]:
    if dry_run:
        # alternate broken → fixed → fixed…  (exercises the loop deterministically)
        broken = 'open_page("http://localhost:8081")\n'
        fixed = (
            'stores = ["http://localhost:8081","http://localhost:8082","http://localhost:8083","http://localhost:8084"]\n'
            'results = []\n'
            'for store in stores:\n'
            '    url = search_on_page(store, "widget")\n'
            '    if url is not None:\n'
            '        results.append(url)\n'
            'open_page("http://localhost:8085/")\n'
            'fill_text_field("Type your final answer here...", "###".join(results) if results else "Done")\n'
            'press_button("Submit Final Result")\n'
        )
        state = {"n": 0}
        def planner(task_prompt, previous_plan=None, feedback=None):
            state["n"] += 1
            return broken if state["n"] == 1 else fixed
        return planner

    if provider == "openai":
        from planner_adapter import make_openai_planner
        return make_openai_planner(model=model, temperature=temperature)
    if provider == "anthropic":
        from planner_adapter import make_anthropic_planner
        return make_anthropic_planner(model=model, temperature=temperature)
    raise ValueError(f"unknown provider: {provider}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True, help="webmall_prompts.jsonl")
    ap.add_argument("--condition", choices=["vanilla", "nl-critique", "fv-guided"],
                    default="fv-guided")
    ap.add_argument("--provider", choices=["openai", "anthropic"], default="openai")
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="run only the first N tasks")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="use the deterministic mock planner; no API calls")
    ap.add_argument("--expected-stores", default=",".join(DEFAULT_EXPECTED_STORES))
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    traces_path = os.path.join(args.outdir, "traces.jsonl")
    summary_csv = os.path.join(args.outdir, "summary.csv")
    # start fresh
    open(traces_path, "w").close()

    prompts = _load_prompts(args.prompts, args.limit)
    expected_stores = [s.strip() for s in args.expected_stores.split(",") if s.strip()]

    planner = _build_planner(args.provider, args.model, args.temperature, args.dry_run)

    n_converged = 0
    iter_counts: list[int] = []
    t0 = time.time()

    for i, row in enumerate(prompts, 1):
        task_id = row.get("id", f"idx{i}")
        task_prompt = row.get("prompt", "")
        try:
            if args.condition == "vanilla":
                # exactly one plan, no re-plan
                res = run_verified_loop(
                    task_prompt=task_prompt, planner=planner,
                    max_iterations=1, expected_stores=expected_stores,
                    condition="vanilla",
                )
            elif args.condition == "nl-critique":
                res = run_nl_critique_loop(
                    task_prompt=task_prompt, planner=planner,
                    max_iterations=args.max_iterations,
                    expected_stores=expected_stores,
                    verifier_aware=True,
                )
            else:  # fv-guided
                res = run_verified_loop(
                    task_prompt=task_prompt, planner=planner,
                    max_iterations=args.max_iterations,
                    expected_stores=expected_stores,
                    condition="fv-guided",
                )
        except Exception as e:
            print(f"[warn] {task_id}: {type(e).__name__}: {e}", file=sys.stderr)
            continue

        dump_loop_result_jsonl(res, traces_path, task_id=task_id)
        if res.converged:
            n_converged += 1
        iter_counts.append(len(res.iterations))

        if i % 10 == 0 or i == len(prompts):
            rate = 100 * n_converged / i
            print(f"  [{i:>4}/{len(prompts)}] converged={n_converged} ({rate:.1f}%)  "
                  f"mean_iters={sum(iter_counts)/len(iter_counts):.2f}  "
                  f"elapsed={time.time()-t0:.1f}s")

    # Write aggregate summary
    with open(summary_csv, "w") as fh:
        fh.write("condition,model,total,converged,converged_pct,mean_iterations\n")
        pct = 100 * n_converged / max(1, len(iter_counts))
        mean_iters = sum(iter_counts) / max(1, len(iter_counts))
        fh.write(f"{args.condition},{args.model},{len(iter_counts)},{n_converged},{pct:.2f},{mean_iters:.3f}\n")

    print()
    print(f"Condition:   {args.condition}")
    print(f"Model:       {args.model}")
    print(f"Tasks run:   {len(iter_counts)}")
    print(f"Converged:   {n_converged} ({100*n_converged/max(1,len(iter_counts)):.1f}%)")
    print(f"Mean iters:  {sum(iter_counts)/max(1,len(iter_counts)):.2f}")
    print(f"Traces →     {traces_path}")
    print(f"Summary →    {summary_csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
