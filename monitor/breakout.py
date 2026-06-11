"""
Breakout detection + auto-scaling (spec 6.2) and update cadence (spec 14).

Breakout: CCU > 200 sustained 24h →
  1. daily content-drop cadence for this game
  2. regenerate thumbnail with higher-effort FLUX prompt
  3. refresh description daily instead of weekly
  4. Discord alert

Underperforming: CCU < 10 for 30 days AND zero revenue for 14 days →
flag in dashboard (status 'flagged'); never auto-unpublish.
"""
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog

from .discord_reporter import DiscordReporter

log = structlog.get_logger()

BREAKOUT_CCU = 200
BREAKOUT_WINDOW_HOURS = 24
# Hourly sampling → require most of a day's samples above threshold
BREAKOUT_MIN_SAMPLES = 20

UNDERPERFORM_CCU = 10
UNDERPERFORM_CCU_DAYS = 30
UNDERPERFORM_REVENUE_DAYS = 14


class BreakoutDetector:
    def __init__(self, pool: asyncpg.Pool, reporter: DiscordReporter) -> None:
        self._pool = pool
        self._reporter = reporter

    async def run(self) -> list[str]:
        """Returns game_ids that newly hit breakout (for thumbnail regen)."""
        new_breakouts = await self._detect_breakouts()
        await self._detect_underperformers()
        return new_breakouts

    async def _detect_breakouts(self) -> list[str]:
        window_start = datetime.now(timezone.utc) - timedelta(hours=BREAKOUT_WINDOW_HOURS)
        new_breakouts: list[str] = []
        async with self._pool.acquire() as conn:
            candidates = await conn.fetch(
                """
                SELECT pg.id, pg.game_title,
                       COUNT(*) AS samples,
                       MIN(gm.ccu) AS min_ccu,
                       MAX(gm.ccu) AS max_ccu
                FROM published_games pg
                JOIN game_metrics gm ON gm.game_id = pg.id
                WHERE pg.status = 'live'
                  AND gm.timestamp > $1
                GROUP BY pg.id, pg.game_title
                HAVING COUNT(*) >= $2 AND MIN(gm.ccu) > $3
                """,
                window_start,
                BREAKOUT_MIN_SAMPLES,
                BREAKOUT_CCU,
            )
            for game in candidates:
                await conn.execute(
                    "UPDATE published_games SET status = 'breakout' WHERE id = $1",
                    game["id"],
                )
                new_breakouts.append(str(game["id"]))
                await self._reporter.alert(
                    f"🚀 Game **{game['game_title']}** hit breakout threshold — "
                    f"{game['max_ccu']} CCU (sustained > {BREAKOUT_CCU} for "
                    f"{BREAKOUT_WINDOW_HOURS}h). Switching to daily update cadence."
                )
                log.info("breakout.detected", game=game["game_title"])
        return new_breakouts

    async def _detect_underperformers(self) -> None:
        now = datetime.now(timezone.utc)
        ccu_window = now - timedelta(days=UNDERPERFORM_CCU_DAYS)
        revenue_window = now - timedelta(days=UNDERPERFORM_REVENUE_DAYS)
        async with self._pool.acquire() as conn:
            flagged = await conn.fetch(
                """
                SELECT pg.id, pg.game_title
                FROM published_games pg
                WHERE pg.status = 'live'
                  AND pg.published_at < $1
                  -- no CCU sample >= threshold in the window
                  AND NOT EXISTS (
                      SELECT 1 FROM game_metrics gm
                      WHERE gm.game_id = pg.id
                        AND gm.timestamp > $1
                        AND gm.ccu >= $2
                  )
                  -- zero revenue in the revenue window
                  AND NOT EXISTS (
                      SELECT 1 FROM game_metrics gm
                      WHERE gm.game_id = pg.id
                        AND gm.timestamp > $3
                        AND gm.revenue_robux > 0
                  )
                """,
                ccu_window,
                UNDERPERFORM_CCU,
                revenue_window,
            )
            for game in flagged:
                await conn.execute(
                    "UPDATE published_games SET status = 'flagged' WHERE id = $1",
                    game["id"],
                )
                log.info("breakout.underperformer_flagged", game=game["game_title"])


class UpdateCadence:
    """Spec 14: which live games are due for an update this cycle."""

    CADENCE_DAYS = {"breakout": 1, "live": 7, "flagged": 30}

    @classmethod
    async def games_due_for_update(cls, pool: asyncpg.Pool) -> list[dict]:
        """
        A game is due when its last description refresh (tracked via
        orchestrator_state key 'last_update:{game_id}') is older than its
        cadence. Updates themselves run through LuauAgent → AutoValidator →
        OpenCloudPublisher (Phase 4 integration).
        """
        due: list[dict] = []
        now = datetime.now(timezone.utc)
        async with pool.acquire() as conn:
            games = await conn.fetch(
                """
                SELECT id, game_title, status, genre_account
                FROM published_games
                WHERE status IN ('live', 'breakout', 'flagged')
                """
            )
            for game in games:
                cadence = cls.CADENCE_DAYS[game["status"]]
                last_str = await conn.fetchval(
                    "SELECT value FROM orchestrator_state WHERE key = $1",
                    f"last_update:{game['id']}",
                )
                last = datetime.fromisoformat(last_str) if last_str else None
                if last is None or (now - last) >= timedelta(days=cadence):
                    due.append(dict(game))
        return due

    @staticmethod
    async def mark_updated(pool: asyncpg.Pool, game_id: str) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_state (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                f"last_update:{game_id}",
                datetime.now(timezone.utc).isoformat(),
            )
