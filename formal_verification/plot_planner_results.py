"""
Read results/planner_results.tex, average P0-P6 per row to produce
"Overall performance", and plot a grouped bar chart by model.
"""

import re
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from pathlib import Path

TEX_FILE = Path(__file__).parent / "results" / "planner_results.tex"
OUT_FILE = Path(__file__).parent / "results" / "planner_results_chart.pdf"

# ---------------------------------------------------------------------------
# Parse the .tex file
# ---------------------------------------------------------------------------
text = TEX_FILE.read_text()

# Extract data rows: lines that look like "word & word & num & ... \\"
row_re = re.compile(
    r"^\s*(\S+)\s*&\s*(\S+)\s*&\s*"   # Condition & Model
    r"([\d.]+)\s*&\s*"                  # Valid
    r"([\d.]+)\s*&\s*"                  # P0
    r"([\d.]+)\s*&\s*"                  # P1
    r"([\d.]+)\s*&\s*"                  # P2
    r"([\d.]+)\s*&\s*"                  # P3
    r"([\d.]+)\s*&\s*"                  # P4
    r"([\d.]+)\s*&\s*"                  # P5
    r"([\d.]+)",                        # P6  (Avg. Iterations optional)
    re.MULTILINE,
)

records = []
for m in row_re.finditer(text):
    condition, model = m.group(1), m.group(2)
    p_vals = [float(m.group(i)) for i in range(4, 11)]   # P0-P6
    overall = np.mean(p_vals)
    records.append({"condition": condition, "model": model, "overall": overall})

# ---------------------------------------------------------------------------
# Normalise model names for display
# ---------------------------------------------------------------------------
MODEL_LABELS = {
    "gpt-4.1":              "GPT-4.1",
    "claude-sonnet-4":      "Claude Sonnet 4",
    "deepseek-coder-33b":   "DeepSeek Coder 33B",
    "qwen3-coder-33b":      "Qwen3 Coder 33B",
    "qwen-coder-30b":       "Qwen Coder 30B",
    "qwen3-coder-30b":      "Qwen3 Coder 30B",
    "deepseek-coder-6.7b":  "DeepSeek Coder 6.7B",
    "qwen-coder-6.7b":      "Qwen Coder 6.7B",
    "qwen2.5-coder-7b":     "Qwen2.5 Coder 7B",
}

CONDITION_ORDER = ["nl-critique", "oracle-nl", "fv-guided"]
CONDITION_LABELS = {
    "nl-critique": "NL Critique",
    "oracle-nl":   "Oracle NL",
    "fv-guided":   "FV-Guided",
}

# Collect all unique models in appearance order
seen_models = []
for r in records:
    if r["model"] not in seen_models:
        seen_models.append(r["model"])

# Build a 2-D dict: model → condition → overall
data: dict[str, dict[str, float]] = {m: {} for m in seen_models}
for r in records:
    cond, model, val = r["condition"], r["model"], r["overall"]
    # If duplicate key (same model+condition appears twice), take mean
    if cond in data[model]:
        data[model][cond] = (data[model][cond] + val) / 2
    else:
        data[model][cond] = val

# ---------------------------------------------------------------------------
# Plot
# ---------------------------------------------------------------------------
COLORS = {
    "nl-critique": "#4C72B0",
    "oracle-nl":   "#DD8452",
    "fv-guided":   "#55A868",
}
HATCHES = {
    "nl-critique": "///",
    "oracle-nl":   "...",
    "fv-guided":   "xxx",
}

n_models = len(seen_models)
n_conds  = len(CONDITION_ORDER)
bar_w    = 0.22
group_w  = n_conds * bar_w
x_centers = np.arange(n_models)

fig, ax = plt.subplots(figsize=(max(10, n_models * 1.6), 5))

for ci, cond in enumerate(CONDITION_ORDER):
    offsets = x_centers + (ci - (n_conds - 1) / 2) * bar_w
    values  = [data[m].get(cond, np.nan) for m in seen_models]
    bars = ax.bar(
        offsets, values,
        width=bar_w * 0.9,
        color=COLORS[cond],
        hatch=HATCHES[cond],
        edgecolor="black",
        label=CONDITION_LABELS[cond],
        zorder=3,
    )
    # Annotate bars with value
    for bar, val in zip(bars, values):
        if not np.isnan(val):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.5,
                f"{val:.1f}",
                ha="center", va="bottom",
                fontsize=10, color="black",
            )

ax.set_xticks(x_centers)
ax.set_xticklabels(
    [MODEL_LABELS.get(m, m) for m in seen_models],
    rotation=20, ha="right", fontsize=10,
)
ax.set_ylabel("Overall Performance (avg. P0–P6, %)", fontsize=12)
ax.set_ylim(0, 108)
# No title because it should be the figure caption.
#ax.set_title("Plan Property Compliance by Model and Critique Condition", fontsize=14, pad=10)
ax.yaxis.grid(True, linestyle="--", alpha=0.5, zorder=0)
ax.set_yticklabels(labels=ax.get_yticks(), fontsize=10)
ax.set_axisbelow(True)
ax.spines[["top", "right"]].set_visible(False)

legend_patches = [
    mpatches.Patch(color=COLORS[c], hatch=HATCHES[c], edgecolor="black", label=CONDITION_LABELS[c])
    for c in CONDITION_ORDER
]
ax.legend(handles=legend_patches, loc="lower right", fontsize=12)

plt.tight_layout()
plt.savefig(OUT_FILE, bbox_inches="tight")
print(f"Saved → {OUT_FILE}")
plt.show()
