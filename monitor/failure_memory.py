"""
FailureMemory (improvement 6) — remembers which mechanic+genre combos
keep producing dead games so the pipeline stops re-trying them.

A game "fails" when it has been live 30+ days and no metrics sample ever
exceeded 5 CCU. Each failed game increments its combo's fail_count once
(published_games.failure_recorded guards double counting). At 3 failures
the combo is permanently suppressed: the ScoringEngine hard-excludes it
regardless of signal strength until `!unsuppress <mechanic> <genre>`.
"""
from datetime import datetime, timezone

import asyncpg
import structlog

log = structlog.get_logger()

FAILURE_CCU = 5
FAILURE_AGE_DAYS = 30
SUPPRESS_AT_FAILS = 3


class FailureMemory:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record_failures(self) -> list[tuple[str, str]]:
        """Scan for newly failed games, increment their combos, suppress
        any combo reaching the threshold. Returns combos that became
        suppressed this run (for Discord alerting)."""
        async with self._pool.acquire() as conn:
            failed_games = await conn.fetch(
                """
                SELECT pg.id, pg.game_title, cq.mechanic_tag, cq.genre
                FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.failure_recorded = FALSE
                  AND pg.published_at <= NOW() - make_interval(days => $1)
                  AND pg.status IN ('live', 'flagged')
                  AND NOT EXISTS (
                      SELECT 1 FROM game_metrics gm
                      WHERE gm.game_id = pg.id AND gm.ccu > $2
                  )
                """,
                FAILURE_AGE_DAYS,
                FAILURE_CCU,
            )

            newly_suppressed: list[tuple[str, str]] = []
            for game in failed_games:
                combo = (game["mechanic_tag"], game["genre"])
                row = await conn.fetchrow(
                    """
                    INSERT INTO failure_memory
                        (mechanic_tag, genre, fail_count, last_failed)
                    VALUES ($1, $2, 1, $3)
                    ON CONFLICT (mechanic_tag, genre) DO UPDATE
                        SET fail_count = failure_memory.fail_count + 1,
                            last_failed = EXCLUDED.last_failed
                    RETURNING fail_count, permanently_suppressed
                    """,
                    combo[0],
                    combo[1],
                    datetime.now(timezone.utc),
                )
                await conn.execute(
                    "UPDATE published_games SET failure_recorded = TRUE WHERE id = $1",
                    game["id"],
                )
                log.info(
                    "failure_memory.failure_recorded",
                    game=game["game_title"],
                    mechanic=combo[0],
                    genre=combo[1],
                    fail_count=row["fail_count"],
                )
                if row["fail_count"] >= SUPPRESS_AT_FAILS and not row["permanently_suppressed"]:
                    await conn.execute(
                        """
                        UPDATE failure_memory SET permanently_suppressed = TRUE
                        WHERE mechanic_tag = $1 AND genre = $2
                        """,
                        combo[0],
                        combo[1],
                    )
                    newly_suppressed.append(combo)
                    log.warning(
                        "failure_memory.combo_suppressed",
                        mechanic=combo[0],
                        genre=combo[1],
                    )
        return newly_suppressed

    async def get_suppressed(self) -> set[tuple[str, str]]:
        """All permanently suppressed (mechanic_tag, genre) combos."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT mechanic_tag, genre FROM failure_memory
                WHERE permanently_suppressed = TRUE
                """
            )
        return {(row["mechanic_tag"], row["genre"]) for row in rows}

    async def unsuppress(self, mechanic_tag: str, genre: str) -> bool:
        """Re-enable a suppressed combo (resets its strike count so it
        gets three fresh chances). Returns False when no suppressed row
        matched."""
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """
                UPDATE failure_memory
                SET permanently_suppressed = FALSE, fail_count = 0
                WHERE mechanic_tag = $1 AND genre = $2
                  AND permanently_suppressed = TRUE
                RETURNING mechanic_tag
                """,
                mechanic_tag,
                genre,
            )
        if updated is not None:
            log.info("failure_memory.unsuppressed", mechanic=mechanic_tag, genre=genre)
        return updated is not None
