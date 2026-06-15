"""
VideoPipeline (marketing step 7) — runs script → visuals → assembly →
platform publishes for a freshly published game.

Gated by ENABLE_MARKETING_VIDEOS (default false). MARKETING_PLATFORMS
(comma-separated, default "youtube,tiktok,instagram") enables platforms
individually; a platform with missing credentials is skipped with a log
instead of failing. One platform failing never aborts the others.

Results land in marketing_publishes; a Discord summary (DM via the
approval bot when available, webhook otherwise) fires when all enabled
platforms are done.
"""
import json
import os
import pathlib
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import asyncpg
import structlog

from monitor.discord_reporter import DiscordReporter

from .publishers import instagram, tiktok, youtube
from .script_generator import generate_script
from .video_assembler import assemble_video
from .visual_generator import generate_visuals

if TYPE_CHECKING:
    from publish.discord_bot import ApprovalBot

log = structlog.get_logger()

ALL_PLATFORMS = {
    "youtube": youtube,
    "tiktok": tiktok,
    "instagram": instagram,
}


def marketing_enabled() -> bool:
    return os.environ.get("ENABLE_MARKETING_VIDEOS", "").strip().lower() in (
        "true", "1", "yes",
    )


def enabled_platforms() -> list[str]:
    raw = os.environ.get("MARKETING_PLATFORMS", "youtube,tiktok,instagram")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


class VideoPipeline:
    def __init__(
        self,
        pool: asyncpg.Pool,
        reporter: DiscordReporter,
        bot: "ApprovalBot | None" = None,
    ) -> None:
        self._pool = pool
        self._reporter = reporter
        self._bot = bot

    async def run(self, published_game_id: str, build_dir: pathlib.Path) -> None:
        """Generate and publish the marketing video for a published game.
        `build_dir` is the archived build directory (holds concept.json,
        description.txt, thumbnail.png); the video lands in
        {build_dir}/marketing/final_video.mp4."""
        if not marketing_enabled():
            log.info("marketing.disabled_skipping")
            return

        game = await self._load_game(published_game_id)
        if game is None:
            log.warning("marketing.game_not_found", game_id=published_game_id)
            return
        concept = game["concept"]
        marketing_dir = build_dir / "marketing"
        marketing_dir.mkdir(parents=True, exist_ok=True)

        # Steps 1-3: script → stills → video (a failure here aborts the
        # whole video, there is nothing to publish without it)
        script = await generate_script(concept)
        images = await generate_visuals(concept, marketing_dir)
        video_path = await assemble_video(images, script, marketing_dir)

        description = ""
        description_file = build_dir / "description.txt"
        if description_file.exists():
            description = description_file.read_text(encoding="utf-8")
        thumbnail = build_dir / "thumbnail.png"

        metadata = {
            "game_title": game["game_title"],
            "genre": concept.get("mechanic_tag", "game"),
            "hook": script.get("hook", ""),
            "description": description or concept.get("tagline", ""),
            "hashtags": script.get("suggested_hashtags", []),
            "tags": script.get("suggested_hashtags", []) + [game["genre_account"], "roblox"],
            "thumbnail_path": str(thumbnail) if thumbnail.exists() else None,
        }

        # Steps 4-6: publish to each enabled platform, never aborting on
        # a single platform's failure
        results: dict[str, tuple[bool, str]] = {}
        for name in enabled_platforms():
            module = ALL_PLATFORMS.get(name)
            if module is None:
                log.warning("marketing.unknown_platform", platform=name)
                continue
            if not module.configured():
                log.info("marketing.platform_not_configured", platform=name)
                continue
            try:
                url = await module.publish(video_path, metadata)
                results[name] = (True, url)
            except Exception as exc:
                log.error(
                    "marketing.platform_failed", platform=name, error=str(exc)
                )
                results[name] = (False, str(exc)[:500])
            await self._log_publish(published_game_id, name, results[name])

        await self._notify(game["game_title"], results)

    # ── helpers ─────────────────────────────────────────────

    async def _load_game(self, game_id: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT pg.game_title, pg.genre_account, cq.concept_json
                FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.id = $1
                """,
                uuid.UUID(game_id),
            )
        if row is None:
            return None
        concept = (
            json.loads(row["concept_json"])
            if isinstance(row["concept_json"], str)
            else dict(row["concept_json"])
        )
        return {
            "game_title": row["game_title"],
            "genre_account": row["genre_account"],
            "concept": concept,
        }

    async def _log_publish(
        self, game_id: str, platform: str, result: tuple[bool, str]
    ) -> None:
        success, detail = result
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO marketing_publishes
                    (game_id, platform, video_url, published_at, status, error_message)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                uuid.UUID(game_id),
                platform,
                detail if success else None,
                datetime.now(timezone.utc),
                "success" if success else "failed",
                None if success else detail,
            )

    async def _notify(self, game_title: str, results: dict) -> None:
        if not results:
            return
        lines = [f"🎬 Marketing video published for **{game_title}**"]
        for platform, (success, detail) in results.items():
            mark = "✅" if success else "❌"
            lines.append(f"{mark} {platform.capitalize()}: {detail}")
        message = "\n".join(lines)

        sent_dm = False
        if self._bot is not None and self._bot.is_ready():
            try:
                owner = await self._bot.fetch_user(self._bot._owner_id)
                await owner.send(message[:1900])
                sent_dm = True
            except Exception as exc:
                log.warning("marketing.dm_failed", error=str(exc))
        if not sent_dm:
            await self._reporter.alert(message)
