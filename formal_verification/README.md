# Formal verification for WebMall plans

Static-analysis tools that verify LLM-generated Python plans against structural
properties, plus an iterative re-planning loop that feeds verification failures
back to the planner LLM.

Paper: *Constraining LLM Agent Trajectories with Formal Verification*
(NeurIPS 2026 submission).

## What's here

```
verifier.py              AST + CFG path enumerator; DSL vocabulary (14 WebMall
                         functions) and parameter signatures for kwarg
                         normalization. Inlines top-level `def plan(): plan()`.
properties.py            7 property checkers (P0..P6). See "Properties" below.
run_demo.py              Demo on 5 hand-written plans (3 correct, 2 mutants).
run_formal_verification  Batch-verifies a jsonl of plans; writes annotated
  .py                    jsonl + CSV + per-category summary.
aggregate_table1.py      Builds Table 1 (vanilla pass rates × 6 model runs).

spec_proposer.py         Prompts an LLM to generate task-specific property
                         checks; compiles + validates them in a safe namespace;
                         rejects trivial or crashing checks.
replan_loop.py           plan → verify → re-plan loop (max K iterations).
baseline_nl_critique.py  "Check your plan and revise" baseline from the Mar 31
                         research plan.
planner_adapter.py       OpenAI / Anthropic planner callables.
run_replan_experiment.py End-to-end experiment runner (one condition × n tasks).
                         Supports --bootstrap-plans to reuse an existing
                         plan-jsonl as iter-0 (no API cost for first plan).
aggregate_table2.py      Builds Table 2 (3 conditions × GPT-5.1).
plot_convergence.py      Figures 1 & 2 from the traces.

tests/test_replan_loop.py  6 smoke tests; `python tests/test_replan_loop.py`.

paper/section_experiments.tex   LaTeX draft of §2.1 and §2.2.
paper/figures/                   figure1_convergence.pdf,
                                 figure2_per_property.pdf.
results/                         per-file annotated jsonls + summary CSVs.
results/experiments/             per-condition traces + aggregated tables/figs.
```

## Properties

| # | Name | What it catches |
|---|------|-----------------|
| P0 | Uses only DSL / builtin functions | hallucinated DSL names (`go_to_checkout`, …) |
| P1 | Submit always called | every execution path contains `press_button("Submit Final Result")` |
| P2 | Solution field filled before submit | `fill_text_field` on the final-answer field precedes submit |
| P3 | All stores searched | each expected shop URL appears in a `search_on_page` call |
| P4 | None-returning results guarded | `Optional`-returning DSL results are None-checked before use |
| P5 | Solution page opened before submit | `open_page("http://localhost:8085/…")` precedes submit |
| P6 | Top-level code actually runs | not wrapped in a `def plan():` that is never invoked |

Each checker returns a `PropertyResult(name, passed, message, counterexample)`
— the counterexample path is fed back to the LLM when re-planning.

## Usage

### Verify a jsonl of existing plans
```bash
python run_formal_verification.py \
  --input webmall_plan_gpt-5.1_0.0_Example_True.jsonl \
  --outdir results
```
Writes `<name>.annotated.jsonl`, `<name>.summary.csv`, `<name>.summary.txt` into
`results/`. Per-category (Task-type) breakdown is included in the `.txt`.

### End-to-end re-plan experiment
```bash
# $OPENAI_API_KEY is auto-loaded from WebMall/.env or project-root .env
python run_replan_experiment.py \
  --prompts webmall_prompts.jsonl \
  --provider openai --model gpt-5.1 \
  --condition fv-guided --max-iterations 3 \
  --outdir results/experiments/gpt51_fv_guided

# save cost by starting from pre-generated plans (line-aligned with prompts):
python run_replan_experiment.py \
  --prompts webmall_prompts.jsonl \
  --bootstrap-plans webmall_plan_gpt-5.1_0.0_Example_True.jsonl \
  --provider openai --model gpt-5.1 \
  --condition fv-guided --max-iterations 3 \
  --with-example \                # <-- match the bootstrap plans' prompt mode
  --outdir results/experiments/gpt51_fv_guided_boot
```

The `--with-example` flag prepends a cheapest-price exemplar (in the current
WebMall DSL) to every user prompt, matching the team's "Example=True" notebook
prompt mode used to generate the jsonl plan files in `plan_docs/`. Use it when
bootstrapping from `*_Example_True.jsonl` so iter-1+ re-plans see the same
prompting distribution as iter-0; omit it for a clean ablation against the
no-example baseline.

Conditions:
- `vanilla` — one plan, no re-planning.
- `nl-critique` — Mar 31 baseline: "check your plan and revise" (no verifier output shared).
- `fv-guided` — our approach: verifier report + counterexamples back to the LLM.

### Build the paper tables / figures
```bash
python aggregate_table1.py   --dir results                     # Table 1 (vanilla × models)
python aggregate_table2.py   --dir results/experiments         # Table 2 (conditions × GPT-5.1)
python plot_convergence.py   --dir results/experiments         # Figures 1 & 2
```

### LLM-generated task-specific properties
```python
from spec_proposer import MockLLM, propose_and_validate
accepted = propose_and_validate(
    task_prompt=...,
    generate=MockLLM(),        # swap for a real LLM callable
    good_plans=[("gold", gold_plan_src)],
    bad_plans=[("mutant", broken_plan_src)],
)
# Then feed `accepted` into run_verified_loop(..., extra_checks=accepted)
```

## Key results

**Table 1.** Single-shot pass rates across 6 model runs (n=273 each). See
`results/table1.md`. Headline: every model has a distinct failure profile
(GPT-5.1 wraps 63% of plans in an uncalled `def plan():`; DeepSeek
hallucinates DSL; Qwen2.5-Coder never None-guards).

**Table 2.** GPT-5.1 × 3 conditions (n=273). See `results/experiments/table2.md`.
| Condition | Converged | Mean iters |
|---|---|---|
| vanilla | 1.5% | 1.00 |
| nl-critique | 0.7% | 2.99 |
| fv-guided | **75.5%** | 2.44 |

NL-critique baseline *underperforms* vanilla — unstructured self-critique
doesn't know what to fix.

## Integration points for the team

- **Emi**: plans stored in jsonl files are drop-in inputs to both
  `run_formal_verification.py` (static verification) and
  `run_replan_experiment.py --bootstrap-plans` (iter-0 for the re-plan loop).
  No changes needed to your notebook pipeline.
- **Alan**: `spec_proposer.propose_and_validate()` is the LLM-spec entry
  point. The safe-exec namespace and good/bad-plan validation are done;
  extend the prompt or validation criteria as needed.
- **Ray**: bootstrap experiments run with `--bootstrap-plans path/to/*.jsonl`.
  Use this for the fair head-to-head with Table 1.

## Caveats

- P3 uses a default expected-shops list of all 4 shops. Tasks that legitimately
  restrict search to a subset (e.g., "find in TechTalk and CamelCases only")
  produce benign P3 false positives. A per-task store-derivation step would
  eliminate these.
- For-loop path enumeration includes a "skip the loop entirely" branch. For
  non-empty literal iterables this is unsound, but we have not observed false
  positives from this in practice.
- Function inlining picks one representative body path per call site (the
  busiest by action count). True multi-branch enumeration inside called
  functions would require propagating alternatives through `_calls_in_expr`.
