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
import os
import pathlib
import uuid
from typing import TYPE_CHECKING

import asyncpg
import structlog

from monitor.discord_reporter import DiscordReporter

from .build_archive import archive_build, discard_build
from .marketer import InRobloxMarketer
from .open_cloud_publisher import OpenCloudPublisher, dry_run_enabled

if TYPE_CHECKING:
    from build.pipeline import BuildOutput
    from .discord_bot import ApprovalBot

log = structlog.get_logger()

APPROVALS_TO_AUTONOMY = 5


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
            if row["status"] == "skipped":
                await self._finalize_skip(row)
            else:
                await self._publish_approved(row, publisher, marketer)

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
            await self._reporter.alert(
                f"Publish failed for approved game **{row['game_title']}**: "
                f"{result.error}. Row marked processed — re-approve manually to retry."
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
        # Spec 18: archive the published build, prune to the newest
        # MAX_BUILDS_PER_GENRE per genre
        archive_build(pathlib.Path(row["build_dir"]), row["genre"])
        log.info(
            "approval_gate.published",
            game_id=str(row["game_id"]),
            published_game_id=result.game_id,
        )
        # Only operator-decided rows count toward the 5-approval target
        if row["decided_at"] is not None and row["status"] == "approved":
            await self._count_approval()

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
