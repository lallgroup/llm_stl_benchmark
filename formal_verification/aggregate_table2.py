"""
aggregate_table2.py — Build Table 2 from the 3-condition replan-experiment
traces under results/experiments/.

Reads traces.jsonl for each of {vanilla, nl-critique, fv-guided} and emits a
consolidated comparison: convergence rate, per-property pass rates on the
FINAL iteration, mean iterations to termination.

Writes:
  * results/experiments/table2.csv
  * results/experiments/table2.md
Prints to stdout.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys


def _per_condition(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        rows = [json.loads(l) for l in f]
    n = len(rows)
    converged = sum(1 for r in rows if r["converged"])
    iters = [len(r["iterations"]) for r in rows]
    # final-iteration property pass counts
    prop_pass: dict[str, int] = {}
    prop_total: dict[str, int] = {}
    for r in rows:
        for pr in r["iterations"][-1]["property_results"]:
            prop_total[pr["name"]] = prop_total.get(pr["name"], 0) + 1
            if pr["passed"]:
                prop_pass[pr["name"]] = prop_pass.get(pr["name"], 0) + 1
    return {
        "n": n,
        "converged": converged,
        "converged_pct": 100 * converged / max(1, n),
        "mean_iters": sum(iters) / max(1, n),
        "prop_pass": prop_pass,
        "prop_total": prop_total,
    }


def _key(name: str):
    m = re.match(r"^P(\d+)", name)
    return (0, int(m.group(1))) if m else (1, name)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results/experiments",
                    help="directory containing gpt51_{vanilla,nl_critique,fv_guided}/traces.jsonl")
    ap.add_argument("--model", default="gpt-5.1")
    args = ap.parse_args(argv)

    conditions = [
        ("vanilla",           os.path.join(args.dir, "gpt51_vanilla",          "traces.jsonl")),
        ("nl-critique",       os.path.join(args.dir, "gpt51_nl_critique",      "traces.jsonl")),
        ("fv-guided",         os.path.join(args.dir, "gpt51_fv_guided",        "traces.jsonl")),
        ("nl-critique (boot)",os.path.join(args.dir, "gpt51_nl_critique_boot", "traces.jsonl")),
        ("fv-guided (boot)",  os.path.join(args.dir, "gpt51_fv_guided_boot",   "traces.jsonl")),
    ]

    stats = {label: _per_condition(path) for label, path in conditions}

    # union of property names
    all_props: set[str] = set()
    for s in stats.values():
        all_props |= set(s.get("prop_pass", {})) | set(s.get("prop_total", {}))
    prop_order = sorted(all_props, key=_key)

    # ── Markdown table ───────────────────────────────────────────────────────
    md: list[str] = []
    md.append(f"# Table 2 — re-planning conditions on {args.model} (n=273 tasks)")
    md.append("")
    md.append("| Condition | n | Converged | Mean iters | " +
              " | ".join(re.match(r"^(P\d+)", p).group(1) if re.match(r"^P\d+", p) else p for p in prop_order) + " |")
    md.append("|" + "|".join(["---"] * (4 + len(prop_order))) + "|")
    for label, _ in conditions:
        s = stats.get(label, {})
        if not s:
            md.append(f"| {label} | — | — | — | " + " | ".join(["—"] * len(prop_order)) + " |")
            continue
        cells = [label, str(s["n"]), f'{s["converged"]}/{s["n"]} ({s["converged_pct"]:.1f}%)',
                 f'{s["mean_iters"]:.2f}']
        for p in prop_order:
            pp = s["prop_pass"].get(p, 0)
            pt = s["prop_total"].get(p, 0)
            if pt == 0:
                cells.append("—")
            else:
                cells.append(f"{100*pp/pt:.1f}%")
        md.append("| " + " | ".join(cells) + " |")

    md.append("")
    md.append("**Property legend:**")
    for p in prop_order:
        m = re.match(r"^(P\d+):\s*(.+)$", p)
        key = m.group(1) if m else p
        desc = m.group(2) if m else p
        md.append(f"- `{key}` — {desc}")

    md_out = os.path.join(args.dir, "table2.md")
    with open(md_out, "w") as f:
        f.write("\n".join(md) + "\n")

    # ── CSV table ────────────────────────────────────────────────────────────
    csv_out = os.path.join(args.dir, "table2.csv")
    with open(csv_out, "w", newline="") as f:
        w = csv.writer(f)
        header = ["condition", "n", "converged", "converged_pct", "mean_iters"] + prop_order
        w.writerow(header)
        for label, _ in conditions:
            s = stats.get(label, {})
            if not s:
                continue
            row = [label, s["n"], s["converged"], f'{s["converged_pct"]:.2f}', f'{s["mean_iters"]:.3f}']
            for p in prop_order:
                pp = s["prop_pass"].get(p, 0); pt = s["prop_total"].get(p, 0)
                row.append(f'{100*pp/pt:.2f}' if pt else '')
            w.writerow(row)

    print("\n".join(md))
    print()
    print(f"→ wrote {md_out}")
    print(f"→ wrote {csv_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
