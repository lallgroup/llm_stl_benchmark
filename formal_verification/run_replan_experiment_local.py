"""
run_replan_experiment_local.py — End-to-end experiment runner.

# uses the locally deployed small LLM

For each task in a webmall_prompts.jsonl file, runs one of three conditions:
  * ``vanilla``        — single plan, no re-planning
  * ``nl-critique``    — generic "check your plan and revise" baseline (Mar 31)
  * ``fv-guided``      — our approach: plan → verify → re-plan with property
                         counterexamples until convergence or max_iterations

Writes one jsonl per task id to the output directory: full iteration trace,
final plan, convergence flag.  Aggregate stats are written to summary.csv.

Example
-------
    python run_replan_experiment.py \\
        --prompts "/home/ray/Downloads/drive-download-.../webmall_prompts.jsonl" \\
        --model Qwen/Qwen3-Coder-30B-A3B-Instruct \\
        --condition fv-guided --max-iterations 3 \\
        --outdir results/experiments/qwen3-coder-30b-a3b-instruct_fv \\
        --limit 20             # start small; drop --limit for full 273-task run
        --example              # prepend the few-shot example from small_models_on_webmall_planning.py to iter-0 prompts

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

from small_models_on_webmall_planning import ChatModel, standardize_parameters, setup_environment, get_first_valid, example as FEW_SHOT_EXAMPLE

setup_environment()

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


def _load_bootstrap_plans(path: str) -> list[str]:
    """Load pre-computed iter-0 plans from an existing plans jsonl, indexed by
    line number. The webmall_prompts.jsonl and the team's plan jsonls are
    aligned line-by-line (same (id, seed) order), so position matching is the
    correct join — (id, seed) is not unique in the prompts file.
    """
    plans: list[str] = []
    with open(path) as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                plans.append("")
                continue
            code = row.get("clean_response") or row.get("response") or ""
            plans.append(code)
    return plans


def _build_planner(model: str, temperature: float, dry_run: bool, use_example: bool = False, tensor_parallel_size=4):
    """Returns (planner_callable, token_counter).

    token_counter is a dict {"input_tokens": int, "output_tokens": int} that
    accumulates token counts across all planner calls.  Reset between tasks by
    calling token_counter["input_tokens"] = token_counter["output_tokens"] = 0,
    or use the helper reset_counter(token_counter).
    For --dry-run, the counter stays at zero (no real model calls).
    """
    token_counter = {"input_tokens": 0, "output_tokens": 0}

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
        return planner, token_counter

    chat_model = ChatModel(model, standardize_parameters(model, temperature, 0, {}), tensor_parallel_size=tensor_parallel_size)

    # wrapped model should have the property that planner(task_prompt, previous_plan=None, feedback=None) -> plan_src
    def wrapped_model(task_prompt, previous_plan=None, feedback=None):
        parts = [task_prompt]
        if use_example and previous_plan is None:
            parts += ["\n", FEW_SHOT_EXAMPLE]
        if previous_plan is not None:
            parts += ["\n## Previous plan:\n", previous_plan]
        if feedback is not None:
            parts += ["\n## Feedback:\n", feedback]
        raw_response, in_tok, out_tok = chat_model.chat_with_tokens("".join(parts))
        token_counter["input_tokens"] += in_tok
        token_counter["output_tokens"] += out_tok
        plan_src = get_first_valid(raw_response)
        if plan_src is None:
            raise ValueError(f"No valid plan found in response: {raw_response}")
        return plan_src

    return wrapped_model, token_counter



def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompts", required=True, help="webmall_prompts.jsonl")
    ap.add_argument("--condition", choices=["vanilla", "nl-critique", "fv-guided"],
                    default="fv-guided")
    ap.add_argument("--model", default="Qwen/Qwen3-Coder-30B-A3B-Instruct")
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--max-iterations", type=int, default=3)
    ap.add_argument("--limit", type=int, default=None, help="run only the first N tasks")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--example", action="store_true",
                    help="prepend the few-shot example from small_models_on_webmall_planning.py "
                         "to iter-0 prompts")
    ap.add_argument("--dry-run", action="store_true",
                    help="use the deterministic mock planner; no API calls")
    ap.add_argument("--expected-stores", default=",".join(DEFAULT_EXPECTED_STORES))
    ap.add_argument("--bootstrap-plans", default=None,
                    help="path to an existing plans jsonl; iter-0 plans are loaded "
                         "from it (matched by task id), saving one API call per task. "
                         "Use this to run nl-critique / fv-guided against the team's "
                         "pre-generated vanilla plans.")
    ap.add_argument("--gpus", default=4, type=int)
    args = ap.parse_args(argv)

    os.makedirs(args.outdir, exist_ok=True)
    traces_path = os.path.join(args.outdir, "traces.jsonl")
    summary_csv = os.path.join(args.outdir, "summary.csv")
    # start fresh
    open(traces_path, "w").close()

    prompts = _load_prompts(args.prompts, args.limit)
    expected_stores = [s.strip() for s in args.expected_stores.split(",") if s.strip()]

    planner, token_counter = _build_planner(args.model, args.temperature, args.dry_run, use_example=args.example, tensor_parallel_size=args.gpus)

    # If bootstrapping, wrap the planner so iter-0 returns the pre-computed plan
    # for that task. We index by line number (position), not task id — the
    # prompts jsonl and plan jsonls are aligned line-by-line (same (id, seed)
    # order), and (id, seed) is not unique in the prompts file.
    bootstrap_plans: list[str] = []
    if args.bootstrap_plans:
        bootstrap_plans = _load_bootstrap_plans(args.bootstrap_plans)
        print(f"Bootstrap plans loaded: {len(bootstrap_plans)} plans from {args.bootstrap_plans}")
        if len(bootstrap_plans) < len(prompts):
            print(f"[warn] fewer bootstrap plans ({len(bootstrap_plans)}) than prompts "
                  f"({len(prompts)}); remaining tasks will call the real planner for iter-0")

    def _wrap_planner_for_task(task_idx: int) -> Callable[..., str]:
        """If we have a bootstrap plan for this task, the first planner call
        returns it verbatim (no API hit); subsequent calls go to the real LLM."""
        boot = bootstrap_plans[task_idx] if task_idx < len(bootstrap_plans) else ""
        if not boot.strip():
            return planner
        state = {"used": False}
        def wrapped(task_prompt, previous_plan=None, feedback=None):
            if not state["used"] and previous_plan is None and feedback is None:
                state["used"] = True
                return boot
            return planner(task_prompt, previous_plan=previous_plan, feedback=feedback)
        return wrapped

    n_converged = 0
    iter_counts: list[int] = []
    t0 = time.time()

    for i, row in enumerate(prompts, 1):
        task_id = row.get("id", f"idx{i}")
        task_prompt = row.get("prompt", "")
        task_planner = _wrap_planner_for_task(i - 1)  # 0-indexed
        token_counter["input_tokens"] = 0
        token_counter["output_tokens"] = 0
        try:
            if args.condition == "vanilla":
                # exactly one plan, no re-plan
                res = run_verified_loop(
                    task_prompt=task_prompt, planner=task_planner,
                    max_iterations=1, expected_stores=expected_stores,
                    condition="vanilla",
                )
            elif args.condition == "nl-critique":
                res = run_nl_critique_loop(
                    task_prompt=task_prompt, planner=task_planner,
                    max_iterations=args.max_iterations,
                    expected_stores=expected_stores,
                    verifier_aware=True,
                )
            else:  # fv-guided
                res = run_verified_loop(
                    task_prompt=task_prompt, planner=task_planner,
                    max_iterations=args.max_iterations,
                    expected_stores=expected_stores,
                    condition="fv-guided",
                )
        except Exception as e:
            print(f"[warn] {task_id}: {type(e).__name__}: {e}", file=sys.stderr)
            continue

        res.total_input_tokens = token_counter["input_tokens"]
        res.total_output_tokens = token_counter["output_tokens"]
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
