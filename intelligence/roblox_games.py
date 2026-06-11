"""
Shared top-games fetch via the Roblox explore API.

The legacy `roblox.com/games/list-json` endpoint was removed (404s);
the explore API is the current public, unauthenticated source for
charting games. Used by MetaScout (trend signals) and GapAnalyzer
(differentiation baseline).
"""
import uuid

import httpx
import structlog

log = structlog.get_logger()

EXPLORE_SORTS_URL = "https://apis.roblox.com/explore-api/v1/get-sorts"


async def fetch_top_games(limit: int = 50) -> list[dict]:
    """Top games by live player count, deduped across explore sorts.
    Returns [] on any failure — callers degrade gracefully."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                EXPLORE_SORTS_URL,
                params={"sessionId": str(uuid.uuid4())},
                headers={"User-Agent": "RobloxStudioBot/1.0"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        log.warning("roblox_games.explore_fetch_failed", error=str(exc))
        return []

    games_by_universe: dict[int, dict] = {}
    for sort in data.get("sorts", []):
        for game in sort.get("games") or []:
            universe_id = game.get("universeId")
            if not universe_id or game.get("isSponsored"):
                continue
            if universe_id not in games_by_universe:
                games_by_universe[universe_id] = {
                    "universe_id": universe_id,
                    "name": game.get("name", ""),
                    "playing": game.get("playerCount", 0),
                    "up_votes": game.get("totalUpVotes", 0),
                }

    top = sorted(games_by_universe.values(), key=lambda g: g["playing"], reverse=True)
    log.info("roblox_games.fetched", count=len(top[:limit]))
    return top[:limit]
