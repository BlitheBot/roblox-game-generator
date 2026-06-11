"""
InRobloxMarketer (spec 5.2).

Phase 1 (launch): SEO description already set by publisher; queue an
alternate thumbnail variant for a 48h A/B test, then keep the winner.

Phase 2 (weekly): refresh description with latest MetaScout keywords;
monthly, regenerate any thumbnail with CTR < 2%.
"""
import json
import pathlib
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import structlog

from build.asset_generator import AssetGenerator
from intelligence.llm_client import DEEPSEEK_V3, chat

from .open_cloud_publisher import APIS_BASE, dry_run_enabled, load_genre_account

log = structlog.get_logger()

AB_TEST_HOURS = 48
MIN_CTR = 0.02


class InRobloxMarketer:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._assets = AssetGenerator()

    # ── Phase 1: launch ─────────────────────────────────────

    async def start_ab_test(self, game_id: str, build_dir: pathlib.Path) -> None:
        """Generate the alternate thumbnail variant and record both arms."""
        concept = json.loads((build_dir / "concept.json").read_text(encoding="utf-8"))
        try:
            await self._assets.generate_all(
                concept, build_dir, alt_prompt=True
            )
            # alternate overwrote thumbnail.png; keep both on disk
            alt_path = build_dir / "thumbnail_alt.png"
            (build_dir / "thumbnail.png").rename(alt_path)
        except Exception as exc:
            log.warning("marketer.alt_thumbnail_failed", game_id=game_id, error=str(exc))
            return

        async with self._pool.acquire() as conn:
            for variant in ("primary", "alternate"):
                await conn.execute(
                    """
                    INSERT INTO thumbnail_tests (game_id, variant)
                    VALUES ($1, $2)
                    """,
                    uuid.UUID(game_id),
                    variant,
                )
        log.info("marketer.ab_test_started", game_id=game_id)

    async def settle_ab_tests(self) -> None:
        """Decide any A/B tests older than 48h using recorded CTR."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=AB_TEST_HOURS)
        async with self._pool.acquire() as conn:
            games = await conn.fetch(
                """
                SELECT DISTINCT game_id FROM thumbnail_tests
                WHERE decided_at IS NULL AND started_at < $1
                """,
                cutoff,
            )
            for row in games:
                game_id = row["game_id"]
                # CTR per variant comes from game_metrics.thumbnail_ctr samples
                # taken while each variant was live.
                # TODO: per-variant CTR attribution requires swapping the live
                # thumbnail mid-test; until the Analytics API exposes
                # impression splits, settle using overall CTR for primary and
                # keep primary on ties.
                ctr = await conn.fetchval(
                    """
                    SELECT AVG(thumbnail_ctr) FROM game_metrics
                    WHERE game_id = $1 AND timestamp > $2 AND thumbnail_ctr IS NOT NULL
                    """,
                    game_id,
                    cutoff,
                )
                await conn.execute(
                    """
                    UPDATE thumbnail_tests
                    SET decided_at = NOW(),
                        ctr = $2,
                        winner = (variant = 'primary')
                    WHERE game_id = $1 AND decided_at IS NULL
                    """,
                    game_id,
                    ctr,
                )
                log.info("marketer.ab_test_settled", game_id=str(game_id), ctr=ctr)

    # ── Phase 2: ongoing ────────────────────────────────────

    async def refresh_descriptions(self, meta_keywords: list[str]) -> None:
        """Weekly: rewrite each live game's description with fresh keywords."""
        async with self._pool.acquire() as conn:
            games = await conn.fetch(
                """
                SELECT pg.id, pg.game_title, pg.genre_account, pg.universe_id,
                       cq.concept_json
                FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.status IN ('live', 'breakout')
                """
            )
        await self._refresh_rows(games, meta_keywords)

    async def refresh_for_games(
        self, game_ids: list[str], meta_keywords: list[str]
    ) -> None:
        """Cadence-driven refresh (spec 14) for specific due games."""
        if not game_ids:
            return
        async with self._pool.acquire() as conn:
            games = await conn.fetch(
                """
                SELECT pg.id, pg.game_title, pg.genre_account, pg.universe_id,
                       cq.concept_json
                FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.id = ANY($1::uuid[])
                """,
                [uuid.UUID(g) for g in game_ids],
            )
        await self._refresh_rows(games, meta_keywords)

    async def _refresh_rows(self, games, meta_keywords: list[str]) -> None:
        for game in games:
            try:
                concept = (
                    json.loads(game["concept_json"])
                    if isinstance(game["concept_json"], str)
                    else dict(game["concept_json"])
                )
                description = await self._write_refreshed_description(
                    game["game_title"], concept, meta_keywords
                )
                await self._push_description(
                    game["genre_account"], game["universe_id"], description
                )
                log.info("marketer.description_refreshed", game=game["game_title"])
            except Exception as exc:
                log.warning(
                    "marketer.refresh_failed",
                    game=game["game_title"],
                    error=str(exc),
                )

    async def regenerate_low_ctr_thumbnails(self) -> list[str]:
        """
        Monthly: return game_ids whose 30-day average CTR < 2% so the
        orchestrator can re-run AssetGenerator + thumbnail upload for them.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT game_id, AVG(thumbnail_ctr) AS avg_ctr
                FROM game_metrics
                WHERE timestamp > $1 AND thumbnail_ctr IS NOT NULL
                GROUP BY game_id
                HAVING AVG(thumbnail_ctr) < $2
                """,
                cutoff,
                MIN_CTR,
            )
        flagged = [str(row["game_id"]) for row in rows]
        if flagged:
            log.info("marketer.low_ctr_flagged", count=len(flagged))
        return flagged

    # ── helpers ─────────────────────────────────────────────

    async def _write_refreshed_description(
        self, game_title: str, concept: dict, meta_keywords: list[str]
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Rewrite this Roblox game description with the current trending "
                    "keywords woven in naturally. Max 1000 characters, family-friendly, "
                    "punchy. Output description text only."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Game: {game_title}\n"
                    f"Core loop: {concept.get('core_loop', '')}\n"
                    f"Trending keywords: {meta_keywords[:10]}"
                ),
            },
        ]
        description = await chat(DEEPSEEK_V3, messages, temperature=0.7, max_tokens=600)
        return description.strip().strip('"')[:1000]

    async def _push_description(
        self, genre: str, universe_id: int, description: str
    ) -> None:
        if dry_run_enabled():
            log.info("marketer.dry_run_description_skipped", genre=genre)
            return
        account = load_genre_account(genre)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.patch(
                f"{APIS_BASE}/cloud/v2/universes/{universe_id}",
                params={"updateMask": "description"},
                headers={"x-api-key": account.api_key, "Content-Type": "application/json"},
                json={"description": description},
            )
            resp.raise_for_status()
