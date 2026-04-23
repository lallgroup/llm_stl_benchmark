"""
planner_adapter.py — Pluggable ``planner(task_prompt, previous_plan, feedback)
-> plan_src`` callables for the re-plan loop.

Two providers supported out of the box:

  * OpenAI-compatible chat completion  (openai.OpenAI client; works with GPT-5.1,
    Qwen vLLM endpoints exposing an OpenAI schema, DeepSeek via Together, etc.)
  * Anthropic messages API             (anthropic.Anthropic client; Claude)

Keep this module tiny — the goal is a stable interface to pass into
``replan_loop.run_verified_loop`` / ``baseline_nl_critique.run_nl_critique_loop``.
Authentication comes from env vars; we do not manage keys here.
"""

from __future__ import annotations

import os
import re
from typing import Callable, Optional


# ── Plan extraction: strip code fences the planner tends to wrap around ─────

_CODE_FENCE_RE = re.compile(r"```(?:python)?\s*(?P<body>.*?)```", re.DOTALL)


def extract_plan_code(raw: str) -> str:
    """Pull the first Python code block from a planner response, stripping
    ```python fences.  If no fence is found, return the raw response trimmed.
    """
    m = _CODE_FENCE_RE.search(raw)
    if m:
        return m.group("body").strip()
    return raw.strip()


# ── Prompt template ──────────────────────────────────────────────────────────

DEFAULT_SYSTEM_PROMPT = (
    "You are an expert planner. Your task is to write a plan in Python code to "
    "automate a web interaction task. Do not solve the task yourself; only write "
    "the plan. Output ONLY Python code for the plan — no prose, no markdown "
    "fences."
)

# In-context example — the same kind of cheapest-price exemplar the team's
# notebook (Small_models_on_WebMall_planning.ipynb) appends to the prompt
# when generating plans in "Example=True" mode.  Updated to use the current
# WebMall DSL (search_on_page / extract_information_from_page / port 8085 /
# "Type your final answer here…" / "Submit Final Result"), and written so it
# satisfies all of P0–P6 — the LLM should treat it as a structural template,
# not as task content.
EXAMPLE_PLAN_BLOCK = """\
Example: Find the cheapest offer for "Product P" across the four shops.
Example plan (output ONLY Python code like this — no prose, no fences):

stores = [
    "http://localhost:8081",  # E-Store Athletes
    "http://localhost:8082",  # TechTalk
    "http://localhost:8083",  # CamelCases
    "http://localhost:8084",  # Hardware Cafe
]
results = []
for store in stores:
    url = search_on_page(store, "Product P")
    if url is not None:
        price_str = extract_information_from_page("The price of the product as a number")
        if price_str is not None:
            results.append((url, float(price_str)))

if results:
    final_answer = min(results, key=lambda x: x[1])[0]
else:
    final_answer = "Done"

open_page("http://localhost:8085/")
fill_text_field("Type your final answer here...", final_answer)
press_button("Submit Final Result")
"""


def _compose_user_prompt(
    task_prompt: str,
    previous_plan: Optional[str],
    feedback: Optional[str],
    *,
    with_example: bool = False,
) -> str:
    pieces: list[str] = []
    if with_example:
        pieces += [EXAMPLE_PLAN_BLOCK.strip(), ""]
    pieces.append(task_prompt)
    if previous_plan is not None:
        pieces += ["", "Your previous plan was:", "", previous_plan.strip(), ""]
        if feedback:
            pieces += ["Feedback on this plan:", "", feedback.strip(), ""]
        pieces += ["Output ONLY the revised plan as Python code. Do not explain."]
    return "\n".join(pieces)


# ── OpenAI adapter ───────────────────────────────────────────────────────────

def make_openai_planner(
    model: str,
    *,
    temperature: float = 0.0,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    base_url: Optional[str] = None,
    api_key_env: str = "OPENAI_API_KEY",
    extra: Optional[dict] = None,
    with_example: bool = False,
) -> Callable[..., str]:
    """Return a planner callable backed by an OpenAI-compatible chat endpoint.

    Works with:
      * OpenAI (``base_url=None``, ``OPENAI_API_KEY``)
      * Together / DeepInfra (``base_url=https://api.together.xyz/v1``, etc.)
      * A local vLLM server (``base_url=http://localhost:8000/v1``)

    ``with_example=True`` prepends ``EXAMPLE_PLAN_BLOCK`` to every user message,
    matching the team's "Example=True" prompt mode used to generate the jsonl
    plan files in plan_docs/.

    ``extra`` is forwarded verbatim to ``client.chat.completions.create``.
    """
    from openai import OpenAI  # local import so the module is importable w/o openai

    kwargs = {"api_key": os.environ.get(api_key_env)}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    extra = extra or {}

    def planner(task_prompt: str, previous_plan: Optional[str] = None,
                feedback: Optional[str] = None) -> str:
        user = _compose_user_prompt(task_prompt, previous_plan, feedback,
                                    with_example=with_example)
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            **extra,
        )
        raw = resp.choices[0].message.content or ""
        return extract_plan_code(raw)

    return planner


# ── Anthropic adapter ────────────────────────────────────────────────────────

def make_anthropic_planner(
    model: str,
    *,
    temperature: float = 0.0,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    max_tokens: int = 4096,
    api_key_env: str = "ANTHROPIC_API_KEY",
    with_example: bool = False,
) -> Callable[..., str]:
    """Return a planner callable backed by Anthropic's messages API.

    See ``make_openai_planner`` for ``with_example`` semantics.
    """
    from anthropic import Anthropic  # local import

    client = Anthropic(api_key=os.environ.get(api_key_env))

    def planner(task_prompt: str, previous_plan: Optional[str] = None,
                feedback: Optional[str] = None) -> str:
        user = _compose_user_prompt(task_prompt, previous_plan, feedback,
                                    with_example=with_example)
        resp = client.messages.create(
            model=model,
            system=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
        )
        raw = "".join(getattr(b, "text", "") for b in resp.content)
        return extract_plan_code(raw)

    return planner
