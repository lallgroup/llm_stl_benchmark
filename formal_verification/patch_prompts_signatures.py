"""
patch_prompts_signatures.py — Rewrite the DSL-signature block inside an
existing webmall_prompts.jsonl so the annotations reflect the real Optional
return types.

Context
-------
Emi's ``webmall_prompts.jsonl`` was produced before Browsergym's
``functions.py`` was fixed (the source had ``-> str or None`` which Python
evaluates to just ``str`` at def-time, so ``inspect.signature`` rendered
``-> str`` instead of ``-> str | None``).  Plans copied into re-plan
experiments via ``--bootstrap-plans`` assume this *stale* contract; LLMs
write ``if x != "":`` guards that don't catch None.

This script reads the jsonl and, in every row's ``prompt``, rewrites the
7 specific "lies" to reflect reality:

  search_on_page(...) -> str            →  -> str | None
  extract_information_from_page(...) -> str   →  -> str | None
  navigate_to_page(...) -> bool         →  -> bool | None
  fill_text_field(...) -> bool          →  -> bool | None
  press_button(...) -> bool             →  -> bool | None
  select_option(...) -> bool            →  -> bool | None   (also drops wrong first arg)
  generic_action(...) -> str            →  -> str | None
  add_to_cart(...) -> bool              →  -> bool | None
  checkout(...) -> bool                 →  -> bool | None

The rewrite is purely textual: we find the stale signature line and replace
it with the corrected one, leaving everything else in the prompt (task,
observation, instructions) untouched.

Usage
-----
    python patch_prompts_signatures.py \
        --input  /path/to/webmall_prompts.jsonl \
        --output /path/to/webmall_prompts_v2.jsonl

If ``--output`` is omitted, writes alongside the input with ``_v2`` before
the extension.
"""

from __future__ import annotations

import argparse
import json
import os
import sys


# (old_line, new_line) pairs. Precise line-level substitutions so we don't
# accidentally hit other text. Match what the prompts jsonls actually
# contain today, including weird whitespace.
REPLACEMENTS: list[tuple[str, str]] = [
    # search_on_page: add selection_criteria arg and fix return type
    # handles the Optional[str] variant present in current webmall_prompts.jsonl
    (
        "search_on_page(search_page_url: str, search_text: str) -> Optional[str]\n",
        "search_on_page(search_page_url: str, search_text: str, selection_criteria: str) -> str\n",
    ),
    # also handle the plain -> str variant (pre-patch files)
    (
        "search_on_page(search_page_url: str, search_text: str) -> str\n",
        "search_on_page(search_page_url: str, search_text: str, selection_criteria: str) -> str\n",
    ),
    # also handle the -> str | None variant (already-patched files)
    (
        "search_on_page(search_page_url: str, search_text: str) -> str | None\n",
        "search_on_page(search_page_url: str, search_text: str, selection_criteria: str) -> str\n",
    ),
    # extract_information_from_page  str -> str | None
    (
        "extract_information_from_page(description: str) -> str\n",
        "extract_information_from_page(description: str) -> str | None\n",
    ),
    # navigate_to_page  bool -> bool | None
    (
        "navigate_to_page(description: str) -> bool\n",
        "navigate_to_page(description: str) -> bool | None\n",
    ),
    # fill_text_field  bool -> bool | None
    (
        "fill_text_field(field_description: str, text: str) -> bool\n",
        "fill_text_field(field_description: str, text: str) -> bool | None\n",
    ),
    # press_button  bool -> bool | None
    (
        "press_button(button_description: str) -> bool\n",
        "press_button(button_description: str) -> bool | None\n",
    ),
    # generic_action  str -> str | None
    (
        "generic_action(description: str) -> str\n",
        "generic_action(description: str) -> str | None\n",
    ),
    # add_to_cart  bool -> bool | None
    (
        "add_to_cart(url: str, item_description: str) -> bool\n",
        "add_to_cart(url: str, item_description: str) -> bool | None\n",
    ),
    # checkout  bool -> bool | None
    (
        "checkout(payment_and_shipping_information: str) -> bool\n",
        "checkout(payment_and_shipping_information: str) -> bool | None\n",
    ),
    # select_option: the existing prompt uses the `(bid: str, options: ...)`
    # signature (because HighLevelActionSet picks the low-level bid version by
    # name-collision), which isn't what the planner actually calls. Leave the
    # bid-signature in place but mark return as bool | None for consistency.
    (
        "select_option(bid: str, options: str | list[str])\n",
        "select_option(bid: str, options: str | list[str]) -> bool | None\n",
    ),
]


def patch_prompt(prompt: str) -> tuple[str, int]:
    """Apply all replacements to a prompt string. Returns (new_prompt, n_hits)."""
    n = 0
    for old, new in REPLACEMENTS:
        if old in prompt and old != new:
            prompt = prompt.replace(old, new)
            n += 1
    return prompt, n


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.output is None:
        base, ext = os.path.splitext(args.input)
        args.output = f"{base}_v2{ext}"

    n_rows = 0
    n_hits_total = 0
    hits_histogram: dict[int, int] = {}

    with open(args.input) as fh_in, open(args.output, "w") as fh_out:
        for line in fh_in:
            line = line.strip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as e:
                print(f"[warn] skip line {n_rows + 1}: bad JSON ({e})", file=sys.stderr)
                fh_out.write(line + "\n")
                n_rows += 1
                continue
            n_rows += 1
            prompt = row.get("prompt", "")
            patched, hits = patch_prompt(prompt)
            row["prompt"] = patched
            n_hits_total += hits
            hits_histogram[hits] = hits_histogram.get(hits, 0) + 1
            fh_out.write(json.dumps(row) + "\n")

    if not args.quiet:
        print(f"Processed {n_rows} rows  ·  {n_hits_total} total substitutions")
        print("Substitutions per row:")
        for h in sorted(hits_histogram):
            print(f"  {h:>2} subs: {hits_histogram[h]} rows")
        print(f"→ {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
