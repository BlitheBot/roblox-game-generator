"""Thin OpenRouter wrapper used by every intelligence module."""
import json
import os
from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger()

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

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
        log.debug(
            "llm.call",
            model=model,
            prompt_tokens=data.get("usage", {}).get("prompt_tokens"),
            completion_tokens=data.get("usage", {}).get("completion_tokens"),
        )
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
