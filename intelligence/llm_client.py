"""Thin OpenRouter wrapper used by every intelligence module."""
import asyncio
import json
import os
import re
import time
from typing import Any

import asyncpg
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()

# Overridable for integration testing against scripts/mock_openrouter.py
OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

# ── Global OpenRouter throttle (FIX 7) ──────────────────────────────
# A process-wide limiter shared by every agent: at most MAX_CALLS_PER_MINUTE
# calls in any rolling 60s window, and a hard PAUSE_ON_429 cooldown for ALL
# callers after any 429 so a rate-limit error never cascades mid-build.
_MAX_CALLS_PER_MINUTE = 10
_RATE_WINDOW_SECONDS = 60.0
_PAUSE_ON_429_SECONDS = 60.0

_call_times: list[float] = []
_throttle_lock = asyncio.Lock()
_paused_until = 0.0

# FIX 6: cap simultaneous in-flight OpenRouter calls to bound peak memory on
# the 1GB VPS (separate from the per-minute rate limit above).
_MAX_CONCURRENT_CALLS = 2
_concurrency = asyncio.Semaphore(_MAX_CONCURRENT_CALLS)


def _trip_429_pause() -> None:
    global _paused_until
    _paused_until = time.monotonic() + _PAUSE_ON_429_SECONDS


async def _throttle() -> None:
    """Block until it is safe to make another OpenRouter call under the global
    rate limit / 429 cooldown."""
    while True:
        async with _throttle_lock:
            now = time.monotonic()
            if now < _paused_until:
                wait = _paused_until - now
            else:
                cutoff = now - _RATE_WINDOW_SECONDS
                while _call_times and _call_times[0] < cutoff:
                    _call_times.pop(0)
                if len(_call_times) < _MAX_CALLS_PER_MINUTE:
                    _call_times.append(now)
                    return
                wait = _RATE_WINDOW_SECONDS - (now - _call_times[0])
        await asyncio.sleep(max(wait, 0.05))

# Optional spend logging — when the orchestrator registers a pool, every
# chat call records its cost to llm_spend (feeds the $15/7d alert, spec 6.4)
_spend_pool: asyncpg.Pool | None = None


def set_spend_pool(pool: asyncpg.Pool) -> None:
    global _spend_pool
    _spend_pool = pool


async def _record_spend(model: str, usage: dict) -> None:
    if _spend_pool is None:
        return
    try:
        async with _spend_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO llm_spend (model, prompt_tokens, completion_tokens, cost_usd)
                VALUES ($1, $2, $3, $4)
                """,
                model,
                usage.get("prompt_tokens"),
                usage.get("completion_tokens"),
                float(usage.get("cost") or 0.0),
            )
    except Exception as exc:
        log.warning("llm.spend_record_failed", error=str(exc))

# Model IDs on OpenRouter (spec Section 8 defaults, env-overridable so a
# provider deprecation never requires a code change)
GEMINI_FLASH   = os.environ.get("LLM_MODEL_FAST", "google/gemini-2.5-flash")
DEEPSEEK_V3    = os.environ.get("LLM_MODEL_REASONING", "deepseek/deepseek-chat")
CLAUDE_SONNET  = os.environ.get("LLM_MODEL_CODE", "anthropic/claude-sonnet-4.6")
# Code-gen escalation tier. NOTE: anthropic/claude-fable-5 is listed in
# OpenRouter's /models but is gated ("Fable Mythos access") and 404s on
# call — escalate to Opus, which is both available and more capable.
CLAUDE_OPUS    = os.environ.get("LLM_MODEL_CODE_ESCALATION", "anthropic/claude-opus-4.8")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": "https://github.com/BlitheBot/roblox-game-generator",
        "X-Title": "Autonomous Roblox Game Studio",
        "Content-Type": "application/json",
    }


# Backoff delays of ~5s, 10s, 20s between the 4 attempts (FIX 7), and
# reraise the underlying error so callers (and build_failures) see the real
# HTTPStatusError with its status/body, not an opaque RetryError wrapper.
@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=5, min=5, max=20),
    reraise=True,
)
async def chat(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 4096,
    response_format: dict | None = None,
) -> str:
    """Call OpenRouter chat completions. Returns the assistant message content."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Ask OpenRouter to include cost (credits == USD) in the usage block
        "usage": {"include": True},
    }
    if response_format:
        body["response_format"] = response_format

    # Respect the global rate limit / 429 cooldown before every call
    await _throttle()

    # Cap concurrent in-flight requests (memory bound on the 1GB VPS)
    async with _concurrency:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=_headers(),
                json=body,
            )
            if resp.status_code == 429:
                # Pause every caller for 60s, then let tenacity retry this one
                _trip_429_pause()
                log.warning("llm.rate_limited_429", model=model)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            log.debug(
                "llm.call",
                model=model,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                cost_usd=usage.get("cost"),
            )
            await _record_spend(model, usage)
            return content


_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def _repair_truncated_json(text: str) -> str | None:
    """Best-effort repair of JSON truncated mid-structure (e.g. the model
    hit max_tokens): cut back to the last *complete container* (the last
    balanced `}`/`]`) and close any still-open brackets. Cutting only at
    container boundaries avoids salvaging a half-written object as if it
    were complete. Returns None if nothing is salvageable."""
    last_safe: int | None = None
    in_str = esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "}]":
            last_safe = i + 1          # a container just closed here
    if last_safe is None:
        return None
    prefix = text[:last_safe]
    # Recompute the open brackets for the prefix and close them in reverse.
    stack: list[str] = []
    in_str = esc = False
    for ch in prefix:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()
    return prefix + "".join(reversed(stack))


def _loads_lenient(text: str) -> dict:
    """json.loads, but tolerant of the two malformations a capped LLM reply
    produces: a trailing comma, and truncation at max_tokens. One over-long
    model response must not crash a whole cycle."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # 1) trailing comma before a closer: {"a":1,}  ->  {"a":1}
        try:
            return json.loads(_TRAILING_COMMA_RE.sub(r"\1", text))
        except json.JSONDecodeError:
            pass
        # 2) truncated mid-structure: close at the last complete container
        repaired = _repair_truncated_json(text)
        if repaired is not None:
            try:
                return json.loads(_TRAILING_COMMA_RE.sub(r"\1", repaired))
            except json.JSONDecodeError:
                pass
        raise ValueError(
            f"model returned unparseable JSON ({len(text)} chars, "
            f"truncation likely): {exc}"
        ) from exc


async def chat_json(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 8192,
) -> dict:
    """Call OpenRouter and parse the response as JSON. Tolerant of a reply
    truncated at max_tokens (repaired to the last complete element)."""
    raw = await chat(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    # Strip markdown code fences if model wraps output
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return _loads_lenient(cleaned)
