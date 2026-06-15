"""
Cross-game referral system (improvement 5).

Every build embeds a CrossPromoManager script that erects in-game
billboards ("Play our other game: <title>") for the other live games on
the same genre account, with teleports to their places. The sibling
list is baked into the build at generation time via the
{{CROSS_PROMO_LUA}} placeholder.

Roblox offers no channel to push fresh data into an already-published
place (MessagingService is same-universe only), so when a new game
publishes, on_game_published() marks every sibling on that account as
due for update — the daily update cycle then rebuilds and republishes
them with the new billboard list baked in.
"""
import uuid

import asyncpg
import structlog

log = structlog.get_logger()


async def get_siblings(
    pool: asyncpg.Pool,
    genre_account: str,
    exclude_game_id: str | None = None,
) -> list[dict]:
    """Live games on `genre_account` as billboard entries:
    [{"title", "universe_id", "place_id"}], newest first."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, game_title, universe_id, place_id
            FROM published_games
            WHERE genre_account = $1
              AND status IN ('live', 'breakout', 'flagged')
            ORDER BY published_at DESC
            """,
            genre_account,
        )
    exclude = uuid.UUID(exclude_game_id) if exclude_game_id else None
    return [
        {
            "title": row["game_title"],
            "universe_id": row["universe_id"],
            "place_id": row["place_id"],
        }
        for row in rows
        if exclude is None or row["id"] != exclude
    ]


async def on_game_published(pool: asyncpg.Pool, published_game_id: str) -> int:
    """Mark every sibling on the new game's account due for update so the
    daily update cycle republishes them with refreshed billboards.
    Returns the number of siblings queued."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT genre_account FROM published_games WHERE id = $1",
            uuid.UUID(published_game_id),
        )
        if row is None:
            return 0
        siblings = await conn.fetch(
            """
            SELECT id FROM published_games
            WHERE genre_account = $1
              AND id != $2
              AND status IN ('live', 'breakout', 'flagged')
            """,
            row["genre_account"],
            uuid.UUID(published_game_id),
        )
        # Clearing last_update:{id} makes UpdateCadence treat the game as
        # immediately due on the next daily update run; the cross_promo
        # marker tells the update cycle to push a rebuilt place version
        # (not just a description refresh) so the new billboard ships
        for sibling in siblings:
            await conn.execute(
                "DELETE FROM orchestrator_state WHERE key = $1",
                f"last_update:{sibling['id']}",
            )
            await conn.execute(
                """
                INSERT INTO orchestrator_state (key, value, updated_at)
                VALUES ($1, 'pending', NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = 'pending', updated_at = NOW()
                """,
                f"cross_promo_refresh:{sibling['id']}",
            )
    if siblings:
        log.info(
            "cross_promotion.siblings_queued_for_update",
            account=row["genre_account"],
            count=len(siblings),
        )
    return len(siblings)
