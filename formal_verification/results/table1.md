| LLM | valid | P0 | P1 | P2 | P3 | P4 | P5 | P6 |
|---|---|---|---|---|---|---|---|---|
| Qwen2.5-Coder-7B-Instruct (ex=T, T=0.0) | 100.00% | 0.00% | 100.00% | 100.00% | 100.00% | 0.00% | 100.00% | 100.00% |
| Qwen3.5-9B (ex=F, T=0.6) | 70.70% | 98.96% | 64.25% | 95.85% | 70.98% | 50.78% | 64.77% | 97.41% |
| Qwen3.5-9B (ex=T, T=0.6) | 97.44% | 99.25% | 100.00% | 96.24% | 91.35% | 99.62% | 90.98% | 100.00% |
| deepseek-coder-6.7b-instruct (ex=F, T=0.0) | 100.00% | 0.00% | 100.00% | 0.00% | 100.00% | 100.00% | 0.00% | 100.00% |
| deepseek-coder-6.7b-instruct (ex=T, T=0.0) | 100.00% | 100.00% | 0.00% | 100.00% | 0.00% | 100.00% | 100.00% | 0.00% |
| gpt-5.1 (ex=T, T=0.0) | 100.00% | 100.00% | 37.00% | 100.00% | 90.11% | 24.91% | 98.90% | 37.36% |

**Property legend:**
- `P0` — P0: Uses only DSL / builtin functions
- `P1` — P1: Submit always called
- `P2` — P2: Solution field filled before submit
- `P3` — P3: All stores searched
- `P4` — P4: None-returning results guarded
- `P5` — P5: Solution page opened before submit
- `P6` — P6: Top-level code actually runs
