"""
Orchestrator — APScheduler-based coordinator.
Runs the full intelligence → build → publish → monitor cycle every 6 hours.
Handles crash recovery, supervised mode, and Discord alerts.
"""
import asyncio
import json
import os
import pathlib
import traceback
import uuid
from datetime import datetime, timezone

import asyncpg
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from db import get_pool, close_pool, run_migrations
from intelligence.llm_client import set_spend_pool
from intelligence.meta_scout import MetaScout
from intelligence.trend_predictor import TrendPredictor
from intelligence.mechanic_mapper import MechanicMapper
from intelligence.gap_analyzer import GapAnalyzer
from intelligence.scoring_engine import ScoringEngine, ViabilityGate, FeedbackLoop
from monitor import BreakoutDetector, DiscordReporter, PerformanceMonitor, UpdateCadence
from monitor.failure_memory import FailureMemory
from publish.approval_gate import ApprovalGate
from publish.discord_bot import ApprovalBot, create_bot
from publish.marketer import InRobloxMarketer
from publish.open_cloud_publisher import OpenCloudPublisher

log = structlog.get_logger()

CYCLE_INTERVAL_HOURS   = 6
MONITOR_INTERVAL_HOURS = 1


class Orchestrator:
    """
    Top-level coordinator.
    Call .start() to begin the scheduler loop; .stop() to shut down cleanly.
    """

    def __init__(self) -> None:
        self._scheduler   = AsyncIOScheduler()
        self._pool: asyncpg.Pool | None = None

        # Phase modules — wired in .start() once pool is available
        self._meta_scout:    MetaScout | None    = None
        self._trend_pred:    TrendPredictor | None = None
        self._mech_mapper:   MechanicMapper | None = None
        self._gap_analyzer:  GapAnalyzer | None  = None
        self._scoring_eng:   ScoringEngine | None = None
        self._viability_gate: ViabilityGate | None = None
        self._feedback_loop:  FeedbackLoop | None  = None
        self._reporter:      DiscordReporter | None = None
        self._perf_monitor:  PerformanceMonitor | None = None
        self._breakout:      BreakoutDetector | None = None
        self._marketer:      InRobloxMarketer | None = None
        self._publisher:     OpenCloudPublisher | None = None
        self._approval_gate: ApprovalGate | None = None
        self._failure_memory: FailureMemory | None = None
        self._bot:           ApprovalBot | None = None
        self._bot_task:      asyncio.Task | None = None

    async def init(self) -> None:
        """Initialize DB pool and wire all phase modules (no scheduling).
        Used by start() and by scripts/dry_run.py for one-shot runs."""
        self._pool = await get_pool()
        await run_migrations()
        set_spend_pool(self._pool)

        self._meta_scout     = MetaScout()
        self._trend_pred     = TrendPredictor()
        self._mech_mapper    = MechanicMapper()
        self._gap_analyzer   = GapAnalyzer()
        self._scoring_eng    = ScoringEngine()
        self._viability_gate = ViabilityGate(self._pool)
        self._feedback_loop  = FeedbackLoop()
        self._reporter       = DiscordReporter(self._pool)
        self._perf_monitor   = PerformanceMonitor(self._pool, self._reporter)
        self._breakout       = BreakoutDetector(self._pool, self._reporter)
        self._marketer       = InRobloxMarketer(self._pool)
        self._publisher      = OpenCloudPublisher(self._pool)
        self._failure_memory = FailureMemory(self._pool)
        self._bot            = create_bot(self._pool)
        self._approval_gate  = ApprovalGate(self._pool, self._reporter, self._bot)

        # Give the bot the references its ops commands need (!force/!status →
        # orchestrator, !retry → approval gate + publisher + marketer)
        if self._bot is not None:
            self._bot.attach(
                orchestrator=self,
                approval_gate=self._approval_gate,
                publisher=self._publisher,
                marketer=self._marketer,
            )

        # Discord bot runs alongside the scheduler (DM approvals, spec 12)
        token = os.environ.get("DISCORD_BOT_TOKEN", "")
        if self._bot is not None and token:
            self._bot_task = asyncio.create_task(self._bot.start(token))
            self._bot_task.add_done_callback(self._on_bot_exit)

    def _on_bot_exit(self, task: asyncio.Task) -> None:
        """A dead bot means approvals stall silently — make it loud."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            log.error("discord_bot.crashed", error=repr(exc))
            asyncio.get_running_loop().create_task(
                self._discord_alert(
                    f"Approval bot crashed ({exc!r}) — supervised publishes "
                    f"will queue until the service restarts."
                )
            )

    async def start(self) -> None:
        """Initialize, schedule all jobs, start the scheduler loop."""
        await self.init()

        # Intelligence cycle — every 6 hours
        self._scheduler.add_job(
            self._run_intelligence_cycle,
            trigger=IntervalTrigger(hours=CYCLE_INTERVAL_HOURS),
            id="intelligence_cycle",
            name="Intelligence Cycle",
            replace_existing=True,
            misfire_grace_time=600,
            coalesce=True,
        )

        # Performance monitor — every hour (wired in Phase 3, no-op until then)
        self._scheduler.add_job(
            self._run_monitor_cycle,
            trigger=IntervalTrigger(hours=MONITOR_INTERVAL_HOURS),
            id="monitor_cycle",
            name="Performance Monitor",
            replace_existing=True,
            misfire_grace_time=120,
            coalesce=True,
        )

        # Weekly Discord digest — every Monday at 09:00
        self._scheduler.add_job(
            self._run_weekly_digest,
            trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
            id="weekly_digest",
            name="Weekly Discord Digest",
            replace_existing=True,
        )

        # Approval queue processor — publishes approved builds, finalizes
        # skips, retries rate-limited publishes (spec Section 12)
        self._scheduler.add_job(
            self._run_approval_processing,
            trigger=IntervalTrigger(minutes=5),
            id="approval_processing",
            name="Approval Queue Processor",
            replace_existing=True,
            misfire_grace_time=60,
            coalesce=True,
        )

        # Live-game update cadence — daily at 03:00 (spec 14: breakout
        # daily, normal weekly, underperforming monthly)
        self._scheduler.add_job(
            self._run_update_cycle,
            trigger=CronTrigger(hour=3, minute=0),
            id="update_cycle",
            name="Live Game Update Cycle",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

        # 48h description refresh (improvement 4) — checked every 6 hours
        # so each game refreshes as soon as its 48h window lapses
        self._scheduler.add_job(
            self._run_description_refresh,
            trigger=IntervalTrigger(hours=6),
            id="description_refresh_48h",
            name="48h SEO Description Refresh",
            replace_existing=True,
            misfire_grace_time=1800,
            coalesce=True,
        )

        # Name blacklist refresh — every 24h (get_blacklist() also lazily
        # refreshes on read, this keeps the file warm between builds)
        self._scheduler.add_job(
            self._run_blacklist_refresh,
            trigger=IntervalTrigger(hours=24),
            id="name_blacklist_refresh",
            name="Game Name Blacklist Refresh",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

        # LiveOps weekly cycle (improvement 8) — Mondays 10:00, independent
        # of the 6-hour generation cycle; gated by ENABLE_LIVEOPS
        self._scheduler.add_job(
            self._run_liveops_cycle,
            trigger=CronTrigger(day_of_week="mon", hour=10, minute=0),
            id="liveops_weekly",
            name="Weekly LiveOps Cycle",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

        # Seasonal reskin revert check — daily 06:00
        self._scheduler.add_job(
            self._run_seasonal_reverts,
            trigger=CronTrigger(hour=6, minute=0),
            id="seasonal_reverts",
            name="Seasonal Reskin Revert Check",
            replace_existing=True,
            misfire_grace_time=3600,
            coalesce=True,
        )

        # Low-CTR thumbnail refresh — monthly on the 1st (spec 5.2 phase 2)
        self._scheduler.add_job(
            self._run_thumbnail_refresh,
            trigger=CronTrigger(day=1, hour=4, minute=0),
            id="thumbnail_refresh",
            name="Monthly Thumbnail CTR Refresh",
            replace_existing=True,
        )

        self._scheduler.start()
        log.info("orchestrator.started", cycle_hours=CYCLE_INTERVAL_HOURS)

        # Run first intelligence cycle immediately on startup
        await self._run_intelligence_cycle()

    async def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        if self._bot is not None and not self._bot.is_closed():
            await self._bot.close()
        if self._bot_task is not None:
            self._bot_task.cancel()
        await close_pool()
        log.info("orchestrator.stopped")

    async def run_one_cycle(self, force: bool = False) -> None:
        """Single end-to-end pass: intelligence → build → approval/publish
        → monitor. Used by scripts/dry_run.py and the !force command; call
        init() first. force=True bypasses the !pause flag."""
        await self._run_intelligence_cycle(force=force)
        await self._run_approval_processing()
        await self._run_monitor_cycle()

    async def _is_paused(self) -> bool:
        """True when an operator has issued !pause (orchestrator_state)."""
        return (await self._get_state("paused")) == "true"

    # ─────────────────────────────────────────────────────────
    # Intelligence cycle
    # ─────────────────────────────────────────────────────────

    async def _run_intelligence_cycle(self, force: bool = False) -> None:
        # FIX 7: honor the !pause flag. The build pipeline runs inside this
        # cycle (via _dispatch_to_build), so this single guard pauses both
        # scouting and building. force=True (the !force command) overrides.
        if not force and await self._is_paused():
            log.info("cycle.intelligence.paused_skip")
            return
        log.info("cycle.intelligence.start")
        try:
            await self._intelligence_cycle_inner()
        except Exception:
            log.error("cycle.intelligence.crashed", traceback=traceback.format_exc())
            await self._discord_alert(
                "Intelligence cycle crashed — check logs. System will retry on next scheduled run."
            )
        finally:
            # Stamp completion for the !status command
            await self._set_state(
                "last_cycle_completed", datetime.now(timezone.utc).isoformat()
            )

    async def _intelligence_cycle_inner(self) -> None:
        assert self._pool and self._meta_scout and self._trend_pred
        assert self._mech_mapper and self._gap_analyzer
        assert self._scoring_eng and self._viability_gate and self._feedback_loop

        # Step 1: Gather raw signals (parallel)
        meta_result, trend_result = await asyncio.gather(
            self._meta_scout.run(),
            self._trend_pred.run(),
        )
        log.info(
            "cycle.signals_gathered",
            meta=len(meta_result.signals),
            trends=len(trend_result.pre_arrival_trends),
        )

        # Persist trending keywords for SEO descriptions (spec 5.2) — used
        # by this cycle's builds and the daily update cycle
        keywords = self._derive_keywords(meta_result, trend_result)
        if keywords:
            await self._set_state("latest_meta_keywords", json.dumps(keywords))

        # Step 2: Map to mechanics
        mapped = await self._mech_mapper.map_signals(
            meta_result.signals, trend_result.pre_arrival_trends
        )
        log.info("cycle.mechanics_mapped", count=len(mapped))

        if not mapped:
            log.warning("cycle.no_mapped_signals")
            return

        # Step 3: Gap analysis
        gap_results = await self._gap_analyzer.analyze(mapped)
        log.info("cycle.gap_analyzed", count=len(gap_results))

        # Step 4: Load signal weights (FeedbackLoop adjustments)
        signal_weights = await self._feedback_loop.get_weights(self._pool)

        # Step 5: Score (hard-excluding FailureMemory-suppressed combos)
        assert self._failure_memory
        suppressed = await self._failure_memory.get_suppressed()
        scored = self._scoring_eng.score(
            meta_result, trend_result, mapped, gap_results, signal_weights,
            suppressed_combos=suppressed,
        )
        log.info("cycle.scored", count=len(scored), top_score=scored[0].opportunity_score if scored else 0)

        # Step 6: Viability gate
        consecutive_rejects = await self._viability_gate.get_consecutive_rejects(self._pool)
        gate_result = await self._viability_gate.filter(scored, consecutive_rejects)

        # Update consecutive reject counter
        if gate_result.passing:
            await self._viability_gate.update_consecutive_rejects(self._pool, 0)
        else:
            await self._viability_gate.update_consecutive_rejects(
                self._pool, consecutive_rejects + 1
            )

        if gate_result.fallback_triggered and scored:
            await self._discord_alert(
                f"Viability gate in fallback mode — threshold lowered to "
                f"{gate_result.threshold_used}. "
                f"Top score was {scored[0].opportunity_score:.2f}."
            )

        log.info(
            "cycle.viability_gate",
            passing=len(gate_result.passing),
            rejected=len(gate_result.rejected),
            threshold=gate_result.threshold_used,
        )

        # Step 7: Hand off to build pipeline — one concept's crash must not
        # take down the rest of this cycle's builds
        for concept in gate_result.passing:
            try:
                await self._dispatch_to_build(concept)
            except Exception:
                log.error(
                    "cycle.build_dispatch_crashed",
                    concept_id=concept.concept_id,
                    traceback=traceback.format_exc(),
                )

    async def _dispatch_to_build(self, concept) -> None:
        """Hand off a passing concept to the Build Pipeline (L2)."""
        log.info(
            "cycle.build_dispatched",
            concept_id=concept.concept_id,
            mechanic=concept.mechanic_tag,
            score=concept.opportunity_score,
        )
        from build.pipeline import BuildPipeline

        assert self._pool
        pipeline = BuildPipeline(self._pool)
        output = await pipeline.run(
            concept.concept_id, meta_keywords=await self._get_meta_keywords()
        )
        if output is None:
            await self._discord_alert(
                f"Build failed for concept {concept.concept_id} "
                f"({concept.mechanic_tag}) after all retries — see build_failures table."
            )
            return
        log.info(
            "cycle.build_complete",
            game_id=output.game_id,
            title=output.concept.get("game_title"),
            rbxl=str(output.rbxl_path),
        )

        # Hand off to the approval gate (spec Section 12): supervised mode
        # pauses for a Discord DM decision; autonomous mode pre-approves.
        # Pass the genre ACCOUNT (idle/horror/sim) — the publisher resolves
        # ROBLOX_API_KEY_{GENRE} from it, not the raw trend genre string.
        assert self._approval_gate
        genre_account = output.concept.get("target_genre_account") or "sim"
        await self._approval_gate.submit(output, genre_account)
        # Process immediately so autonomous publishes don't wait for the
        # 5-minute job; pending (supervised) rows are untouched.
        await self._run_approval_processing()

    async def _run_approval_processing(self) -> None:
        assert self._approval_gate and self._publisher and self._marketer
        try:
            await self._approval_gate.process_decisions(self._publisher, self._marketer)
        except Exception:
            log.error("cycle.approval_processing_failed", traceback=traceback.format_exc())

    # ─────────────────────────────────────────────────────────
    # Monitor cycle
    # ─────────────────────────────────────────────────────────

    async def _run_monitor_cycle(self) -> None:
        """
        Hourly: poll metrics, detect breakouts/moderation, settle A/B tests,
        adjust signal weights, run big-decision threshold checks.
        Each step is isolated so one failure doesn't kill the cycle.
        """
        assert self._pool and self._perf_monitor and self._breakout
        assert self._marketer and self._feedback_loop and self._reporter

        try:
            await self._perf_monitor.run()
            await self._perf_monitor.check_account_health()
        except Exception:
            log.error("cycle.monitor.metrics_failed", traceback=traceback.format_exc())

        try:
            new_breakouts = await self._breakout.run()
            if new_breakouts:
                await self._regenerate_thumbnails(new_breakouts)
        except Exception:
            log.error("cycle.monitor.breakout_failed", traceback=traceback.format_exc())

        try:
            await self._marketer.settle_ab_tests()
        except Exception:
            log.error("cycle.monitor.ab_settle_failed", traceback=traceback.format_exc())

        try:
            await self._feedback_loop.adjust_weights(self._pool)
        except Exception:
            log.error("cycle.monitor.feedback_failed", traceback=traceback.format_exc())

        # FailureMemory (improvement 6): record games dead after 30 days,
        # alert when a mechanic+genre combo hits permanent suppression
        try:
            assert self._failure_memory
            newly_suppressed = await self._failure_memory.record_failures()
            for mechanic, genre in newly_suppressed:
                await self._discord_alert(
                    f"⛔ Combo **{mechanic} / {genre}** permanently suppressed "
                    f"after 3 failed games (<5 CCU after 30 days). The scoring "
                    f"engine will skip it. Re-enable with `!unsuppress "
                    f"{mechanic} {genre}`."
                )
        except Exception:
            log.error("cycle.monitor.failure_memory_failed", traceback=traceback.format_exc())

        try:
            await self._reporter.run_threshold_checks()
        except Exception:
            log.error("cycle.monitor.thresholds_failed", traceback=traceback.format_exc())

    async def _regenerate_thumbnails(self, game_ids: list[str]) -> None:
        """Higher-effort FLUX thumbnail regen — used for new breakouts
        (spec 6.2 action 2) and the monthly low-CTR refresh (spec 5.2)."""
        from build.asset_generator import AssetGenerator
        from publish.open_cloud_publisher import upload_thumbnail

        assert self._pool
        assets = AssetGenerator()
        builds_root = pathlib.Path(os.environ.get("BUILDS_ROOT", "/builds"))
        for game_id in game_ids:
            try:
                async with self._pool.acquire() as conn:
                    row = await conn.fetchrow(
                        """
                        SELECT pg.genre_account, cq.concept_json
                        FROM published_games pg
                        JOIN concept_queue cq ON cq.id = pg.concept_id
                        WHERE pg.id = $1
                        """,
                        uuid.UUID(game_id),
                    )
                if row is None:
                    continue
                concept = (
                    json.loads(row["concept_json"])
                    if isinstance(row["concept_json"], str)
                    else dict(row["concept_json"])
                )
                work_dir = builds_root / "active" / f"breakout_{game_id}"
                work_dir.mkdir(parents=True, exist_ok=True)
                generated = await assets.generate_all(concept, work_dir, alt_prompt=True)
                await upload_thumbnail(row["genre_account"], generated["thumbnail"])
                log.info("cycle.monitor.breakout_thumbnail_regenerated", game_id=game_id)
            except Exception as exc:
                log.warning(
                    "cycle.monitor.breakout_thumbnail_failed",
                    game_id=game_id,
                    error=str(exc),
                )

    # ─────────────────────────────────────────────────────────
    # Live-game update cycle (spec 14)
    # ─────────────────────────────────────────────────────────

    async def _run_update_cycle(self) -> None:
        """Daily: refresh games due per their cadence (breakout 1d, live 7d,
        flagged 30d). All due games get a fresh SEO description; breakout
        games additionally get a content drop (new place version)."""
        assert self._pool and self._marketer
        try:
            due = await UpdateCadence.games_due_for_update(self._pool)
        except Exception:
            log.error("cycle.update.due_check_failed", traceback=traceback.format_exc())
            return
        if not due:
            return
        keywords = await self._get_meta_keywords()
        for game in due:
            game_id = str(game["id"])
            try:
                await self._marketer.refresh_for_games([game_id], keywords)
                # Breakouts get their daily content drop; any game with a
                # pending cross-promo marker gets a rebuilt place version
                # so new sibling billboards actually ship (improvement 5)
                cross_promo_pending = (
                    await self._get_state(f"cross_promo_refresh:{game_id}")
                ) == "pending"
                if game["status"] == "breakout" or cross_promo_pending:
                    await self._content_drop(game)
                    if cross_promo_pending:
                        await self._clear_state(f"cross_promo_refresh:{game_id}")
                await UpdateCadence.mark_updated(self._pool, game_id)
            except Exception:
                log.error(
                    "cycle.update.game_failed",
                    game=game["game_title"],
                    traceback=traceback.format_exc(),
                )
        log.info("cycle.update.complete", due=len(due))

    async def _content_drop(self, game) -> None:
        """Spec 14: regenerate the game's source from its stored concept
        (fresh theme/balance pass + current sibling billboards) and push a
        new place version. Used for breakout daily drops and cross-promo
        billboard refreshes.
        TODO: richer content drops need update-aware LuauAgent prompting
        with the live game's source as context."""
        from build.auto_validator import AutoValidator
        from build.cross_promotion import get_siblings
        from build.luau_agent import LuauAgent
        from build.rojo_builder import RojoBuilder

        assert self._pool and self._publisher
        async with self._pool.acquire() as conn:
            concept_json = await conn.fetchval(
                """
                SELECT cq.concept_json FROM published_games pg
                JOIN concept_queue cq ON cq.id = pg.concept_id
                WHERE pg.id = $1
                """,
                game["id"],
            )
        if concept_json is None:
            return
        concept = (
            json.loads(concept_json) if isinstance(concept_json, str) else dict(concept_json)
        )
        concept["cross_promo_siblings"] = await get_siblings(
            self._pool, game["genre_account"], exclude_game_id=str(game["id"])
        )
        build_dir = await LuauAgent().generate(concept, f"update_{game['id']}")
        rojo_result = await RojoBuilder().build(build_dir)
        validation = await AutoValidator().validate(build_dir, rojo_result)
        if not validation.passed or rojo_result.rbxl_path is None:
            log.warning(
                "cycle.update.content_drop_invalid",
                game=game["game_title"],
                failures=validation.failures[:5],
            )
            return
        await self._publisher.publish_update(
            game["genre_account"], game["place_id"], rojo_result.rbxl_path
        )

    # ─────────────────────────────────────────────────────────
    # LiveOps (improvement 8)
    # ─────────────────────────────────────────────────────────

    async def _run_liveops_cycle(self) -> None:
        assert self._pool and self._publisher and self._reporter
        try:
            from liveops.liveops_pipeline import LiveOpsPipeline

            pipeline = LiveOpsPipeline(self._pool, self._publisher, self._reporter)
            await pipeline.run_weekly_cycle(await self._get_meta_keywords())
        except Exception:
            log.error("cycle.liveops_failed", traceback=traceback.format_exc())
            await self._discord_alert(
                "Weekly LiveOps cycle crashed — check logs. Will retry next Monday."
            )

    async def _run_seasonal_reverts(self) -> None:
        assert self._pool
        try:
            from liveops.seasonal_reskin import revert_due_overrides

            reverted = await revert_due_overrides(self._pool)
            for title in reverted:
                await self._discord_alert(
                    f"🔄 Seasonal reskin reverted: **{title}** — original title, "
                    f"description, and thumbnail restored."
                )
        except Exception:
            log.error("cycle.seasonal_revert_failed", traceback=traceback.format_exc())

    # ─────────────────────────────────────────────────────────
    # 48h description refresh (improvement 4)
    # ─────────────────────────────────────────────────────────

    async def _run_description_refresh(self) -> None:
        """Refresh the SEO description of every live game whose last
        refresh is older than 48h, using the latest MetaScout keywords."""
        assert self._marketer
        try:
            keywords = await self._get_meta_keywords()
            refreshed = await self._marketer.refresh_due_descriptions(keywords)
            if refreshed:
                log.info("cycle.description_refresh.complete", refreshed=refreshed)
        except Exception:
            log.error(
                "cycle.description_refresh_failed", traceback=traceback.format_exc()
            )

    # ─────────────────────────────────────────────────────────
    # Name blacklist refresh (24h)
    # ─────────────────────────────────────────────────────────

    async def _run_blacklist_refresh(self) -> None:
        from intelligence.name_blacklist import refresh_blacklist

        try:
            await refresh_blacklist(force=True)
        except Exception:
            log.error("cycle.blacklist_refresh_failed", traceback=traceback.format_exc())

    # ─────────────────────────────────────────────────────────
    # Monthly thumbnail CTR refresh (spec 5.2 phase 2)
    # ─────────────────────────────────────────────────────────

    async def _run_thumbnail_refresh(self) -> None:
        assert self._marketer
        try:
            low_ctr_ids = await self._marketer.regenerate_low_ctr_thumbnails()
            if low_ctr_ids:
                await self._regenerate_thumbnails(low_ctr_ids)
        except Exception:
            log.error("cycle.thumbnail_refresh_failed", traceback=traceback.format_exc())

    # ─────────────────────────────────────────────────────────
    # Weekly digest
    # ─────────────────────────────────────────────────────────

    async def _run_weekly_digest(self) -> None:
        """Sends the weekly performance summary via Discord (spec 6.4)."""
        assert self._reporter
        try:
            await self._reporter.weekly_digest()
        except Exception:
            log.error("cycle.weekly_digest.failed", traceback=traceback.format_exc())

    # ─────────────────────────────────────────────────────────
    # Shared state helpers
    # ─────────────────────────────────────────────────────────

    @staticmethod
    def _derive_keywords(meta_result, trend_result) -> list[str]:
        """Trending keywords for SEO writing: signal genres + trend names,
        deduped in order, capped at 15."""
        seen: dict[str, None] = {}
        for s in meta_result.signals:
            if s.genre:
                seen.setdefault(s.genre.strip(), None)
        for t in trend_result.pre_arrival_trends:
            if t.trend_name:
                seen.setdefault(t.trend_name.strip(), None)
        return list(seen)[:15]

    async def _get_meta_keywords(self) -> list[str]:
        assert self._pool
        async with self._pool.acquire() as conn:
            raw = await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = 'latest_meta_keywords'"
            )
        try:
            return json.loads(raw) if raw else []
        except json.JSONDecodeError:
            return []

    async def _get_state(self, key: str) -> str | None:
        assert self._pool
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = $1", key
            )

    async def _clear_state(self, key: str) -> None:
        assert self._pool
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM orchestrator_state WHERE key = $1", key
            )

    async def _set_state(self, key: str, value: str) -> None:
        assert self._pool
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

    # ─────────────────────────────────────────────────────────
    # Alerts
    # ─────────────────────────────────────────────────────────

    async def _discord_alert(self, message: str) -> None:
        """Fire-and-forget Discord webhook alert."""
        if self._reporter:
            await self._reporter.alert(message)
        else:
            log.warning("orchestrator.alert_before_start", message=message)


async def main() -> None:
    """Entry point — runs the orchestrator until interrupted."""
    import dotenv
    dotenv.load_dotenv()

    orchestrator = Orchestrator()
    try:
        await orchestrator.start()
        # Keep running until Ctrl-C
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        log.info("orchestrator.shutdown_requested")
    finally:
        await orchestrator.stop()


if __name__ == "__main__":
    asyncio.run(main())
