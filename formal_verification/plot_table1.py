"""
plot_table1.py — Visualize Table 1 (vanilla pass rates × 6 model runs) as a
grouped bar chart, one bar per property within each model group.

Reads results/table1.csv and emits results/figure0_table1.pdf / .png.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _short(name: str) -> str:
    m = re.match(r"^(P\d+)", name)
    return m.group(1) if m else name


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="results/table1.csv")
    ap.add_argument("--out", default="results/figure0_table1")
    args = ap.parse_args(argv)

    with open(args.csv) as f:
        r = csv.reader(f)
        header = next(r)
        rows = list(r)

    # Header: LLM, valid, P0, P1, P2, P3, P4, P5, P6
    prop_cols = [h for h in header[2:]]
    # Parse each row
    models: list[str] = []
    data: list[list[float]] = []
    for row in rows:
        label = row[0]
        # shorter display label
        m = re.match(r"^(.+?)\s*\(ex=(T|F),\s*T=([\d.]+)\)$", label)
        if m:
            short = m.group(1).replace("Qwen2.5-Coder-7B-Instruct", "Qwen2.5-Coder-7B")\
                              .replace("deepseek-coder-6.7b-instruct", "DeepSeek-6.7B")
            ex = m.group(2)
            tpt = m.group(3)
            short = f"{short}\n(ex={ex},T={tpt})"
        else:
            short = label
        models.append(short)
        pcts = [float(v.rstrip("%")) for v in row[2:]]
        data.append(pcts)

    n_models = len(models)
    n_props = len(prop_cols)
    width = 0.11
    x = list(range(n_models))

    colors = plt.cm.viridis([i / max(1, n_props - 1) for i in range(n_props)])

    fig, ax = plt.subplots(figsize=(10.5, 4.5))
    for j, prop in enumerate(prop_cols):
        ys = [data[i][j] for i in range(n_models)]
        xs = [xx + (j - (n_props - 1) / 2) * width for xx in x]
        ax.bar(xs, ys, width, label=prop, color=colors[j])

    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=8)
    ax.set_ylabel("Pass rate (%)")
    ax.set_title("Single-shot pass rates across models (n=273 tasks per model)")
    ax.set_ylim(0, 105)
    ax.grid(True, axis="y", alpha=0.3)
    ax.legend(loc="upper right", frameon=False, ncol=n_props // 2 + 1, fontsize=8)
    fig.tight_layout()
    fig.savefig(f"{args.out}.png", dpi=160)
    fig.savefig(f"{args.out}.pdf")
    plt.close(fig)
    print(f"→ {args.out}.png")
    print(f"→ {args.out}.pdf")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
