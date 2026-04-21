"""
plot_convergence.py — Two figures for the paper from the 3-condition traces.

Figure 1: pass-rate vs iteration, per condition
  For k ∈ {0, 1, 2}, what % of tasks have all-properties-passing by that iter?
  This shows how the FV loop reaches convergence across iterations vs. the
  baseline conditions which stay flat.

Figure 2: per-property pass-rate at the FINAL iteration, per condition
  Grouped bar chart: x = P0..P6, bars = {vanilla, nl-critique, fv-guided}.
  Makes it easy to see which properties the FV guidance fixes most.

Run after run_replan_experiment.py has populated
results/experiments/gpt51_{vanilla,nl_critique,fv_guided}[_boot]/traces.jsonl

Writes PNG + PDF into results/experiments/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


CONDITIONS = [
    # (label, directory suffix, color, linestyle)
    ("vanilla",              "vanilla",          "#888888", "-"),
    ("nl-critique",          "nl_critique",      "#d62728", "-"),
    ("fv-guided",            "fv_guided",        "#2ca02c", "-"),
    ("nl-critique (boot)",   "nl_critique_boot", "#ff9896", "--"),
    ("fv-guided (boot)",     "fv_guided_boot",   "#98df8a", "--"),
]


def _load_condition(base: str, variant: str = "") -> tuple[list[dict], dict[str, dict]]:
    """Return (rows, per_prop_stats) for a condition under base/.
    variant='' or '_boot' to select bootstrap runs."""
    path = os.path.join(base, f"gpt51_{variant}", "traces.jsonl") if variant.startswith("gpt51") else \
           os.path.join(base, f"gpt51_{variant}", "traces.jsonl")
    if not os.path.exists(path):
        return [], {}
    with open(path) as f:
        rows = [json.loads(l) for l in f]
    return rows, {}


def _pass_rate_by_iter(rows: list[dict], max_k: int = 3) -> list[float]:
    """Fraction of tasks whose iteration k exists AND all properties passed."""
    out: list[float] = []
    n = len(rows) or 1
    for k in range(max_k):
        pass_count = 0
        for r in rows:
            # "passed at iter k" = the task had an iter<=k where all props passed
            iters = r["iterations"]
            for it in iters[: k + 1]:
                if all(pr["passed"] for pr in it["property_results"]):
                    pass_count += 1
                    break
        out.append(pass_count / n)
    return out


def _final_prop_pass(rows: list[dict]) -> dict[str, float]:
    """Per-property pass rate at the final iteration."""
    tot = defaultdict(int); p = defaultdict(int)
    for r in rows:
        for pr in r["iterations"][-1]["property_results"]:
            tot[pr["name"]] += 1
            if pr["passed"]:
                p[pr["name"]] += 1
    return {k: p[k] / tot[k] if tot[k] else 0.0 for k in tot}


def _short(name: str) -> str:
    m = re.match(r"^(P\d+)", name)
    return m.group(1) if m else name


def plot_figure1(base: str, out_prefix: str, suffix: str = ""):
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    for label, d, color, ls in CONDITIONS:
        path = os.path.join(base, f"gpt51_{d}", "traces.jsonl")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            rows = [json.loads(l) for l in f]
        rates = _pass_rate_by_iter(rows, max_k=3)
        xs = list(range(len(rates)))
        ax.plot(xs, [100 * r for r in rates], marker="o", linestyle=ls,
                label=f"{label} (n={len(rows)})", color=color,
                linewidth=2, markersize=6)
    ax.set_xlabel("Iteration")
    ax.set_ylabel("All-properties pass rate (%)")
    ax.set_title("GPT-5.1 convergence: from-scratch (solid) and bootstrap (dashed)")
    ax.set_xticks([0, 1, 2])
    ax.set_ylim(0, 100)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=9)
    fig.tight_layout()
    png = f"{out_prefix}.png"; pdf = f"{out_prefix}.pdf"
    fig.savefig(png, dpi=160, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"→ {png}")
    print(f"→ {pdf}")


def plot_figure2(base: str, out_prefix: str, suffix: str = ""):
    # Collect data
    data: dict[str, dict[str, float]] = {}
    all_props: set[str] = set()
    for label, d, _, _ in CONDITIONS:
        path = os.path.join(base, f"gpt51_{d}", "traces.jsonl")
        if not os.path.exists(path):
            continue
        with open(path) as f:
            rows = [json.loads(l) for l in f]
        stats = _final_prop_pass(rows)
        data[label] = stats
        all_props |= set(stats)

    prop_list = sorted(all_props, key=lambda n: (0, int(re.match(r'^P(\d+)', n).group(1))) if re.match(r'^P\d+', n) else (1, n))
    shorts = [_short(p) for p in prop_list]
    x = list(range(len(prop_list)))
    n_conds = sum(1 for (lbl, _, _, _) in CONDITIONS if lbl in data)
    width = 0.95 / n_conds if n_conds else 0.15

    fig, ax = plt.subplots(figsize=(9, 3.8))
    i = 0
    for label, _, color, _ in CONDITIONS:
        if label not in data:
            continue
        ys = [100 * data[label].get(p, 0) for p in prop_list]
        xs = [xx + (i - (n_conds - 1) / 2) * width for xx in x]
        ax.bar(xs, ys, width, label=label, color=color)
        i += 1
    ax.set_xticks(x)
    ax.set_xticklabels(shorts)
    ax.set_ylabel("Pass rate at final iteration (%)")
    ax.set_title("Per-property pass rate at final iteration, by condition")
    ax.set_ylim(0, 105)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=9)
    fig.tight_layout()
    png = f"{out_prefix}.png"; pdf = f"{out_prefix}.pdf"
    fig.savefig(png, dpi=160, bbox_inches="tight")
    fig.savefig(pdf, bbox_inches="tight")
    plt.close(fig)
    print(f"→ {png}")
    print(f"→ {pdf}")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/experiments")
    args = ap.parse_args(argv)

    plot_figure1(args.dir, os.path.join(args.dir, "figure1_convergence"))
    plot_figure2(args.dir, os.path.join(args.dir, "figure2_per_property"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
