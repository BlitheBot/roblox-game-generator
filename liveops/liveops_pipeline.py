"""
LiveOpsPipeline (LiveOps step 5) — weekly Monday-10:00 cycle:

  1. select top 5 live games by 7-day average CCU
  2. per game (sequentially, to respect Open Cloud rate limits):
     content drop patch → balance patch → seasonal reskin (if a window
     is near) → ONE rebuild (LuauAgent → Rojo → AutoValidator) →
     publish_update → persist the patched concept
  3. Discord digest + liveops_log row

A failure on one game logs it and moves on — the cycle never aborts.
Gated by ENABLE_LIVEOPS (default false).
"""
import json
import os
import uuid

import asyncpg
import structlog

from build.cross_promotion import get_siblings
from monitor.discord_reporter import DiscordReporter
from publish.open_cloud_publisher import OpenCloudPublisher

from .balance_tuner import generate_balance_patch
from .content_drop_generator import apply_content_patch, generate_content_patch
from .seasonal_reskin import maybe_reskin
from .top_games_selector import select_top_games, set_queue_status

log = structlog.get_logger()


def liveops_enabled() -> bool:
    return os.environ.get("ENABLE_LIVEOPS", "").strip().lower() in ("true", "1", "yes")


class LiveOpsPipeline:
    def __init__(
        self,
        pool: asyncpg.Pool,
        publisher: OpenCloudPublisher,
        reporter: DiscordReporter,
    ) -> None:
        self._pool = pool
        self._publisher = publisher
        self._reporter = reporter

    async def run_weekly_cycle(self, meta_keywords: list[str]) -> None:
        if not liveops_enabled():
            log.info("liveops.disabled_skipping")
            return

        games = await select_top_games(self._pool)
        if not games:
            log.info("liveops.no_games_with_metrics")
            return

        summary: dict = {
            "content_drops": [],
            "balance_changes": [],
            "seasonal_reskins": [],
            "failed": [],
        }

        for game in games:
            await set_queue_status(self._pool, game["queue_id"], "building")
            try:
                await self._update_one(game, meta_keywords, summary)
                await set_queue_status(self._pool, game["queue_id"], "published")
            except Exception as exc:
                log.error(
                    "liveops.game_failed",
                    game=game["game_title"],
                    error=str(exc)[:500],
                )
                summary["failed"].append(f"{game['game_title']}: {str(exc)[:120]}")
                await set_queue_status(self._pool, game["queue_id"], "failed")

        await self._finish(len(games), summary)

    async def _update_one(
        self, game: dict, meta_keywords: list[str], summary: dict
    ) -> None:
        concept = await self._load_concept(game["concept_id"])

        # Content drop (config-only patch)
        patch = await generate_content_patch(concept, meta_keywords)
        drop_changes = apply_content_patch(concept, patch)
        if drop_changes:
            summary["content_drops"].append(
                f"{game['game_title']}: {patch.get('drop_summary', '')} "
                f"({len(drop_changes)} additions)"
            )

        # Balance tune (threshold-triggered)
        balance = await generate_balance_patch(self._pool, game["game_id"], concept)
        if balance is not None:
            _, change_lines = balance
            summary["balance_changes"].append(
                f"{game['game_title']}: " + "; ".join(change_lines)
            )

        # Seasonal reskin (only when a window is active/near)
        build_dir = await self._archived_build_dir(game)
        reskin_changes = await maybe_reskin(self._pool, game, concept, build_dir)
        if reskin_changes:
            summary["seasonal_reskins"].append(
                f"{game['game_title']}: " + "; ".join(reskin_changes)
            )

        # One rebuild + republish carrying every patch from this cycle
        await self._rebuild_and_publish(game, concept)
        await self._persist_concept(game["concept_id"], concept)

    # ── build/publish ───────────────────────────────────────

    async def _rebuild_and_publish(self, game: dict, concept: dict) -> None:
        from build.auto_validator import AutoValidator
        from build.luau_agent import LuauAgent
        from build.rojo_builder import RojoBuilder

        concept["cross_promo_siblings"] = await get_siblings(
            self._pool, game["genre_account"], exclude_game_id=game["game_id"]
        )
        build_dir = await LuauAgent().generate(concept, f"liveops_{game['game_id']}")
        rojo_result = await RojoBuilder().build(build_dir)
        validation = await AutoValidator().validate(build_dir, rojo_result)
        if not validation.passed or rojo_result.rbxl_path is None:
            raise RuntimeError(
                "liveops rebuild failed validation: "
                + "; ".join(validation.failures[:3])
            )
        published = await self._publisher.publish_update(
            game["genre_account"], game["place_id"], rojo_result.rbxl_path
        )
        if not published:
            raise RuntimeError("publish_update returned False (see publisher logs)")

    async def _load_concept(self, concept_id: str) -> dict:
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                "SELECT concept_json FROM concept_queue WHERE id = $1",
                uuid.UUID(concept_id),
            )
        if raw is None:
            raise RuntimeError(f"concept {concept_id} not found")
        return json.loads(raw) if isinstance(raw, str) else dict(raw)

    async def _persist_concept(self, concept_id: str, concept: dict) -> None:
        # Drop build-time-only keys before persisting
        stored = {k: v for k, v in concept.items() if k != "cross_promo_siblings"}
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE concept_queue SET concept_json = $2 WHERE id = $1",
                uuid.UUID(concept_id),
                json.dumps(stored),
            )

    async def _archived_build_dir(self, game: dict):
        """The game's archived build dir (for original thumbnail lookup)."""
        import pathlib

        builds_root = pathlib.Path(os.environ.get("BUILDS_ROOT", "/builds"))
        async with self._pool.acquire() as conn:
            build_dir = await conn.fetchval(
                "SELECT build_dir FROM pending_approvals WHERE concept_id = $1 "
                "ORDER BY created_at DESC LIMIT 1",
                uuid.UUID(game["concept_id"]),
            )
        if build_dir:
            name = pathlib.Path(build_dir).name
            archived = builds_root / "archive" / game["genre_account"] / name
            if archived.exists():
                return archived
        fallback = builds_root / "archive" / game["genre_account"] / game["game_id"]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    # ── reporting ───────────────────────────────────────────

    async def _finish(self, total: int, summary: dict) -> None:
        updated = total - len(summary["failed"])
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO liveops_log (games_updated, games_failed, summary_json)
                VALUES ($1, $2, $3)
                """,
                updated,
                len(summary["failed"]),
                json.dumps(summary),
            )

        def section(title: str, lines: list[str]) -> str:
            if not lines:
                return ""
            return f"\n**{title}:**\n" + "\n".join(f"• {line}" for line in lines)

        message = (
            f"🛠️ Weekly LiveOps complete — {updated}/{total} games updated successfully"
            + section("Content drops", summary["content_drops"])
            + section("Balance changes", summary["balance_changes"])
            + section("Seasonal reskins", summary["seasonal_reskins"])
            + section("Failed", summary["failed"])
        )
        await self._reporter.alert(message[:1900])
        log.info("liveops.cycle_complete", updated=updated, failed=len(summary["failed"]))
