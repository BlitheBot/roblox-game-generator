"""Thin OpenRouter wrapper used by every intelligence module."""
import json
import os
from typing import Any

import asyncpg
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()

# Overridable for integration testing against scripts/mock_openrouter.py
OPENROUTER_BASE = os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")

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

# Canonical model IDs on OpenRouter
GEMINI_FLASH   = "google/gemini-flash-1.5"
DEEPSEEK_V3    = "deepseek/deepseek-chat"
CLAUDE_SONNET  = "anthropic/claude-sonnet-4-6"
CLAUDE_FABLE   = "anthropic/claude-fable-5"


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
        "HTTP-Referer": "https://github.com/BlitheBot/roblox-game-generator",
        "X-Title": "Autonomous Roblox Game Studio",
        "Content-Type": "application/json",
    }


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
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

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{OPENROUTER_BASE}/chat/completions",
            headers=_headers(),
            json=body,
        )
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
