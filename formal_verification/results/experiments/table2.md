# Table 2 — re-planning conditions on gpt-5.1 (n=273 tasks)

| Condition | n | Converged | Mean iters | P0 | P1 | P2 | P3 | P4 | P5 | P6 |
|---|---|---|---|---|---|---|---|---|---|---|
| vanilla | 271 | 4/271 (1.5%) | 1.00 | 100.0% | 8.5% | 100.0% | 80.1% | 28.8% | 100.0% | 8.9% |
| nl-critique | 273 | 2/273 (0.7%) | 2.99 | 98.9% | 8.1% | 100.0% | 71.1% | 26.4% | 100.0% | 8.1% |
| fv-guided | 273 | 206/273 (75.5%) | 2.44 | 100.0% | 99.6% | 99.3% | 90.8% | 85.3% | 97.8% | 100.0% |
| nl-critique (boot) | 273 | 29/273 (10.6%) | 2.79 | 100.0% | 36.6% | 100.0% | 90.1% | 27.5% | 98.9% | 36.6% |
| fv-guided (boot) | 153 | 71/153 (46.4%) | 2.52 | 100.0% | 98.0% | 100.0% | 98.7% | 52.3% | 92.8% | 100.0% |

**Property legend:**
- `P0` — Uses only DSL / builtin functions
- `P1` — Submit always called
- `P2` — Solution field filled before submit
- `P3` — All stores searched
- `P4` — None-returning results guarded
- `P5` — Solution page opened before submit
- `P6` — Top-level code actually runs
