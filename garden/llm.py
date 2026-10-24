"""The only place the app talks to an LLM.

Every call goes through `call_structured`, which:
  - checks the per-session budget BEFORE calling (token cap + call cap),
  - asks for JSON that must validate against a Pydantic model,
  - records usage (input, cached, output, latency, cost) to logs/usage.jsonl
    and to the session's Budget so the UI can show a usage panel.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from . import config

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    """Raised before a call that would go over the session's token or call cap."""


class LLMError(RuntimeError):
    """The model call failed or returned output that did not match the schema."""


class ContentFiltered(LLMError):
    """The provider's safety filter blocked the prompt (e.g. a jailbreak attempt)."""


@dataclass
class CallRecord:
    ts: str
    session_id: str
    run_id: str
    agent: str
    model: str
    input_tokens: int
    cached_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float
    ok: bool
    note: str = ""


@dataclass
class Budget:
    """Per-session spend tracker. Lives in Streamlit session_state."""

    session_id: str
    token_cap: int = config.SESSION_TOKEN_BUDGET
    call_cap: int = config.MAX_CALLS_PER_SESSION
    calls: list[CallRecord] = field(default_factory=list)

    @property
    def tokens_used(self) -> int:
        return sum(c.input_tokens + c.output_tokens for c in self.calls)

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def tokens_left(self) -> int:
        return max(0, self.token_cap - self.tokens_used)

    def check(self) -> None:
        if len(self.calls) >= self.call_cap:
            raise BudgetExceeded(f"Session call limit reached ({self.call_cap} AI calls).")
        if self.tokens_used >= self.token_cap:
            raise BudgetExceeded(f"Session token budget used up ({self.token_cap:,} tokens).")


def request_cost(model: str, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    p = config.PRICES.get(model, config.PRICES["gpt-6-luna"])
    cached = min(cached_tokens, input_tokens)
    return (
        (input_tokens - cached) * p["input"]
        + cached * p["cached_input"]
        + output_tokens * p["output"]
    ) / 1_000_000


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    portkey = os.getenv("PORTKEY_API_KEY", "").strip()
    if portkey:
        # Class pattern: OpenAI SDK pointed at the Portkey gateway.
        return OpenAI(
            api_key=portkey,
            base_url=config.PORTKEY_BASE_URL,
            default_headers={"x-portkey-provider": "openai"},
        )
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if openai_key:
        return OpenAI(api_key=openai_key)
    raise LLMError(
        "No API key found. Put PORTKEY_API_KEY (or OPENAI_API_KEY) in a .env file in this "
        "repo folder or the folder above it. See .env.example."
    )


def _log(record: CallRecord) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    with config.USAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record.__dict__) + "\n")


def call_structured(
    *,
    agent: str,
    instructions: str,
    user_input: str,
    schema: type[T],
    budget: Budget,
    run_id: str = "",
    cache_key: str | None = None,
) -> T:
    """Run one structured LLM call and return the validated Pydantic object."""
    budget.check()
    client = get_client()
    kwargs = dict(
        model=config.MODEL_NAME,
        instructions=instructions,
        input=user_input,
        text_format=schema,
        max_output_tokens=config.MAX_OUTPUT_TOKENS,
        reasoning={"effort": os.getenv("REASONING_EFFORT", "low")},
    )
    if cache_key:
        kwargs["prompt_cache_key"] = cache_key

    start = time.perf_counter()
    response = None
    error = ""
    try:
        response = client.responses.parse(**kwargs)
    except Exception as exc:  # network, auth, schema rejection
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    latency_ms = int((time.perf_counter() - start) * 1000)

    usage = getattr(response, "usage", None)
    in_tok = getattr(usage, "input_tokens", 0) or 0
    out_tok = getattr(usage, "output_tokens", 0) or 0
    details = getattr(usage, "input_tokens_details", None)
    cached = getattr(details, "cached_tokens", 0) or 0
    parsed = getattr(response, "output_parsed", None) if response is not None else None
    if response is not None and parsed is None:
        error = "Model output did not match the required schema."

    record = CallRecord(
        ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        session_id=budget.session_id,
        run_id=run_id,
        agent=agent,
        model=config.MODEL_NAME,
        input_tokens=in_tok,
        cached_tokens=cached,
        output_tokens=out_tok,
        latency_ms=latency_ms,
        cost_usd=round(request_cost(config.MODEL_NAME, in_tok, cached, out_tok), 8),
        ok=not error,
        note=error,
    )
    budget.calls.append(record)
    _log(record)

    if error:
        if "content management policy" in error or "content_filter" in error:
            raise ContentFiltered(error)
        raise LLMError(error)
    return parsed
