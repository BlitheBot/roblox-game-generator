"""
ApprovalGate (spec Section 12) — supervised-mode pause between
AutoValidator and OpenCloudPublisher.

While supervised mode is active, finished builds are parked in
pending_approvals and a Discord DM preview is sent (title, concept
summary, thumbnail, one-line approve/skip command). A scheduled
processor publishes approved rows and finalizes skipped ones. After
APPROVALS_TO_AUTONOMY approved publishes, supervised mode disables
itself; SUPERVISED_MODE=true re-enables it at any time.

In autonomous mode the same queue is used with rows pre-approved, so
every publish gets the rate-limit retry semantics for free.
"""
import json
import os
import pathlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import asyncpg
import structlog

from intelligence.llm_client import DEEPSEEK_V3, chat
from monitor.discord_reporter import DiscordReporter

from .build_archive import archive_build, discard_build
from .marketer import InRobloxMarketer
from .open_cloud_publisher import OpenCloudPublisher, PublishResult, dry_run_enabled

if TYPE_CHECKING:
    from build.pipeline import BuildOutput
    from .discord_bot import ApprovalBot

log = structlog.get_logger()

APPROVALS_TO_AUTONOMY = 5
# A row approved but unpublished for longer than this is treated as stuck
STUCK_PUBLISH_MINUTES = 30


class ApprovalGate:
    def __init__(
        self,
        pool: asyncpg.Pool,
        reporter: DiscordReporter,
        bot: "ApprovalBot | None" = None,
    ) -> None:
        self._pool = pool
        self._reporter = reporter
        self._bot = bot

    # ── mode ────────────────────────────────────────────────

    async def is_supervised(self) -> bool:
        """SUPERVISED_MODE env overrides; otherwise DB state governs so the
        auto-disable after 5 approvals can take effect."""
        env = os.environ.get("SUPERVISED_MODE", "").strip().lower()
        if env in ("true", "1", "yes"):
            return True
        if env in ("false", "0", "no"):
            return False
        async with self._pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = 'supervised_mode_active'"
            )
        return (val or "true") == "true"

    # ── intake ──────────────────────────────────────────────

    async def submit(self, output: "BuildOutput", genre: str) -> None:
        """Park a finished build. Supervised → 'pending' + DM preview;
        autonomous → pre-approved, published on the next processor run."""
        supervised = await self.is_supervised()
        status = "pending" if supervised else "approved"
        concept = output.concept
        summary = (
            f"{concept.get('tagline', '')}\n"
            f"Core loop: {concept.get('core_loop', '')}"
        ).strip() or "(no summary available)"
        game_title = concept.get("game_title", "Untitled")

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO pending_approvals
                    (game_id, concept_id, game_title, summary, build_dir, genre,
                     status, decided_at, rbxl_path, thumbnail_path, description)
                VALUES ($1, $2, $3, $4, $5, $6, $7,
                        CASE WHEN $7 = 'approved' THEN NOW() END, $8, $9, $10)
                ON CONFLICT (game_id) DO NOTHING
                """,
                uuid.UUID(output.game_id),
                uuid.UUID(output.concept_id),
                game_title,
                summary,
                str(output.build_dir),
                genre,
                status,
                str(output.rbxl_path),
                str(output.thumbnail_path),
                output.description,
            )

        if not supervised:
            log.info("approval_gate.auto_approved", game_id=output.game_id)
            return

        preview = (
            f"Publish approval needed — **{game_title}** [{genre}]\n"
            f"{summary}\n"
            f"Respond: `!approve {output.game_id}` or `!skip {output.game_id}`"
        )
        sent_dm = False
        if self._bot is not None and self._bot.is_ready():
            try:
                await self._bot.send_approval_request(
                    output.game_id,
                    game_title,
                    summary,
                    str(output.thumbnail_path),
                    genre,
                )
                sent_dm = True
            except Exception as exc:
                log.warning("approval_gate.dm_failed", error=str(exc))
        if not sent_dm:
            # Webhook fallback — same preview, minus the thumbnail attachment
            await self._reporter.alert(preview)
        log.info("approval_gate.queued", game_id=output.game_id, title=game_title)

    # ── decision processing (scheduled every few minutes) ───

    async def process_decisions(
        self, publisher: OpenCloudPublisher, marketer: InRobloxMarketer
    ) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM pending_approvals
                WHERE status IN ('approved', 'skipped') AND processed_at IS NULL
                ORDER BY created_at
                """
            )
        for row in rows:
            # One row's failure must not block the rest of the queue
            try:
                if row["status"] == "skipped":
                    await self._finalize_skip(row)
                else:
                    await self._publish_approved(row, publisher, marketer)
            except Exception as exc:
                log.error(
                    "approval_gate.row_failed",
                    game_id=str(row["game_id"]),
                    error=str(exc),
                )
                await self._log_publish_failure(row["concept_id"], str(exc))
                # A swallowed exception here was the silent-publish bug: the
                # operator was told "publishing soon" and never heard again.
                await self._reporter.alert(
                    f"Publish error for **{row['game_title']}** [{row['genre']}]: "
                    f"{str(exc)[:400]}. The row is left queued — fix the cause and "
                    f"`!retry {row['game_id']}`, or it will retry next cycle."
                )

        # Loudly flag anything approved but still unpublished past the SLA
        await self.alert_stuck_rows()

    async def alert_stuck_rows(self) -> None:
        """Spec/FIX 1: alert when a row has been approved but unpublished for
        more than STUCK_PUBLISH_MINUTES, deduped per game via
        orchestrator_state so the operator hears about it exactly once."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_PUBLISH_MINUTES)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT game_id, game_title, genre FROM pending_approvals
                WHERE status = 'approved'
                  AND processed_at IS NULL
                  AND decided_at IS NOT NULL
                  AND decided_at < $1
                """,
                cutoff,
            )
        for row in rows:
            # Fire exactly once per stuck row, ever — the presence of the
            # state key means we've already alerted, so never alert again
            # (previously a 1h cooldown re-fired every monitor cycle).
            key = f"alert_cooldown:stuck_publish:{row['game_id']}"
            if await self._state_get(key):
                continue
            await self._reporter.alert(
                f"Publish stuck — **{row['game_title']}** has been approved for "
                f"{STUCK_PUBLISH_MINUTES}+ minutes without publishing. Check "
                f"credentials for the `{row['genre']}` account "
                f"(`!retry {row['game_id']}`)."
            )
            await self._state_set(key, datetime.now(timezone.utc).isoformat())

    async def retry(
        self, game_id_str: str, publisher: OpenCloudPublisher, marketer: InRobloxMarketer
    ) -> str:
        """FIX 1: manually re-trigger publishing for a stuck approved row.
        Returns a human-readable result string for the Discord reply."""
        try:
            game_id = uuid.UUID(game_id_str)
        except ValueError:
            return f"`{game_id_str}` is not a valid game id."
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM pending_approvals
                WHERE game_id = $1 AND status = 'approved' AND processed_at IS NULL
                """,
                game_id,
            )
        if row is None:
            return f"No stuck approved publish found for `{game_id_str}`."
        try:
            await self._publish_approved(row, publisher, marketer)
        except Exception as exc:
            return f"Retry failed for **{row['game_title']}**: {str(exc)[:400]}"
        async with self._pool.acquire() as conn:
            still_pending = await conn.fetchval(
                "SELECT processed_at IS NULL FROM pending_approvals WHERE game_id = $1",
                game_id,
            )
        if still_pending:
            return (
                f"**{row['game_title']}** is still pending (rate-limited or deferred) "
                f"— it will keep retrying automatically."
            )
        return f"✅ Re-published **{row['game_title']}**."

    async def _log_publish_failure(self, concept_id, error: str) -> None:
        """FIX 1: record a publish-stage failure to build_failures so it shows
        up in the failure-rate alert and the audit trail, not just the log."""
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO build_failures
                        (id, concept_id, timestamp, stage, error_message,
                         model_used, retry_count)
                    VALUES ($1, $2, NOW(), 'publish', $3, 'opencloud', 0)
                    """,
                    uuid.uuid4(),
                    concept_id,
                    str(error)[:4000],
                )
        except Exception as exc:
            log.warning("approval_gate.publish_failure_log_failed", error=str(exc))

    async def _state_get(self, key: str) -> str | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = $1", key
            )

    async def _state_set(self, key: str, value: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_state (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                key,
                value,
            )

    async def _finalize_skip(self, row) -> None:
        async with self._pool.acquire() as conn:
            # 'failed' is the only terminal non-published concept status
            await conn.execute(
                "UPDATE concept_queue SET status = 'failed' WHERE id = $1",
                row["concept_id"],
            )
            await conn.execute(
                "UPDATE pending_approvals SET processed_at = NOW() WHERE game_id = $1",
                row["game_id"],
            )
        # Spec 18: /builds/active only holds in-progress work
        discard_build(pathlib.Path(row["build_dir"]))
        log.info("approval_gate.skip_finalized", game_id=str(row["game_id"]))

    async def _publish_approved(
        self, row, publisher: OpenCloudPublisher, marketer: InRobloxMarketer
    ) -> None:
        if dry_run_enabled():
            await self._mark_processed(row["game_id"])
            await self._reporter.alert(
                f"DRY RUN — built **{row['game_title']}** [{row['genre']}] "
                f"(rbxl: {row['rbxl_path']}). Publish skipped."
            )
            log.info(
                "approval_gate.dry_run_publish_skipped",
                game_id=str(row["game_id"]),
                title=row["game_title"],
            )
            return

        log.info(
            "approval_gate.processing", game_id=str(row["game_id"]), title=row["game_title"]
        )
        log.info(
            "approval_gate.publishing",
            game_id=str(row["game_id"]),
            title=row["game_title"],
            genre=row["genre"],
        )
        result = await publisher.publish(
            concept_id=str(row["concept_id"]),
            rbxl_path=pathlib.Path(row["rbxl_path"]),
            thumbnail_path=pathlib.Path(row["thumbnail_path"]),
            game_title=row["game_title"],
            description=row["description"] or "",
            genre=row["genre"],
        )
        if result.rate_limited:
            # Cooldown (1 publish / 4h / account) — row stays queued for retry
            log.info("approval_gate.publish_deferred", game_id=str(row["game_id"]))
            return
        if not result.success:
            log.error(
                "approval_gate.publish_failed",
                game_id=str(row["game_id"]),
                error=result.error,
            )
            await self._log_publish_failure(row["concept_id"], result.error or "unknown")
            await self._reporter.alert(
                f"Publish failed for approved game **{row['game_title']}**: "
                f"{result.error}. Logged to build_failures; fix the `{row['genre']}` "
                f"account, then re-run the build to retry."
            )
            await self._mark_processed(row["game_id"])
            return

        await self._mark_processed(row["game_id"])
        try:
            await marketer.start_ab_test(
                result.game_id, pathlib.Path(row["build_dir"])
            )
        except Exception as exc:
            log.warning("approval_gate.ab_test_failed", error=str(exc))
        # Spec 15: localized description published as an update right after
        # the English version (well within the 24h window)
        try:
            await self._publish_localized_update(row, result, marketer)
        except Exception as exc:
            log.warning("approval_gate.localization_failed", error=str(exc))
        # Cross-promotion (improvement 5): queue sibling games on this
        # account for a billboard refresh on the next update cycle
        try:
            from build.cross_promotion import on_game_published

            assert result.game_id
            await on_game_published(self._pool, result.game_id)
        except Exception as exc:
            log.warning("approval_gate.cross_promo_failed", error=str(exc))
        # Spec 18: archive the published build, prune to the newest
        # MAX_BUILDS_PER_GENRE per genre
        archived = archive_build(pathlib.Path(row["build_dir"]), row["genre"])
        # Marketing video (improvement 7): generate + publish the short-form
        # promo after every successful publish (gated by env, never fatal)
        try:
            from marketing.video_pipeline import VideoPipeline, marketing_enabled

            if marketing_enabled():
                assert result.game_id
                await VideoPipeline(self._pool, self._reporter, self._bot).run(
                    result.game_id,
                    archived or pathlib.Path(row["build_dir"]),
                )
        except Exception as exc:
            log.warning("approval_gate.marketing_video_failed", error=str(exc))
        log.info(
            "approval_gate.published",
            game_id=str(row["game_id"]),
            published_game_id=result.game_id,
        )
        # Only operator-decided rows count toward the 5-approval target
        if row["decided_at"] is not None and row["status"] == "approved":
            await self._count_approval()

    async def _publish_localized_update(
        self, row, result: PublishResult, marketer: InRobloxMarketer
    ) -> None:
        """Spec 15: when the source trend originates from a non-English
        market (ES/PT/DE/FR/PH), translate the description via DeepSeek V3
        and push it as a metadata update. The English version always goes
        live first; metadata only — no in-game text translation."""
        from build.concept_generator import LOCALIZATION_LANGUAGES

        async with self._pool.acquire() as conn:
            seed_json = await conn.fetchval(
                "SELECT concept_json FROM concept_queue WHERE id = $1",
                row["concept_id"],
            )
        if seed_json is None:
            return
        seed = json.loads(seed_json) if isinstance(seed_json, str) else dict(seed_json)
        origin = str(seed.get("platform_origin_country") or "US").upper()
        language = LOCALIZATION_LANGUAGES.get(origin)
        if language is None or not row["description"]:
            return

        translated = await chat(
            DEEPSEEK_V3,
            [
                {
                    "role": "system",
                    "content": (
                        f"Translate this Roblox game description into {language}. "
                        "Keep the tone, emoji, and any game-specific names unchanged. "
                        "Max 1000 characters. Output the translated text only."
                    ),
                },
                {"role": "user", "content": row["description"]},
            ],
            temperature=0.3,
            max_tokens=600,
        )
        translated = translated.strip().strip('"')[:1000]
        if not translated:
            return
        assert result.universe_id is not None
        await marketer._push_description(row["genre"], result.universe_id, translated)
        log.info(
            "approval_gate.localized_description_published",
            game_id=str(row["game_id"]),
            language=language,
        )

    async def _mark_processed(self, game_id) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE pending_approvals SET processed_at = NOW() WHERE game_id = $1",
                game_id,
            )

    async def _count_approval(self) -> None:
        async with self._pool.acquire() as conn:
            active = await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = 'supervised_mode_active'"
            )
            if (active or "true") != "true":
                return
            count = int(
                await conn.fetchval(
                    "SELECT value FROM orchestrator_state WHERE key = 'supervised_mode_approvals'"
                )
                or 0
            ) + 1
            await conn.execute(
                """
                INSERT INTO orchestrator_state (key, value, updated_at)
                VALUES ('supervised_mode_approvals', $1, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                str(count),
            )
            if count >= APPROVALS_TO_AUTONOMY:
                await conn.execute(
                    """
                    UPDATE orchestrator_state SET value = 'false', updated_at = NOW()
                    WHERE key = 'supervised_mode_active'
                    """
                )
        if count >= APPROVALS_TO_AUTONOMY:
            await self._reporter.alert(
                f"Supervised mode disabled after {count} approved publishes — "
                f"system is now fully autonomous. Re-enable any time with "
                f"SUPERVISED_MODE=true."
            )
            log.info("approval_gate.autonomy_unlocked", approvals=count)
        else:
            log.info("approval_gate.approval_counted", approvals=count)
