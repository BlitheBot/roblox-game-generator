"""
TopGamesSelector (LiveOps step 1) — picks the top 5 live games by
average CCU over the last 7 days and queues them in liveops_queue with
a 'full' update (content drop + balance tune + seasonal reskin).
"""
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog

log = structlog.get_logger()

TOP_N = 5
WINDOW_DAYS = 7


async def select_top_games(pool: asyncpg.Pool) -> list[dict]:
    """Queue this week's top games; returns
    [{"queue_id", "game_id", "game_title", "genre_account", "place_id",
      "universe_id", "concept_id", "avg_ccu"}]."""
    window_start = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    week_start = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT pg.id, pg.game_title, pg.genre_account, pg.place_id,
                   pg.universe_id, pg.concept_id,
                   AVG(gm.ccu) AS avg_ccu
            FROM published_games pg
            JOIN game_metrics gm ON gm.game_id = pg.id
            WHERE pg.status IN ('live', 'breakout')
              AND gm.timestamp > $1
            GROUP BY pg.id
            ORDER BY AVG(gm.ccu) DESC
            LIMIT $2
            """,
            window_start,
            TOP_N,
        )

        selected: list[dict] = []
        for row in rows:
            queue_id = uuid.uuid4()
            await conn.execute(
                """
                INSERT INTO liveops_queue
                    (id, game_id, week_start, update_type, status)
                VALUES ($1, $2, $3, 'full', 'queued')
                """,
                queue_id,
                row["id"],
                week_start,
            )
            selected.append(
                {
                    "queue_id": str(queue_id),
                    "game_id": str(row["id"]),
                    "game_title": row["game_title"],
                    "genre_account": row["genre_account"],
                    "place_id": row["place_id"],
                    "universe_id": row["universe_id"],
                    "concept_id": str(row["concept_id"]),
                    "avg_ccu": float(row["avg_ccu"] or 0),
                }
            )

    log.info("liveops.top_games_selected", count=len(selected))
    return selected


async def set_queue_status(pool: asyncpg.Pool, queue_id: str, status: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE liveops_queue SET status = $2 WHERE id = $1",
            uuid.UUID(queue_id),
            status,
        )
