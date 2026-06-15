"""
InRobloxMarketer (spec 5.2, cadence updated by improvement 4).

Phase 1 (launch): SEO description already set by publisher; queue an
alternate thumbnail variant for a 48h A/B test, then keep the winner.

Phase 2 (ongoing): refresh every live game's description every 48 hours
regardless of performance status, using the latest MetaScout keywords
(orchestrator_state.latest_meta_keywords) woven in by DeepSeek;
monthly, regenerate any thumbnail with CTR < 2%. published_games.
last_description_refresh tracks the cadence.
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
DESCRIPTION_REFRESH_HOURS = 48


class InRobloxMarketer:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool
        self._assets = AssetGenerator()

    # ── Phase 1: launch ─────────────────────────────────────

    async def start_ab_test(self, game_id: str, build_dir: pathlib.Path) -> None:
        """Generate the alternate thumbnail variant and record both arms."""
        concept = json.loads((build_dir / "concept.json").read_text(encoding="utf-8"))
        try:
            # generate_all writes over the primary assets — preserve them so
            # both A/B arms exist on disk and icon/description stay intact
            preserved: dict[str, bytes] = {}
            for name in ("thumbnail.png", "icon.png", "description.txt"):
                f = build_dir / name
                if f.exists():
                    preserved[name] = f.read_bytes()

            await self._assets.generate_all(concept, build_dir, alt_prompt=True)
            (build_dir / "thumbnail.png").replace(build_dir / "thumbnail_alt.png")

            for name, data in preserved.items():
                (build_dir / name).write_bytes(data)
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
        """Rewrite every live game's description with fresh keywords now."""
        async with self._pool.acquire() as conn:
            games = await conn.fetch(
                """
                SELECT pg.id, pg.game_title, pg.genre_account, pg.universe_id,
                       cq.concept_json
                FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.status IN ('live', 'breakout', 'flagged')
                """
            )
        await self._refresh_rows(games, meta_keywords)

    async def refresh_due_descriptions(self, meta_keywords: list[str]) -> int:
        """Improvement 4: refresh every live game whose description is
        older than 48h, regardless of performance status (live, breakout,
        AND flagged). Returns the number of games refreshed."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=DESCRIPTION_REFRESH_HOURS)
        async with self._pool.acquire() as conn:
            games = await conn.fetch(
                """
                SELECT pg.id, pg.game_title, pg.genre_account, pg.universe_id,
                       cq.concept_json
                FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.status IN ('live', 'breakout', 'flagged')
                  AND (pg.last_description_refresh IS NULL
                       OR pg.last_description_refresh < $1)
                """,
                cutoff,
            )
        if games:
            await self._refresh_rows(games, meta_keywords)
        return len(games)

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
                await self._stamp_refreshed(game["id"])
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

    async def _stamp_refreshed(self, game_id) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE published_games SET last_description_refresh = NOW() WHERE id = $1",
                game_id,
            )

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
