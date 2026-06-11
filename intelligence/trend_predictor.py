"""
TrendPredictor — scrapes TikTok (via RapidAPI), YouTube Shorts velocity,
and Twitter/X gaming discourse to identify pre-arrival cultural trends.
Uses Gemini Flash to estimate time-to-Roblox for each signal.
"""
import os
import asyncio
from dataclasses import dataclass, field

import httpx
import structlog

from .llm_client import GEMINI_FLASH, chat_json

log = structlog.get_logger()

RAPIDAPI_HOST_TIKTOK = "tiktok-api23.p.rapidapi.com"
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
                params={"region": "US", "count": "30"},
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
        Scrapes YouTube Shorts search for gaming content uploaded in last 72h.
        Velocity = views / hours_since_upload (approximated from rank).
        # TODO: Replace with YouTube Data API v3 if YOUTUBE_API_KEY is set
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    YOUTUBE_SHORTS_URL,
                    params={"search_query": "gaming trending 2025 shorts", "sp": "EgIYAw%3D%3D"},
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
        Scrapes Twitter/X trending gaming discourse.
        Uses nitter.net public mirror for unauthenticated access.
        # TODO: Plug in Twitter API Bearer token if available via TWITTER_BEARER_TOKEN
        """
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    "https://nitter.privacydev.net/search",
                    params={
                        "q": "roblox gaming trend",
                        "f": "tweets",
                        "since": "",
                    },
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RobloxStudioBot/1.0)"},
                    follow_redirects=True,
                )
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "lxml")
                tweets = []
                for tweet in soup.select(".tweet-content")[:20]:
                    text = tweet.get_text(strip=True)
                    if text:
                        tweets.append({"text": text})
                return tweets
        except Exception as exc:
            log.warning("trend_predictor.twitter_failed", error=str(exc))
            return []

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
