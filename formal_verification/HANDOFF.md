# Handoff — Constraining LLM Agent Trajectories with Formal Verification

**For: a new chat / new agent picking up this work.** Self-contained context dump. Last updated after the v2 prompts patch, the cleanup commit, and the BrowserGym Optional-types merge.

NeurIPS 2026 submission, deadline **May 6, 2026**. Today is in the final 2 weeks. The current author of this doc is Ray (`rayk99801@gmail.com`); collaborators are Emi Soroka (`emiko@me.com`, lead) and Alan Xiao (`alanxiao211@gmail.com`).

---

## Repo states (most recent commits)

| Repo | Branch | HEAD | What's there |
|---|---|---|---|
| `lallgroup/llm_stl_benchmark` | `vibe-formal-verification` | `aa4405f` | All experiment code + traces + figures + paper draft |
| `lallgroup/llm_stl_benchmark` | `main` | `aa4405f` (just fast-forwarded) | Same — main now matches vibe |
| `elsoroka/BrowserGym` | `main` | `9000c3a` | Optional return types fixed across all 9 planner DSL actions |

---

## TL;DR — Where the project actually stands

We claim that "formal verification of LLM-generated agent plans drives convergence on a long-horizon benchmark." The empirical story is real but **weaker than the title suggests**, and a critical piece — actually executing the verified plans — has not been done. The paper is in real danger of getting reviewed as "you wrote 7 hardcoded checks and told the LLM what to fix."

### Headline numbers (GPT-5.1, n=273 WebMall tasks)

| Condition | Convergence (all 7 properties pass at iter-K=2) |
|---|---|
| vanilla (single-shot) | 1.5% |
| nl-critique baseline ("revise your plan") | 0.7% (regresses) |
| **fv-guided (structured counterexample feedback)** | **75.5%** |
| oracle-NL (FV failures rephrased as prose, no line numbers) | **47.5%** ← **KEY THREAT** |

**The real, awkward finding:** `oracle-nl ≈ fv-guided` on GPT-5.1 bootstrap (47.5% vs 46.4%) — meaning **structured counterexamples don't beat well-written prose feedback** on a strong model. The "formal" framing is doing less work than the "specific" framing. A reviewer will hammer this.

### What's actually defensible right now

1. **Specific failure feedback >> generic self-critique** (10-50× lift). Robust across prompts.
2. **A small structural-property library can be built once, applied to a whole benchmark, and produces useful signal.** Hand-coding 7 properties takes a day.
3. **LLM-proposed task-specific properties have ~36% acceptance rate** when validated against good/bad plans (15-task pilot). Scales without human authoring.
4. **Catching the documentation-vs-implementation gap** (the `search_on_page -> str` lie that should have been `-> str | None`): static analysis grounded in real semantics catches a class of bugs the LLM cannot avoid given the prompt it sees.

### What's not defensible

1. "Formal verification" is doing the same job as "specific NL feedback" on strong models.
2. We've never executed a plan. The paper title says "agent trajectories" but we only check static properties of plan code.
3. P0–P6 were chosen by hand to match WebMall failure modes — a reviewer will say we're encoding the answer.

---

## Code & data layout

```
/home/ray/formalverification/
├── llm_stl_benchmark/         (lallgroup/llm_stl_benchmark, branch vibe-formal-verification)
│   ├── formal_verification/
│   │   ├── verifier.py            # AST + CFG path enumeration; DSL_FUNCTIONS / DSL_RETURNS_OPTIONAL / DSL_SIGNATURES
│   │   ├── properties.py          # P0–P6 checkers
│   │   ├── replan_loop.py         # plan→verify→re-plan loop
│   │   ├── baseline_nl_critique.py # nl-critique + oracle-NL feedback builders
│   │   ├── spec_proposer.py       # LLM-generated property functions, safe-exec, dry-run validation
│   │   ├── planner_adapter.py     # OpenAI / Anthropic / vLLM-via-base-url planner callables; EXAMPLE_PLAN_BLOCK
│   │   ├── run_formal_verification.py   # batch-verify a jsonl of plans
│   │   ├── run_replan_experiment.py     # the main experiment runner
│   │   ├── run_replan_experiment_local.py # vLLM-backed variant for Marlowe (Emi)
│   │   ├── run_spec_proposer_demo.py     # the §2.3 demo
│   │   ├── small_models_on_webmall_planning.py  # Marlowe model loader (Emi)
│   │   ├── aggregate_table1.py / aggregate_table2.py / plot_convergence.py / plot_table1.py
│   │   ├── patch_prompts_signatures.py   # text-edits an existing prompts jsonl to fix sig lies
│   │   ├── tests/test_replan_loop.py     # 6 smoke tests, all green
│   │   ├── submit_replanner_qwen_7b.sbatch / submit_replanner_qwen_30b.sbatch  # Marlowe
│   │   ├── paper/section_experiments.tex + paper/figures/   # LaTeX draft for §2.1–§2.3
│   │   ├── README.md             # one-page orientation
│   │   └── results/              # all traces + tables + figures (committed)
│   ├── plan_docs/
│   │   ├── webmall_prompts.jsonl          # the original prompts (with the sig lie)
│   │   ├── webmall_prompts_v2.jsonl       # patched: -> str | None advertised correctly
│   │   ├── webmall_plan_*_*.jsonl         # vanilla generations from Qwen, DeepSeek, GPT-5.1
│   │   └── webmall_plan_Qwen3-Coder-30B-A3B-Instruct_0.7_Example_True.jsonl  # NEW (Emi, Marlowe)
│   └── hardcoded_formal_verification/    # Alan's parallel implementation (untouched; coordinate before merging)
├── WebMall/                       # Emi's WebMall fork
│   ├── Browsergym/                # github.com/elsoroka/BrowserGym, branch main
│   │   └── browsergym/core/src/browsergym/core/action/functions.py
│   │       # ↑ has my LOCAL commit 3523baa fixing return-type annotations to PEP-604 unions.
│   │       # NOT pushed; coordinate with Emi before pushing to elsoroka/BrowserGym.
│   ├── AgentLab/.../webmall_generic_agent/planning_agent.py
│   │       # ↑ the live executor: exec()s a plan in a thread with the DSL bound to executor-LLM helpers
│   ├── docker_all/                # Docker Compose stack for the 4 shops + solution page
│   └── .env                       # OPENAI_API_KEY lives here; auto-loaded by run_replan_experiment.py
├── tasks/todo.md                  # earlier project plan; partially out-of-date
└── HANDOFF.md                     # this document
```

### Key git facts
- **lallgroup/llm_stl_benchmark** branch `vibe-formal-verification` has all the formal-verification work. Push as user `ray <rayk99801@gmail.com>`. Multiple authors (Ray, Alan, Emi) push here; **always `git pull --rebase` before pushing**.
- **elsoroka/BrowserGym** branch `main`, commit `3523baa` is local-only. Either push it (if Ray has access) or hand the patch to Emi.
- **Compute keys** — `OPENAI_API_KEY` lives in `WebMall/.env`. `run_replan_experiment.py` auto-loads from there.
- Total OpenAI spend so far on this project is approximately $30–60 (rough estimate from the runs in `results/experiments/`).

---

## The verifier as it stands today

7 structural properties over the AST + CFG of a plan:

| ID | Name | What it catches |
|---|---|---|
| P0 | Uses only DSL / builtin functions | Hallucinated DSL like `go_to_checkout`. |
| P1 | Submit always called | Every CFG path reaches `press_button("Submit Final Result")`. |
| P2 | Solution field filled before submit | `fill_text_field(<solution-field>, …)` precedes the submit call. |
| P3 | All stores searched | Each expected shop URL appears as a `search_on_page` arg, **including the variable-iterable pattern** (`stores = [...]; for x in stores:`) — fixed in `46beacd`. |
| P4 | None-returning results guarded | Every `Optional`-bound variable is None-checked, sanitized via `if x is None: x = default`, or used in `x if x is not None else …`. |
| P5 | Solution page opened before submit | `open_page("http://localhost:8085/")` precedes the submit call. |
| P6 | Top-level code actually runs | Catches the `def plan(): ...` -wrapper-without-call pattern. |

### Recently fixed (post-experiments)

1. **Function inlining** in `verifier.py::get_all_paths`: when a plan defines `def plan():` and calls `plan()` at top level, we inline body paths so subsequent property checks see the DSL calls. (Without this, GPT-5.1's "wrap in def, then call" plans were spuriously P1-failing.)
2. **kwargs → positional normalization** via `DSL_SIGNATURES`: `press_button(button_description="X")` is now indistinguishable from `press_button("X")`.
3. **P3 variable resolution**: handles `webshops = [...]; for x in webshops:`. **Without this fix, Qwen3-Coder-30B's P3 was spuriously 0%; with it, 88.6%.**
4. **P4 sanitization patterns**: now recognizes `if x is None: x = default` and `x if x is not None else default` as valid guards.
5. **DSL Optional return types** (BrowserGym fork, merged into `elsoroka/BrowserGym @ main` as `9000c3a`): all 9 planner-facing actions now declare `Optional[T]` so `inspect.signature` propagates the correct return type into the planner prompt. See "Critical caveat" below.
6. **Cleanup commit** (`aa4405f` on `lallgroup/llm_stl_benchmark`): removed smoke-test directories (`gpt51_*_smoke*`), dryrun outputs (`dryrun/`, `boot_dryrun/`), and 5 empty `.log` files. The full-run trace directories used by Tables 1–2 are unaffected.
7. **Branch state** (`aa4405f`): `vibe-formal-verification` and `main` are in sync after a fast-forward merge. Future work can land on either; keeping the branch as the active development line is fine.

### Verifier impact analysis (asked: "are old results invalidated?")

Re-verified all 7 vanilla model jsonls and all 3 GPT-5.1 bootstrap traces with the patched verifier:

- **Table 1** (vanilla pass rates): 4 of 7 rows unchanged; Qwen3.5-9B (ex=F) +0.5pp on P3; GPT-5.1 +3.3pp on P4 (24.91% → 28.21%); Qwen3-Coder-30B (a *new* row from Emi) is the model that benefited most (P3 went from spuriously 0% to 88.6%).
- **Table 2** (re-plan conditions): **zero re-classifications** of converged. Bootstrap fv-guided 46.4% → 46.4%, oracle-nl 39.5% → 39.5%, nl-critique 10.6% → 10.6%. The patched verifier produces the exact same final-plan verdict on every existing trace.

So: don't throw out old results; add a methods footnote describing the verifier patch and the small Table 1 deltas.

### Critical caveat: DSL prompt vs implementation gap (FIXED on remote, but old jsonls still affected)

The planner prompt used to advertise:
```
search_on_page(...) -> str
extract_information_from_page(...) -> str
press_button(...) -> bool        # etc., 9 functions total
```
but the actual implementations return `Optional[T]`. Python interprets `-> str or None` as `-> str` at def-time (Boolean OR of types), so `inspect.signature` rendered the non-Optional type into the prompt. Plans dutifully wrote `if x != "":` guards that don't catch None and would crash at runtime.

**Status (now fixed in source):**

- `elsoroka/BrowserGym @ main` is at `9000c3a`. The fix has two layers (Emi merged her own commits `f6bfbd4`/`8b0d059`/`d6f5e88` for `search_on_page` and `extract_information_from_page`; Ray merged `9000c3a` for the other 7). All 9 planner-facing actions now correctly declare `Optional[str]` / `Optional[bool]`.
- Verified: `inspect.signature(search_on_page)` now renders `-> Optional[str]`. Freshly generated planner prompts will be correct.

**What still needs handling:**

- All existing vanilla jsonls in `plan_docs/webmall_plan_*.jsonl` were generated against the *buggy* prompt. A fresh vanilla regeneration against the corrected prompt (or against the text-patched `webmall_prompts_v2.jsonl`) would likely raise vanilla P4 and shrink the FV-guided gap on P4. That's a more honest baseline for the paper.
- For ongoing experiments **without** regeneration, point `--prompts ../plan_docs/webmall_prompts_v2.jsonl` (273 rows × 9 substitutions = 2,457 textual edits already applied via `formal_verification/patch_prompts_signatures.py`, committed at `aa4405f`).

---

## Experiment inventory

All under `formal_verification/results/experiments/`:

- `gpt51_vanilla/` — single-shot, n=271 (process killed at 271/273), 1.5% converged
- `gpt51_nl_critique/` — generic critique baseline, n=273, 0.7% converged
- `gpt51_fv_guided/` — FV-guided from-scratch (no example), n=273, **75.5% converged**, mean 2.44 iters
- `gpt51_nl_critique_boot/` — bootstrap from team's plans, n=273, 10.6% converged (regresses iter-0's 11.4%)
- `gpt51_fv_guided_boot/` — bootstrap fv-guided **without** `--with-example`, n=153 (killed early), 46.4% converged
- `gpt51_oracle_nl_boot/`, `gpt51_oracle_nl_boot2/` — oracle-NL bootstrap, partial 122/273 and 76/273 traces
- `gpt51_fv_guided_boot_ex/` — bootstrap fv-guided **with** `--with-example`, ?/273 (status uncertain)
- `gpt51_*_smoke*/` — small sanity-check runs

`results/spec_proposer/` — gpt-4o-mini's task-specific check proposals on 15 tasks: 22/62 (35.5%) accepted by the validation harness.

Aggregated tables: `results/table1.{md,csv}`, `results/experiments/table2.{md,csv}`. Figures: `results/figure0_table1.pdf`, `results/experiments/figure1_convergence.pdf`, `figure2_per_property.pdf`.

---

## Open questions and known issues

1. **oracle-NL ≈ fv-guided on GPT-5.1.** Either (a) formalism doesn't matter for strong models — the win is purely from specificity — or (b) GPT-5.1 ceiling-effects on this benchmark are masking a real gap that smaller models would expose. *Decisive experiment: run on Qwen-7B / Qwen-30B / DeepSeek-6.7B and see if the gap widens.* Marlowe sbatch scripts are written but the runs haven't completed.

2. **No execution.** Every result so far is "the plan passes static checks." We have not run any verified plan through `run_single_task.py` against the WebMall docker stack. *Without execution data, the paper title is an overclaim.*

3. **Selection of properties.** P0–P6 were hand-picked to match WebMall failure modes. The spec_proposer demo (35% acceptance) is the only response, and it's a 15-task pilot.

4. **Re-running with `webmall_prompts_v2.jsonl`** is required for an honest baseline. Not yet done.

5. **Alan's parallel `hardcoded_formal_verification/` directory** in the same repo. Coordinate before paper writeup.

6. **The Browsergym fix** (`3523baa`) is committed locally only. Need to push or hand off.

---

## Compute resources available

- **Marlowe** (Stanford): account `marlowe-m000186-pm05`. Emi has env at `/scratch/m000186/esoroka/`. Sbatch scripts are committed for Qwen2.5-Coder-7B (1 GPU) and Qwen3-Coder-30B-A3B (4 GPUs). Ray now has Marlowe access.
- **OpenAI** key in `WebMall/.env`, used for all GPT-5.1 / gpt-4o-mini runs to date.

---

## Are we actually constraining "agent trajectories"?

**Honest answer: not yet.** What we have is *constraining LLM-generated plan code*. The full agent trajectory loop —

```
plan = LLM(task)
verify(plan)            # ← only this is done today
trajectory = execute(plan, browser_env)   # ← this is missing
score = evaluate(trajectory, gold_answer)
```

— is broken at the execution step. The plumbing exists (`WebMall/AgentLab/.../planning_agent.py::execute_plan` calls `exec(plan, dsl_namespace)`), but no experiment in this repo has actually run a verified plan and measured the resulting task F1.

This is the **single most important thing missing**, and a reviewer will catch it. See "Research direction A" below.

---

## Research directions (Ray's question — paradox + 7 alternatives)

### Why the current direction is paradoxical

The implicit research question is *"does formal verification beat self-critique for LLM-generated agent plans?"* With our current setup that question collapses on itself:

1. If we hardcode properties → we're encoding the answer. *"Your seven checks ARE the supervision signal; the LLM just executes a fix."*
2. If we ask the LLM to propose properties → the LLM is doing both halves. *"How is this different from self-critique with extra steps?"*
3. If we use NL self-critique with specifics (oracle-NL) → it ties FV-guided on GPT-5.1. *"Your formalism is doing nothing."*
4. If we use NL self-critique without specifics → it loses, but trivially. *"Your baseline is a strawman."*

Every framing where formal verification wins, an obvious LLM-only baseline can match it, unless we change one of three things: the *target* of verification (what's being checked), the *signal* the verifier uses (what's it grounded in), or the *ML method* (training-time vs inference-time).

The seven directions below each break the paradox in one of those three ways. Each section says clearly **why an LLM-only baseline cannot match it**.

### D1 — Closed-loop property discovery from execution failures

**Hypothesis.** Properties that catch executor failures are learnable from a small number of (plan, trajectory, success_label) triples — without a human writing them.

**Why an LLM cannot match it.** Self-critique sees only the plan. The property-discoverer sees the plan AND the trajectory it produced AND whether it succeeded. The verifier is grounded in a signal the LLM doesn't have when planning.

**Method.**
1. Boot WebMall docker, run 100 vanilla plans through `planning_agent.execute_plan`, log (plan, action_trace, score).
2. For each failure, prompt an LLM (the *property miner*): given this plan and the action trace, what static check on the plan would have predicted this failure? Output a `check_*(paths, code) -> PropertyResult` Python function.
3. Validate each proposal on a held-out 50/50 success/failure split — keep only checks that discriminate with >70% accuracy.
4. Iterate: add accepted checks to the library, regenerate plans with the augmented verifier, measure whether executor success-rate goes up.

**Headline plot.** Executor success rate as a function of mined-property count. Hypothesis: saturating exponential, asymptote = the "verification ceiling" of the static abstraction.

**Why novel.** Automated specification mining for *agent planning*. Most prior spec-mining (Daikon, ILASP, AutoSpec) is over deterministic programs; ours is over LLM plans executed by another LLM.

**Cost.** ~$10 in proposal-generation API; Marlowe time for re-planning rounds; docker is free.

**Risk.** Mined properties might not generalize beyond their training failures. *Also publishable* as a negative result framed as "limits of static abstraction for agent planning."

### D2 — RLVR: train a planner with verifier-as-reward

**Hypothesis.** A planner LLM fine-tuned with verifier pass-rate as the RL reward will generate verified plans on the *first* try, eliminating the re-planning loop.

**Why an LLM cannot match it.** Self-critique is an *inference-time* fix; RLVR is a *training-time* fix. After RL, the model's plans are verified-by-default — single inference cost. No oracle-NL ablation can match this because oracle-NL still requires re-prompting.

**Method.**
1. Take Qwen-3-Coder-7B or 30B as the base planner.
2. For each task, sample N plans, score each by `Vk(plan) ∈ [0, 1]` (fraction of P0–P6 that pass).
3. GRPO/RLOO/DPO update on the planner.
4. After K epochs, evaluate first-shot verifier pass rate AND executor task F1 (avoid reward hacking).

**Why novel.** RLVR (verifiable reward) is hot — DeepSeek-R1 lit it on fire. Applying it to **multi-property agent planning** with a structural verifier is genuinely new.

**Cost.** ~$100–500 in Marlowe compute for fine-tuning + hyperparameter sweep. Higher reward, higher risk.

**Risk.** Reward hacking — model learns to pass `press_button("Submit Final Result")` without doing the task. Mitigation: include execution success in the reward, or RL with held-out verifier ensemble.

### D3 — Verification format gradient across model scales

**Hypothesis.** Below a critical model scale, *structured* counterexample feedback outperforms *NL-paraphrased* feedback. Above it, they converge.

**Why an LLM-only baseline cannot match it.** This isn't about beating a baseline; it's about *characterizing the regime* where formalism is necessary. The contribution is the curve, not a victory.

**Method.**
1. Run fv-guided + oracle-NL + nl-critique on:
   - DeepSeek-Coder-6.7B
   - Qwen2.5-Coder-7B
   - Qwen3.5-9B
   - Qwen3-Coder-30B-A3B
   - GPT-5.1
2. For each model, compute `Δ = convergence(fv-guided) − convergence(oracle-NL)`.
3. Plot Δ vs model size (or model log-perplexity, or any scale proxy). Identify the crossover scale.

**Why novel.** Prior work on agent verification mostly tests on one model. Scaling laws for the value of feedback structure aren't well-charted. Connects to emergent-capabilities literature, inverse scaling.

**Cost.** $0 marginal — Marlowe runs are free; sbatches already exist. Add oracle-NL to the existing sbatches.

**Risk.** Lowest of any direction. Worst case: noisy curve, smaller paper. Best case: clean phase transition.

### D4 — Symbolic execution of agent plans for *functional* properties

**Hypothesis.** Functional correctness properties (e.g., *"the submitted URL is the cheapest across all searched stores"*) can be verified statically by tracking variable contents symbolically.

**Why an LLM cannot match it.** Self-critique can't *prove* the submitted URL is the argmin; only an SMT-style tool can. This is a class of properties no LLM-verifier or NL-critique baseline can replicate.

**Method.**
1. Build a symbolic execution engine for the WebMall DSL: each variable holds a symbolic expression; control flow accumulates path conditions.
2. Express functional properties in the symbolic algebra: `submit_url == argmin([(price_i, url_i)])`.
3. Discharge verification conditions via Z3 / cvc5.
4. Show: catches a class of bugs P0–P6 cannot.

**Why novel.** First symbolic-execution framework for LLM-generated agent code. Strong PL/SE community appeal.

**Cost.** ~1 week engineering; modest API.

**Risk.** Engineering complexity (Z3 integration, string handling, executor LLM as oracle). Could overrun the deadline. Stronger fit for ICSE/OOPSLA than NeurIPS.

### D5 — Verification ceiling for inference-time agent planning

**Hypothesis** (extends Cohere's *training-time* finding to *inference-time*): strict verification at inference rejects valuable plans that would have executed correctly. Relaxed thresholds (τ = 0.6 fraction of properties) give better executed-task F1 than τ = 1.0.

**Why an LLM cannot match it.** This is a finding about the *gap* between static verification and runtime success — neither pure self-critique nor any LLM-only baseline can produce this finding because they don't have a separate runtime oracle.

**Method.**
1. Run vanilla plans on the WebMall executor; record exec-success.
2. Cross-tabulate (verifier-pass) × (exec-success). Confusion matrix.
3. Vary τ from 1.0 down to 0.4. For each τ, compute the executed-F1 of the *retained* plan set.
4. Find the τ that maximizes executed-F1 — likely <1.0.

**Why novel.** Cohere's *Verification Limits Code LLM Training* (Sept 2025) does this for training data; we'd extend to inference for agent planning. Direct citation pair.

**Cost.** Free if we already have the docker stack up; ~50 task-executions.

**Risk.** Findings might be small effect.

### D6 — Compositional verification with verified subroutine library

**Hypothesis.** If the LLM is given a library of *verified* subroutines (`find_in_shop`, `add_to_cart_safe`, `extract_price`) instead of raw DSL, its plans are correct by composition.

**Why an LLM cannot match it.** This is a system-design contribution, not a learning one. The library is what's verified; the LLM merely composes.

**Method.**
1. Hand-design 5–10 verified-by-construction subroutines with Hoare-style pre/post conditions.
2. Replace raw DSL with the library in the planner prompt.
3. Show: verifier pass rate at iter-0 jumps because composition preserves postconditions.

**Why novel.** "Type-safe agent planning." Connects to PL theory (refinement types, dependent types for agents).

**Cost.** ~3 days engineering; modest API.

**Risk.** Engineering-heavy, theory-light without formal composition rules.

### D7 — Failure-mode taxonomy with property emergence

**Hypothesis.** LLM agent failure modes are concentrated in K canonical patterns; ≤K properties suffice to catch ≥95% of failures across all models.

**Why an LLM cannot match it.** This is a *meta-finding* about the LLM population. Self-critique on individual plans cannot produce population-level statistics.

**Method.**
1. Cluster plans (and their failures) across 6+ models × 273 tasks via embeddings + manual labeling.
2. Identify K canonical failure modes (e.g., "def-wrap-no-call", "no None-guard", "hallucinated DSL").
3. Map each cluster to a property.
4. Empirical: smallest K that catches Y% of failures across all model-task combos.

**Why novel.** Empirical taxonomy of LLM agent failures + minimum property set. Datasets & Benchmarks track viable.

**Cost.** ~1 day analysis on existing data.

**Risk.** "Just empirical" papers without a learning-method contribution sometimes don't clear NeurIPS main track. D&B track is fine.

### Honest ranking (May 6 deadline)

| Rank | Direction | Probability of clean result | Likely venue |
|---|---|---|---|
| 1 | **D3 — Format gradient across scales** | 90% | NeurIPS / COLM |
| 2 | **D5 — Inference-time verification ceiling** | 80% | NeurIPS main |
| 3 | **D1 — Property mining from exec failures** | 70% | NeurIPS main |
| 4 | **D7 — Failure taxonomy** | 95% (D&B) | NeurIPS D&B |
| 5 | **D6 — Verified subroutine library** | 60% | NeurIPS / ICLR |
| 6 | **D2 — RLVR planner** | 50% (highest reward if works) | NeurIPS main |
| 7 | **D4 — Symbolic execution** | 30% (could overrun deadline) | OOPSLA / ICSE |

### Recommended package: D3 + D5 + D1 in one paper

Three legs, one benchmark, one re-planning loop, one property language:

1. *When does formal verification matter?* — D3 (scale-dependent crossover)
2. *How strict should verification be?* — D5 (verification ceiling at inference)
3. *Where do good properties come from?* — D1 (mined from execution traces)

Each leg has a clear hypothesis, method, and publishable finding regardless of whether the result is positive or negative. The combination is genuinely new.

### Recommended paper pitch

> "We study iterative repair of LLM-generated agent plans under three feedback regimes (no feedback, prose self-critique, formal counterexamples), and characterize the value of formal verification as a function of model size and feedback specificity. We find a *verification format gradient*: structured counterexamples decisively outperform prose feedback below a critical model scale, but the gap closes for larger models. We extend Cohere's training-time *verification ceiling* finding to inference time, showing that strict verification rejects executable plans, and locate the optimal pass-fraction threshold for a calibrated re-planner. Finally, we show that structural properties can be *mined* from executor-failure traces without human authoring, yielding a property library that generalizes across tasks. The combined system improves WebMall task F1 by X points over an unverified baseline and matches the gain from a hand-coded property library, with no human annotation."

### What to cut from the current paper

- The "we hand-wrote 7 properties" framing — mention P0–P6 as the *seed* set we *augment* via mining.
- The "fv-guided beats nl-critique" headline — reframe as "fv-guided beats nl-critique-without-specifics, ties oracle-NL on strong models, and beats it on small models."
- The 75.5% vs 1.5% number — replace with full Table 2 including oracle-NL and the small-model sweep.
- Any claim about "agent trajectories" until we have execution data.

---

## Concrete next-week plan (in priority order)

1. **Day 1**: Stand up the WebMall docker stack (`WebMall/docker_all/restore_all_and_deploy_local.sh`), run the 50-task execution-grounded eval. This is the minimum bar to honestly claim "agent trajectories." If exec-success doesn't correlate with static-pass, we *need* to know now, not in week 3. (D5 leg.)
2. **Days 2–3**: Run Qwen-7B / 30B on Marlowe for fv-guided + oracle-NL + nl-critique on 273 tasks each. (D3 leg.)
3. **Day 4**: Run the spec_proposer at 273-task scale, integrate accepted checks into FV-guided loop. (Glue D1 to D3.)
4. **Days 5–6**: Property-mining loop on docker exec traces — LLM proposes checks given (failed plan, action trace). Fit acceptance curve. (D1 leg.)
5. **Day 7**: Aggregate, generate figures, draft paper.
6. **Days 8–14**: Paper write-up, NeurIPS checklist, polish.

---

## Quickstart commands for a new agent

```bash
# 1) Verify the toolchain works
cd /home/ray/formalverification/llm_stl_benchmark/formal_verification
/home/ray/formalverification/.venv/bin/python3 tests/test_replan_loop.py
# Expect: "All tests passed."

# 2) Aggregate the current results
/home/ray/formalverification/.venv/bin/python3 aggregate_table1.py --dir results
/home/ray/formalverification/.venv/bin/python3 aggregate_table2.py --dir results/experiments

# 3) Verify a jsonl of plans (free)
/home/ray/formalverification/.venv/bin/python3 run_formal_verification.py \
    --input ../plan_docs/webmall_plan_gpt-5.1_0.0_Example_True.jsonl \
    --outdir results

# 4) Run a small experiment (paid, ~$1)
/home/ray/formalverification/.venv/bin/python3 run_replan_experiment.py \
    --prompts ../plan_docs/webmall_prompts_v2.jsonl \
    --bootstrap-plans ../plan_docs/webmall_plan_gpt-5.1_0.0_Example_True.jsonl \
    --provider openai --model gpt-5.1 \
    --condition fv-guided --max-iterations 3 --with-example \
    --limit 10 --outdir results/experiments/handoff_smoke

# 5) Inspect a trace (no API)
/home/ray/formalverification/.venv/bin/python3 -c "
import json
with open('results/experiments/gpt51_fv_guided/traces.jsonl') as f:
    for line in f:
        r = json.loads(line)
        print(r['task_id'], 'converged:', r['converged'], 'iters:', len(r['iterations']))
"
```

### Marlowe quickstart
```bash
ssh YOUR_SUNETID@login.marlowe.stanford.edu
cd /scratch/m000186/$USER
git clone git@github.com:lallgroup/llm_stl_benchmark.git
cd llm_stl_benchmark/formal_verification
git checkout vibe-formal-verification
ln -s ../plan_docs/webmall_prompts_v2.jsonl webmall_prompts.jsonl  # use the patched prompts
# Edit submit_replanner_qwen_*.sbatch to point at YOUR conda env, then:
sbatch submit_replanner_qwen_7b.sbatch
sbatch submit_replanner_qwen_30b.sbatch
```

---

## Style / authorship notes

- **No Co-Authored-By trailers in commit messages.** The user has explicitly asked that all commits be authored solely by `ray <rayk99801@gmail.com>` (or whichever real human is operating). Don't add Claude attribution.
- **Always `git pull --rebase origin vibe-formal-verification` before pushing**; the branch has multiple authors pushing concurrently.
- The `tasks/todo.md` file at `/home/ray/formalverification/tasks/todo.md` is project-wide notes from earlier sessions; partially out of date. This `HANDOFF.md` is the authoritative current state.

---

## Hard truths the paper must confront

1. We have not executed a single verified plan. The paper says "constraining agent trajectories"; we have only constrained plan source code.
2. On GPT-5.1, oracle-NL ≈ fv-guided. The "formal" framing is doing equal work to "specific."
3. P0–P6 are hand-picked to match WebMall failure modes; an adversarial reviewer will say we're hardcoding the answer.
4. NL-critique baseline is naive and easy to beat; we need a stronger baseline (the oracle-NL we already have, but also "specific NL with line numbers but no formal structure").
5. Until `webmall_prompts_v2.jsonl` is used, vanilla baselines understate model competence (because the prompt was lying about Optional return types, forcing LLMs into wrong guards).

The handoff agent should treat addressing items (1)–(5) as the bar for paper-readiness, not as nice-to-haves.
