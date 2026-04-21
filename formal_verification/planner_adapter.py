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


def _compose_user_prompt(task_prompt: str, previous_plan: Optional[str], feedback: Optional[str]) -> str:
    if previous_plan is None:
        return task_prompt
    pieces = [task_prompt, "", "Your previous plan was:", "", previous_plan.strip(), ""]
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
) -> Callable[..., str]:
    """Return a planner callable backed by an OpenAI-compatible chat endpoint.

    Works with:
      * OpenAI (``base_url=None``, ``OPENAI_API_KEY``)
      * Together / DeepInfra (``base_url=https://api.together.xyz/v1``, etc.)
      * A local vLLM server (``base_url=http://localhost:8000/v1``)

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
        user = _compose_user_prompt(task_prompt, previous_plan, feedback)
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
) -> Callable[..., str]:
    """Return a planner callable backed by Anthropic's messages API."""
    from anthropic import Anthropic  # local import

    client = Anthropic(api_key=os.environ.get(api_key_env))

    def planner(task_prompt: str, previous_plan: Optional[str] = None,
                feedback: Optional[str] = None) -> str:
        user = _compose_user_prompt(task_prompt, previous_plan, feedback)
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
