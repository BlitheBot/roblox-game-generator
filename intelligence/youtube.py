"""
YouTube Data API v3 helpers — shared by MetaScout (recent uploads, spec
3.1) and TrendPredictor (Shorts view velocity, spec 3.2).

The spec requires an exact "last 72 hours" window, which youtube.com's
native search filters can't express (hour/day/week only) — the Data API's
publishedAfter parameter can. When YOUTUBE_API_KEY is unset, callers fall
back to scraping with the closest native filter.
"""
import os
from datetime import datetime, timedelta, timezone

import httpx
import structlog

log = structlog.get_logger()

YOUTUBE_API_BASE = "https://www.googleapis.com/youtube/v3"


def api_key() -> str:
    return os.environ.get("YOUTUBE_API_KEY", "")


async def search_recent(
    query: str,
    hours: int = 72,
    max_results: int = 20,
    category_id: str | None = None,
    order: str = "date",
) -> list[dict]:
    """Videos published within the last `hours`, exactly bounded via
    publishedAfter. Returns [{video_id, title, published_at}]."""
    published_after = (
        datetime.now(timezone.utc) - timedelta(hours=hours)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    params: dict[str, str | int] = {
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": order,
        "publishedAfter": published_after,
        "maxResults": max_results,
        "key": api_key(),
    }
    if category_id:
        params["videoCategoryId"] = category_id
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{YOUTUBE_API_BASE}/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    videos = []
    for item in data.get("items", []):
        video_id = (item.get("id") or {}).get("videoId")
        snippet = item.get("snippet") or {}
        if video_id and snippet.get("title"):
            videos.append(
                {
                    "video_id": video_id,
                    "title": snippet["title"],
                    "published_at": snippet.get("publishedAt", ""),
                }
            )
    return videos


async def video_stats(video_ids: list[str]) -> dict[str, int]:
    """View counts per video id (single videos.list call, max 50 ids)."""
    if not video_ids:
        return {}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{YOUTUBE_API_BASE}/videos",
            params={
                "part": "statistics",
                "id": ",".join(video_ids[:50]),
                "key": api_key(),
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return {
        item["id"]: int((item.get("statistics") or {}).get("viewCount", 0))
        for item in data.get("items", [])
        if item.get("id")
    }
