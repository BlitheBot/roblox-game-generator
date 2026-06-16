"""Thin OpenRouter wrapper used by every intelligence module."""
import asyncio
import json
import os
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
GEMINI_FLASH   = os.environ.get("LLM_MODEL_FAST", "google/gemini-flash-1.5")
DEEPSEEK_V3    = os.environ.get("LLM_MODEL_REASONING", "deepseek/deepseek-chat")
CLAUDE_SONNET  = os.environ.get("LLM_MODEL_CODE", "anthropic/claude-sonnet-4-6")
CLAUDE_FABLE   = os.environ.get("LLM_MODEL_CODE_ESCALATION", "anthropic/claude-fable-5")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": "https://github.com/BlitheBot/roblox-game-generator",
        "X-Title": "Autonomous Roblox Game Studio",
        "Content-Type": "application/json",
    }


# Backoff delays of ~5s, 10s, 20s between the 4 attempts (FIX 7), and
# reraise the underlying error so callers see the real cause, not RetryError.
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


async def chat_json(
    model: str,
    messages: list[dict],
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> dict:
    """Call OpenRouter and parse the response as JSON."""
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
    return json.loads(cleaned)
