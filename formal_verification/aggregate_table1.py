"""
aggregate_table1.py — Build one consolidated table across all models/settings
from the per-file summary.csv outputs produced by run_formal_verification.py.

Writes:
  * results/table1.csv          — machine-readable grid
  * results/table1.md           — markdown table (for paper draft)
  * prints the table to stdout

Usage: python aggregate_table1.py [--dir results]
"""

from __future__ import annotations

import argparse
import csv
import glob
import os
import re
import sys


def _label_from_basename(base: str) -> str:
    # webmall_plan_<MODEL>_<TEMP>_Example_<BOOL>.summary  →  (MODEL, Example=…, T=…)
    m = re.match(r"^webmall_plan_(.+?)_(?P<temp>[0-9.]+)_Example_(?P<ex>True|False)\.summary$", base)
    if not m:
        return base
    model = m.group(1)
    ex = "T" if m.group("ex") == "True" else "F"
    return f"{model} (ex={ex}, T={m.group('temp')})"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="results")
    args = ap.parse_args(argv)

    files = sorted(glob.glob(os.path.join(args.dir, "*.summary.csv")))
    if not files:
        print(f"No summary.csv files in {args.dir}/", file=sys.stderr)
        return 1

    # load each as dict[property_name] = pass_pct
    rows: list[tuple[str, dict[str, str], str]] = []  # (label, pcts, valid)
    all_props: set[str] = set()
    for f in files:
        label = _label_from_basename(os.path.splitext(os.path.basename(f))[0])
        pcts: dict[str, str] = {}
        valid_pct = "-"
        with open(f) as fh:
            r = csv.reader(fh)
            header = next(r, None)
            for row in r:
                if not row:
                    continue
                if row[0] == "_syntactic_validity":
                    valid_pct = row[4]
                    continue
                prop_name = row[0]
                pass_pct = row[4]
                pcts[prop_name] = pass_pct
                all_props.add(prop_name)
        rows.append((label, pcts, valid_pct))

    # order properties by Pn prefix
    def _key(name: str):
        m = re.match(r"^P(\d+)", name)
        return (0, int(m.group(1))) if m else (1, name)
    prop_order = sorted(all_props, key=_key)
    # short headers: just P0, P1, ...
    short = {n: (re.match(r"^(P\d+)", n).group(1) if re.match(r"^P\d+", n) else n) for n in prop_order}

    # markdown table
    out_md: list[str] = []
    header = ["LLM", "valid"] + [short[p] for p in prop_order]
    out_md.append("| " + " | ".join(header) + " |")
    out_md.append("|" + "|".join(["---"] * len(header)) + "|")
    for label, pcts, valid in rows:
        row = [label, valid + "%"] + [pcts.get(p, "-") + "%" for p in prop_order]
        out_md.append("| " + " | ".join(row) + " |")

    # legend
    out_md.append("")
    out_md.append("**Property legend:**")
    for p in prop_order:
        out_md.append(f"- `{short[p]}` — {p}")

    md_path = os.path.join(args.dir, "table1.md")
    with open(md_path, "w") as fh:
        fh.write("\n".join(out_md) + "\n")

    # csv table
    csv_path = os.path.join(args.dir, "table1.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for label, pcts, valid in rows:
            w.writerow([label, valid] + [pcts.get(p, "") for p in prop_order])

    # stdout
    print("\n".join(out_md))
    print()
    print(f"→ wrote {md_path}")
    print(f"→ wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
