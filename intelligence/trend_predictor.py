"""
TrendPredictor — TikTok trending (RapidAPI), YouTube Shorts view velocity
(Data API, exact 72h window per spec 3.2), and Twitter/X gaming discourse
(RapidAPI) to identify pre-arrival cultural trends.
Uses Gemini Flash to estimate time-to-Roblox for each signal.
"""
import os
import asyncio
from datetime import datetime, timezone
from dataclasses import dataclass, field

import httpx
import structlog

from . import youtube
from .llm_client import GEMINI_FLASH, chat_json

log = structlog.get_logger()

RAPIDAPI_HOST_TIKTOK = "tiktok-api23.p.rapidapi.com"
# RapidAPI X/Twitter provider — env-overridable since RapidAPI providers
# churn; any provider exposing a search endpoint with a compatible
# response shape works (see _fetch_twitter_gaming parsing)
RAPIDAPI_HOST_TWITTER = os.environ.get(
    "RAPIDAPI_HOST_TWITTER", "twitter-api45.p.rapidapi.com"
)
YOUTUBE_SHORTS_URL   = "https://www.youtube.com/results"


@dataclass
class PreArrivalTrend:
    trend_name: str
    platform_origin: str          # tiktok | youtube | twitter
    velocity_score: float         # 0.0–1.0
    estimated_days_to_roblox: int  # 0–30
    suggested_mechanic: str


@dataclass
class TrendPredictorResult:
    pre_arrival_trends: list[PreArrivalTrend] = field(default_factory=list)


class TrendPredictor:
    """Identifies cultural trends outside Roblox that haven't hit the platform yet."""

    def __init__(self) -> None:
        self._rapidapi_key = os.environ.get("RAPIDAPI_KEY", "")

    async def run(self) -> TrendPredictorResult:
        raw_data = await asyncio.gather(
            self._fetch_tiktok_trending(),
            self._fetch_youtube_shorts_velocity(),
            self._fetch_twitter_gaming(),
            return_exceptions=True,
        )
        platform_names = ["tiktok", "youtube", "twitter"]
        items: list[dict] = []
        for platform, result in zip(platform_names, raw_data):
            if isinstance(result, Exception):
                log.warning("trend_predictor.source_failed", platform=platform, error=str(result))
            else:
                items.append({"platform": platform, "data": result})

        trends = await self._analyze_with_llm(items)
        log.info("trend_predictor.complete", trend_count=len(trends))
        return TrendPredictorResult(pre_arrival_trends=trends)

    async def _fetch_tiktok_trending(self) -> list[dict]:
        """Fetch trending TikTok sounds/hashtags via RapidAPI."""
        if not self._rapidapi_key:
            log.warning("trend_predictor.no_rapidapi_key")
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://{RAPIDAPI_HOST_TIKTOK}/api/trending/hashtags",
                headers={
                    "X-RapidAPI-Key": self._rapidapi_key,
                    "X-RapidAPI-Host": RAPIDAPI_HOST_TIKTOK,
                },
                params={"region": os.environ.get("TIKTOK_REGION", "US"), "count": "30"},
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("itemList", data.get("data", []))
            return [
                {
                    "hashtag": item.get("hashtagName", item.get("title", "")),
                    "video_count": item.get("videoCount", 0),
                    "view_count": item.get("viewCount", 0),
                }
                for item in items[:30]
            ]

    async def _fetch_youtube_shorts_velocity(self) -> list[dict]:
        """
        Gaming-category videos uploaded in the last 72 hours (spec 3.2),
        with velocity = views / hours_since_upload from the Data API.
        Without YOUTUBE_API_KEY (or on API failure), falls back to scraping
        with the closest native filters and rank as a velocity proxy.
        """
        if youtube.api_key():
            try:
                videos = await youtube.search_recent(
                    "gaming shorts",
                    hours=72,
                    max_results=20,
                    category_id="20",  # YouTube category 20 = Gaming
                    order="viewCount",
                )
                stats = await youtube.video_stats([v["video_id"] for v in videos])
                now = datetime.now(timezone.utc)
                results = []
                for v in videos:
                    published = datetime.fromisoformat(
                        v["published_at"].replace("Z", "+00:00")
                    )
                    hours_live = max(1.0, (now - published).total_seconds() / 3600)
                    views = stats.get(v["video_id"], 0)
                    results.append(
                        {
                            "title": v["title"],
                            "views": views,
                            "hours_since_upload": round(hours_live, 1),
                            "views_per_hour": round(views / hours_live, 1),
                        }
                    )
                return results
            except Exception as exc:
                log.warning("trend_predictor.youtube_api_failed", error=str(exc))
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    YOUTUBE_SHORTS_URL,
                    # 'this week' upload + short duration filters — no 72h
                    # option exists on youtube.com; exact 72h needs the API
                    params={"search_query": "gaming trending 2025 shorts", "sp": "EgQIAxgD"},
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RobloxStudioBot/1.0)"},
                    follow_redirects=True,
                )
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "lxml")
                results = []
                for i, tag in enumerate(soup.select("a#video-title")[:20]):
                    title = tag.get_text(strip=True)
                    if title:
                        # Proxy for velocity: higher rank = faster rising
                        results.append({"title": title, "rank": i + 1})
                return results
        except Exception as exc:
            log.warning("trend_predictor.youtube_failed", error=str(exc))
            return []

    async def _fetch_twitter_gaming(self) -> list[dict]:
        """
        Twitter/X gaming discourse via RapidAPI (the public Nitter mirrors
        this previously scraped are dead). Reuses RAPIDAPI_KEY; the provider
        host is overridable via RAPIDAPI_HOST_TWITTER. Parsing is defensive
        across the common response shapes RapidAPI X providers return.
        """
        if not self._rapidapi_key:
            log.warning("trend_predictor.no_rapidapi_key_twitter")
            return []
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://{RAPIDAPI_HOST_TWITTER}/search.php",
                headers={
                    "X-RapidAPI-Key": self._rapidapi_key,
                    "X-RapidAPI-Host": RAPIDAPI_HOST_TWITTER,
                },
                params={"query": "roblox gaming trend", "search_type": "Latest"},
            )
            resp.raise_for_status()
            data = resp.json()

        items = data.get("timeline") or data.get("results") or data.get("data") or []
        if isinstance(items, dict):
            items = items.get("tweets") or items.get("list") or []
        tweets = []
        for item in items[:20]:
            if not isinstance(item, dict):
                continue
            text = item.get("text") or item.get("full_text") or item.get("tweet") or ""
            if text:
                tweets.append(
                    {
                        "text": str(text)[:500],
                        "likes": item.get("favorites") or item.get("favorite_count") or 0,
                        "retweets": item.get("retweets") or item.get("retweet_count") or 0,
                    }
                )
        return tweets

    async def _analyze_with_llm(self, raw_items: list[dict]) -> list[PreArrivalTrend]:
        """Use Gemini Flash to classify each raw signal into a pre-arrival trend."""
        payload_str = str(raw_items)[:8000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a gaming trend analyst specializing in Roblox. "
                    "Given raw data from TikTok, YouTube Shorts, and Twitter, "
                    "identify pre-arrival cultural trends that have NOT yet hit Roblox "
                    "but are likely to in the next 1–30 days. "
                    "For each trend estimate: trend_name, platform_origin (tiktok/youtube/twitter), "
                    "velocity_score (0.0–1.0), estimated_days_to_roblox (integer 0–30), "
                    "and suggested_mechanic (one of: idle_tycoon, pet_collect, survival_horror, "
                    "obby, rpg_dungeon, incremental_sim). "
                    "Return JSON with key 'pre_arrival_trends' as an array."
                ),
            },
            {
                "role": "user",
                "content": f"Raw platform data:\n{payload_str}",
            },
        ]
        result = await chat_json(GEMINI_FLASH, messages, temperature=0.2)
        trends = []
        for t in result.get("pre_arrival_trends", []):
            try:
                trends.append(
                    PreArrivalTrend(
                        trend_name=t["trend_name"],
                        platform_origin=t["platform_origin"],
                        velocity_score=float(t["velocity_score"]),
                        estimated_days_to_roblox=int(t["estimated_days_to_roblox"]),
                        suggested_mechanic=t["suggested_mechanic"],
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("trend_predictor.bad_trend", error=str(exc), raw=t)
        return trends
