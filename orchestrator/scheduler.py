"""
Orchestrator — APScheduler-based coordinator.
Runs the full intelligence → build → publish → monitor cycle every 6 hours.
Handles crash recovery, supervised mode, and Discord alerts.
"""
import asyncio
import os
import traceback
from datetime import datetime, timezone

import asyncpg
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from db import get_pool, close_pool, run_migrations
from intelligence.meta_scout import MetaScout
from intelligence.trend_predictor import TrendPredictor
from intelligence.mechanic_mapper import MechanicMapper
from intelligence.gap_analyzer import GapAnalyzer
from intelligence.scoring_engine import ScoringEngine, ViabilityGate, FeedbackLoop

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

    async def start(self) -> None:
        """Initialize DB, wire modules, schedule jobs, start scheduler."""
        self._pool = await get_pool()
        await run_migrations()

        self._meta_scout     = MetaScout()
        self._trend_pred     = TrendPredictor()
        self._mech_mapper    = MechanicMapper()
        self._gap_analyzer   = GapAnalyzer()
        self._scoring_eng    = ScoringEngine()
        self._viability_gate = ViabilityGate(self._pool)
        self._feedback_loop  = FeedbackLoop()

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

        self._scheduler.start()
        log.info("orchestrator.started", cycle_hours=CYCLE_INTERVAL_HOURS)

        # Run first intelligence cycle immediately on startup
        await self._run_intelligence_cycle()

    async def stop(self) -> None:
        self._scheduler.shutdown(wait=False)
        await close_pool()
        log.info("orchestrator.stopped")

    # ─────────────────────────────────────────────────────────
    # Intelligence cycle
    # ─────────────────────────────────────────────────────────

    async def _run_intelligence_cycle(self) -> None:
        log.info("cycle.intelligence.start")
        try:
            await self._intelligence_cycle_inner()
        except Exception:
            log.error("cycle.intelligence.crashed", traceback=traceback.format_exc())
            await self._discord_alert(
                "Intelligence cycle crashed — check logs. System will retry on next scheduled run."
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

        # Step 5: Score
        scored = self._scoring_eng.score(
            meta_result, trend_result, mapped, gap_results, signal_weights
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

        if gate_result.fallback_triggered:
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

        # Step 7: Hand off to build pipeline (Phase 2 — wired later)
        for concept in gate_result.passing:
            await self._dispatch_to_build(concept)

    async def _dispatch_to_build(self, concept) -> None:
        """
        Hand off a passing concept to the Build Pipeline (L2).
        Phase 2 will wire in ConceptGenerator → LuauAgent → ... here.
        """
        log.info(
            "cycle.build_dispatched",
            concept_id=concept.concept_id,
            mechanic=concept.mechanic_tag,
            score=concept.opportunity_score,
        )
        # TODO: wire build pipeline here in Phase 2

    # ─────────────────────────────────────────────────────────
    # Monitor cycle
    # ─────────────────────────────────────────────────────────

    async def _run_monitor_cycle(self) -> None:
        """
        Polls Roblox Analytics for live game metrics and runs FeedbackLoop.
        Phase 3 will wire in PerformanceMonitor here.
        """
        # TODO: wire PerformanceMonitor in Phase 3
        if self._feedback_loop and self._pool:
            try:
                await self._feedback_loop.adjust_weights(self._pool)
            except Exception:
                log.error("cycle.monitor.feedback_failed", traceback=traceback.format_exc())

    # ─────────────────────────────────────────────────────────
    # Weekly digest
    # ─────────────────────────────────────────────────────────

    async def _run_weekly_digest(self) -> None:
        """
        Sends weekly performance summary via Discord.
        Phase 3 will wire in DiscordReporter here.
        """
        # TODO: wire DiscordReporter in Phase 3
        log.info("cycle.weekly_digest.stub_called")

    # ─────────────────────────────────────────────────────────
    # Alerts
    # ─────────────────────────────────────────────────────────

    async def _discord_alert(self, message: str) -> None:
        """Fire-and-forget Discord webhook alert."""
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not webhook_url:
            log.warning("orchestrator.discord_not_configured", message=message)
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    webhook_url,
                    json={"content": f"[RobloxStudio] {message}"},
                )
        except Exception as exc:
            log.error("orchestrator.discord_failed", error=str(exc))


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
