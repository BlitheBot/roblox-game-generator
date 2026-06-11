"""
NameBlacklist — keeps data/name_blacklist.json populated with the current
top-50 Roblox game titles (explore API) and fuzzy-matches proposed game
titles against it so the ConceptGenerator never ships a near-clone name.

The file self-refreshes when older than 24h (lazy, on read) and the
orchestrator also refreshes it on a daily schedule so a long-idle file
never goes stale. Build it explicitly with:

    python -m intelligence.name_blacklist
"""
import asyncio
import json
import pathlib
import time
from datetime import datetime, timezone

import structlog
from rapidfuzz import fuzz

from .roblox_games import fetch_top_games

log = structlog.get_logger()

BLACKLIST_PATH = pathlib.Path(__file__).parent.parent / "data" / "name_blacklist.json"
REFRESH_INTERVAL_SECONDS = 24 * 3600
SIMILARITY_THRESHOLD = 0.75
TOP_GAMES_COUNT = 50


async def refresh_blacklist(force: bool = False) -> list[str]:
    """Fetch the current top-50 titles and write data/name_blacklist.json.
    Keeps the existing file on fetch failure — a stale blacklist beats an
    empty one. Returns the active title list either way."""
    existing = _read_file()
    if not force and existing is not None and not _is_stale(existing):
        return existing["titles"]

    games = await fetch_top_games(TOP_GAMES_COUNT)
    if not games:
        log.warning("name_blacklist.refresh_failed_keeping_existing")
        return existing["titles"] if existing else []

    titles = [g["name"] for g in games if g.get("name")]
    BLACKLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    BLACKLIST_PATH.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": "roblox_explore_api_top50",
                "titles": titles,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    log.info("name_blacklist.refreshed", count=len(titles))
    return titles


async def get_blacklist() -> list[str]:
    """Active blacklist titles, refreshing first when older than 24h."""
    return await refresh_blacklist(force=False)


def check_similarity(title: str, blacklist: list[str]) -> tuple[str, float] | None:
    """Returns (closest_title, score 0-1) when `title` scores above the
    0.75 threshold against any blacklisted title, else None."""
    best: tuple[str, float] | None = None
    for existing in blacklist:
        # token_sort_ratio catches word-order shuffles ("Tycoon Pet" vs
        # "Pet Tycoon"); plain ratio catches near-verbatim copies
        score = max(
            fuzz.ratio(title.lower(), existing.lower()),
            fuzz.token_sort_ratio(title.lower(), existing.lower()),
        ) / 100.0
        if best is None or score > best[1]:
            best = (existing, score)
    if best is not None and best[1] > SIMILARITY_THRESHOLD:
        return best
    return None


def _read_file() -> dict | None:
    if not BLACKLIST_PATH.exists():
        return None
    try:
        data = json.loads(BLACKLIST_PATH.read_text(encoding="utf-8"))
        if isinstance(data.get("titles"), list):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("name_blacklist.read_failed", error=str(exc))
    return None


def _is_stale(data: dict) -> bool:
    try:
        fetched = datetime.fromisoformat(data["fetched_at"])
    except (KeyError, ValueError):
        return True
    age = time.time() - fetched.timestamp()
    return age > REFRESH_INTERVAL_SECONDS


if __name__ == "__main__":
    titles = asyncio.run(refresh_blacklist(force=True))
    print(f"name_blacklist.json written with {len(titles)} titles")
