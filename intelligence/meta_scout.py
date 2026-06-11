"""
MetaScout — collects trending signals from Roblox Games API, Reddit,
Roblox DevForum, and YouTube then scores them with Gemini Flash.
"""
import os
import asyncio
from dataclasses import dataclass, field

import httpx
import praw
import structlog
from bs4 import BeautifulSoup

from . import youtube
from .llm_client import GEMINI_FLASH, chat_json
from .roblox_games import fetch_top_games

log = structlog.get_logger()

DEVFORUM_URL     = "https://devforum.roblox.com/latest.json"


@dataclass
class Signal:
    genre: str
    mechanic_tag: str
    signal_strength: float
    source: str
    sustained_ccu_indicator: bool
    # Spec 15: country where the trend predominantly originates; non-English
    # markets (ES, PT, DE, FR, PH) flag the game for localization downstream
    platform_origin_country: str = "US"


@dataclass
class MetaScoutResult:
    signals: list[Signal] = field(default_factory=list)


class MetaScout:
    """Gathers raw trend signals each cycle."""

    def __init__(self) -> None:
        self._reddit = praw.Reddit(
            client_id=os.environ["REDDIT_CLIENT_ID"],
            client_secret=os.environ["REDDIT_CLIENT_SECRET"],
            user_agent=os.environ.get("REDDIT_USER_AGENT", "roblox-game-studio/1.0"),
            check_for_async=False,
        )

    async def run(self) -> MetaScoutResult:
        raw_data = await asyncio.gather(
            self._fetch_roblox_top_games(),
            asyncio.to_thread(self._fetch_reddit_hot),  # PRAW is sync
            self._fetch_devforum_trending(),
            self._fetch_youtube_recent(),
            return_exceptions=True,
        )
        # Filter out exceptions and flatten
        items: list[dict] = []
        sources = ["roblox_games", "reddit", "devforum", "youtube"]
        for source, result in zip(sources, raw_data):
            if isinstance(result, Exception):
                log.warning("meta_scout.source_failed", source=source, error=str(result))
            else:
                items.append({"source": source, "data": result})

        signals = await self._analyze_with_llm(items)
        log.info("meta_scout.complete", signal_count=len(signals))
        return MetaScoutResult(signals=signals)

    async def _fetch_roblox_top_games(self) -> list[dict]:
        """Top 50 games by live CCU via the explore API."""
        games = await fetch_top_games(50)
        if not games:
            raise RuntimeError("explore API returned no games")
        return games

    def _fetch_reddit_hot(self) -> list[dict]:
        """Sync PRAW call wrapped for asyncio — returns hot r/roblox posts."""
        posts = []
        try:
            for submission in self._reddit.subreddit("roblox").hot(limit=30):
                posts.append(
                    {
                        "title": submission.title,
                        "score": submission.score,
                        "url": submission.url,
                        "flair": submission.link_flair_text,
                    }
                )
        except Exception as exc:
            log.warning("meta_scout.reddit_failed", error=str(exc))
        return posts

    async def _fetch_devforum_trending(self) -> list[dict]:
        """Scrape Roblox DevForum latest/trending threads."""
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                DEVFORUM_URL,
                headers={"User-Agent": "RobloxStudioBot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
            topics = data.get("topic_list", {}).get("topics", [])
            return [
                {
                    "title": t.get("title"),
                    "views": t.get("views"),
                    "posts_count": t.get("posts_count"),
                    "tags": t.get("tags", []),
                }
                for t in topics[:25]
            ]

    async def _fetch_youtube_recent(self) -> list[dict]:
        """
        YouTube videos tagged 'roblox' uploaded in the last 72 hours,
        sorted by upload date (spec 3.1). The Data API's publishedAfter
        gives the exact 72h window; without YOUTUBE_API_KEY (or on API
        failure) we scrape with the closest native filter (this week).
        """
        if youtube.api_key():
            try:
                videos = await youtube.search_recent("roblox", hours=72, max_results=20)
                return [
                    {"title": v["title"], "published_at": v["published_at"]}
                    for v in videos
                ]
            except Exception as exc:
                log.warning("meta_scout.youtube_api_failed", error=str(exc))
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                params = {
                    "search_query": "roblox new game 2025",
                    # 'this week' upload filter — youtube.com has no 72h
                    # option; exact 72h needs YOUTUBE_API_KEY above
                    "sp": "EgIIAw%3D%3D",
                }
                resp = await client.get(
                    "https://www.youtube.com/results",
                    params=params,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (compatible; RobloxStudioBot/1.0)"
                        )
                    },
                    follow_redirects=True,
                )
                soup = BeautifulSoup(resp.text, "lxml")
                titles = [
                    span.get_text()
                    for span in soup.select("a#video-title")[:20]
                ]
                return [{"title": t} for t in titles]
        except Exception as exc:
            log.warning("meta_scout.youtube_failed", error=str(exc))
            return []

    async def _analyze_with_llm(self, raw_items: list[dict]) -> list[Signal]:
        """Send aggregated raw data to Gemini Flash for signal extraction."""
        payload_str = str(raw_items)[:8000]  # token guard
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Roblox game market analyst. Analyze the provided raw data "
                    "from multiple sources (Roblox Games API, Reddit, DevForum, YouTube) "
                    "and identify the top trending game opportunities. "
                    "For each signal, determine the genre, the core mechanic tag, "
                    "signal strength (0.0–1.0), and whether it shows sustained CCU. "
                    "Valid mechanic_tags: idle_tycoon, pet_collect, survival_horror, "
                    "obby, rpg_dungeon, incremental_sim. "
                    "Also tag each signal with platform_origin_country — the ISO 3166 "
                    "country code where the trend predominantly originates (e.g. US, ES, "
                    "PT, DE, FR, PH); use US when unclear. "
                    "Return JSON with key 'signals' containing an array of objects each with: "
                    "genre, mechanic_tag, signal_strength, source, sustained_ccu_indicator, "
                    "platform_origin_country."
                ),
            },
            {
                "role": "user",
                "content": f"Raw trend data:\n{payload_str}",
            },
        ]
        result = await chat_json(GEMINI_FLASH, messages, temperature=0.2)
        signals = []
        for s in result.get("signals", []):
            try:
                signals.append(
                    Signal(
                        genre=s["genre"],
                        mechanic_tag=s["mechanic_tag"],
                        signal_strength=float(s["signal_strength"]),
                        source=s["source"],
                        sustained_ccu_indicator=bool(s.get("sustained_ccu_indicator", False)),
                        platform_origin_country=str(
                            s.get("platform_origin_country") or "US"
                        ).upper(),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("meta_scout.bad_signal", error=str(exc), raw=s)
        return signals
