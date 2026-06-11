"""
PerformanceMonitor (spec 6.1) — hourly metrics polling per live game.

Metrics: CCU, session length, D1/D7/D30 retention, revenue, thumbnail CTR.
Also detects post-publish moderation takedowns (spec 16) and genre
account bans (spec 19), pausing the affected account only.

Live CCU comes from the public games API. Retention/session/CTR/revenue
require the Open Cloud Analytics API, which is rolling out gradually —
those calls degrade to NULL gracefully and are marked TODO.
"""
import uuid
from datetime import datetime, timezone

import asyncpg
import httpx
import structlog

from .discord_reporter import DiscordReporter

log = structlog.get_logger()

GAMES_API = "https://games.roblox.com/v1/games"


class PerformanceMonitor:
    def __init__(self, pool: asyncpg.Pool, reporter: DiscordReporter) -> None:
        self._pool = pool
        self._reporter = reporter

    async def run(self) -> None:
        games = await self._live_games()
        if not games:
            return

        universe_ids = [g["universe_id"] for g in games]
        live_stats = await self._fetch_live_stats(universe_ids)

        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            for game in games:
                stats = live_stats.get(game["universe_id"])
                if stats is None:
                    # Universe missing from the public API response — likely
                    # moderated/taken down (spec 16)
                    await self._handle_possible_moderation(game)
                    continue

                await conn.execute(
                    """
                    INSERT INTO game_metrics
                        (id, game_id, timestamp, ccu, session_length_avg,
                         d1_retention, d7_retention, revenue_robux, thumbnail_ctr)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                    """,
                    uuid.uuid4(),
                    game["id"],
                    now,
                    stats["playing"],
                    None,  # TODO: session length via Open Cloud Analytics API
                    None,  # TODO: D1 retention via Open Cloud Analytics API
                    None,  # TODO: D7 retention via Open Cloud Analytics API
                    0,     # TODO: revenue via Open Cloud economy/analytics API
                    None,  # TODO: thumbnail CTR via Open Cloud Analytics API
                )
        log.info("performance_monitor.cycle_complete", games=len(games))

    async def _live_games(self) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, universe_id, place_id, game_title, genre_account, status
                FROM published_games
                WHERE status IN ('live', 'breakout', 'flagged')
                """
            )
        return [dict(row) for row in rows]

    async def _fetch_live_stats(self, universe_ids: list[int]) -> dict[int, dict]:
        """Public games API gives live `playing` (CCU) per universe."""
        stats: dict[int, dict] = {}
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                # API accepts up to 100 ids per call
                for i in range(0, len(universe_ids), 100):
                    chunk = universe_ids[i : i + 100]
                    resp = await client.get(
                        GAMES_API,
                        params={"universeIds": ",".join(str(u) for u in chunk)},
                        headers={"User-Agent": "RobloxStudioBot/1.0"},
                    )
                    resp.raise_for_status()
                    for item in resp.json().get("data", []):
                        stats[item["id"]] = {
                            "playing": item.get("playing", 0),
                            "visits": item.get("visits", 0),
                            "favorites": item.get("favoritedCount", 0),
                        }
        except Exception as exc:
            log.warning("performance_monitor.stats_fetch_failed", error=str(exc))
        return stats

    async def _handle_possible_moderation(self, game: dict) -> None:
        """Spec 16: pause the genre account, alert, log the incident."""
        async with self._pool.acquire() as conn:
            already = await conn.fetchval(
                "SELECT status FROM published_games WHERE id = $1", game["id"]
            )
            if already == "moderated":
                return
            await conn.execute(
                "UPDATE published_games SET status = 'moderated' WHERE id = $1",
                game["id"],
            )
            await conn.execute(
                """
                UPDATE genre_accounts SET status = 'paused', last_checked = NOW()
                WHERE genre = $1
                """,
                game["genre_account"],
            )
            await conn.execute(
                """
                INSERT INTO moderation_incidents (game_id, genre_account, notes)
                VALUES ($1, $2, $3)
                """,
                game["id"],
                game["genre_account"],
                "universe missing from public games API — presumed moderated",
            )
        await self._reporter.alert(
            f"Game **{game['game_title']}** on account [{game['genre_account']}] "
            f"was moderated — place ID {game['place_id']}. Publishing on this "
            f"account is paused. Awaiting your review "
            f"(`!resume {game['genre_account']}`)."
        )
        log.error(
            "performance_monitor.moderation_detected",
            game=game["game_title"],
            account=game["genre_account"],
        )

    async def check_account_health(self) -> None:
        """
        Spec 19: detect banned/restricted genre accounts each cycle.
        TODO: account status isn't directly exposed via Open Cloud; an API
        key that starts returning 401 on a previously working account is the
        practical ban signal. We probe with a cheap authenticated call.
        """
        from publish.open_cloud_publisher import APIS_BASE, load_genre_account

        async with self._pool.acquire() as conn:
            accounts = await conn.fetch(
                "SELECT genre FROM genre_accounts WHERE status = 'active'"
            )
        for row in accounts:
            genre = row["genre"]
            try:
                account = load_genre_account(genre)
            except RuntimeError:
                continue
            try:
                async with httpx.AsyncClient(timeout=20) as client:
                    resp = await client.get(
                        f"{APIS_BASE}/cloud/v2/universes/{account.universe_id}",
                        headers={"x-api-key": account.api_key},
                    )
                if resp.status_code in (401, 403):
                    async with self._pool.acquire() as conn:
                        await conn.execute(
                            """
                            UPDATE genre_accounts
                            SET status = 'paused', last_checked = NOW()
                            WHERE genre = $1
                            """,
                            genre,
                        )
                    await self._reporter.alert(
                        f"Account for genre [{genre}] returned {resp.status_code} — "
                        f"possibly banned/restricted. Publishing paused for this "
                        f"account only (`!resume-account {genre}` after review)."
                    )
                else:
                    async with self._pool.acquire() as conn:
                        await conn.execute(
                            "UPDATE genre_accounts SET last_checked = NOW() WHERE genre = $1",
                            genre,
                        )
            except Exception as exc:
                log.warning("performance_monitor.account_check_failed", genre=genre, error=str(exc))
