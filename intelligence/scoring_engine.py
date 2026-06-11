"""
ScoringEngine + ViabilityGate — combines MetaScout, TrendPredictor, and
GapAnalyzer scores into a final opportunity score. Writes passing concepts
to the concept_queue table and manages viability fallback (Section 20).
"""
import os
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import asyncpg
import structlog

from .llm_client import DEEPSEEK_V3, chat_json
from .meta_scout import Signal, MetaScoutResult
from .trend_predictor import PreArrivalTrend, TrendPredictorResult
from .mechanic_mapper import MappedSignal
from .gap_analyzer import GapAnalysisResult
from .seasonal_context import SEASONAL_BOOST, get_seasonal_context

log = structlog.get_logger()

# Scoring weights — spec Section 3.5
WEIGHT_SIGNAL_STRENGTH   = 0.30
WEIGHT_VELOCITY          = 0.25
WEIGHT_SUSTAINED_CCU     = 0.25
WEIGHT_DIFFERENTIATION   = 0.20

DEFAULT_VIABILITY_THRESHOLD = float(os.environ.get("VIABILITY_THRESHOLD", "0.65"))
FALLBACK_THRESHOLD          = 0.50
MAX_CONSECUTIVE_REJECTS     = 3

# Weight adjustment caps — spec Section 6.3
WEIGHT_CAP_DELTA = 0.40  # ±40% from baseline


@dataclass
class ScoredConcept:
    concept_id: str
    mechanic_tag: str
    genre: str
    opportunity_score: float
    signal_strength: float
    velocity_score: float
    sustained_ccu: bool
    differentiation_score: float  # 1 - similarity_score
    gap_result: GapAnalysisResult
    concept_json: dict = field(default_factory=dict)


@dataclass
class ViabilityGateResult:
    passing: list[ScoredConcept] = field(default_factory=list)
    rejected: list[ScoredConcept] = field(default_factory=list)
    threshold_used: float = DEFAULT_VIABILITY_THRESHOLD
    fallback_triggered: bool = False


class ScoringEngine:
    """Combines all intelligence scores into a final opportunity score."""

    def score(
        self,
        meta_result: MetaScoutResult,
        trend_result: TrendPredictorResult,
        mapped_signals: list[MappedSignal],
        gap_results: list[GapAnalysisResult],
        signal_weights: dict[str, float],
        suppressed_combos: set[tuple[str, str]] | None = None,
    ) -> list[ScoredConcept]:
        """
        For each gap result, find best matching meta/trend signal and
        compute weighted opportunity score. Combos in `suppressed_combos`
        (FailureMemory, improvement 6) are hard-excluded regardless of
        signal strength.
        """
        season = get_seasonal_context()
        suppressed = suppressed_combos or set()

        # Index meta signals and trend signals by mechanic_tag
        meta_by_tag: dict[str, list[Signal]] = {}
        for s in meta_result.signals:
            meta_by_tag.setdefault(s.mechanic_tag, []).append(s)

        trend_by_tag: dict[str, list[PreArrivalTrend]] = {}
        for t in trend_result.pre_arrival_trends:
            trend_by_tag.setdefault(t.suggested_mechanic, []).append(t)

        scored: list[ScoredConcept] = []
        for gap in gap_results:
            tag = gap.mechanic_tag

            # FailureMemory hard-exclusion — this combo produced 3+ dead
            # games; no signal strength overrides it
            if (tag, gap.raw_genre) in suppressed:
                log.info(
                    "scoring_engine.combo_suppressed",
                    mechanic=tag,
                    genre=gap.raw_genre,
                )
                continue

            tag_weight = signal_weights.get(tag, 1.0)

            # Best matching meta signal for this mechanic
            meta_signals_for_tag = meta_by_tag.get(tag, [])
            if meta_signals_for_tag:
                best_meta = max(meta_signals_for_tag, key=lambda s: s.signal_strength)
                signal_strength = best_meta.signal_strength
                sustained_ccu   = best_meta.sustained_ccu_indicator
            else:
                signal_strength = 0.3  # weak default if no match
                sustained_ccu   = False

            # Best matching trend for this mechanic
            trend_signals_for_tag = trend_by_tag.get(tag, [])
            if trend_signals_for_tag:
                best_trend = max(trend_signals_for_tag, key=lambda t: t.velocity_score)
                velocity_score = best_trend.velocity_score
            else:
                velocity_score = 0.2

            differentiation_score = max(0.0, 1.0 - gap.similarity_score)

            raw_score = (
                WEIGHT_SIGNAL_STRENGTH * signal_strength
                + WEIGHT_VELOCITY       * velocity_score
                + WEIGHT_SUSTAINED_CCU  * (1.0 if sustained_ccu else 0.0)
                + WEIGHT_DIFFERENTIATION * differentiation_score
            )

            # Apply per-mechanic weight multiplier (FeedbackLoop adjustments)
            opportunity_score = raw_score * tag_weight

            # Seasonal boost (15%) for concepts matching the active season
            if season.matches_concept(tag, gap.raw_genre, gap.closest_existing_game):
                opportunity_score *= SEASONAL_BOOST
                log.debug(
                    "scoring_engine.seasonal_boost",
                    mechanic=tag,
                    season=season.name,
                )

            opportunity_score = min(1.0, opportunity_score)

            scored.append(
                ScoredConcept(
                    concept_id=gap.concept_id,
                    mechanic_tag=tag,
                    genre=gap.raw_genre,
                    opportunity_score=opportunity_score,
                    signal_strength=signal_strength,
                    velocity_score=velocity_score,
                    sustained_ccu=sustained_ccu,
                    differentiation_score=differentiation_score,
                    gap_result=gap,
                )
            )

        scored.sort(key=lambda c: c.opportunity_score, reverse=True)
        log.info("scoring_engine.complete", count=len(scored))
        return scored


class ViabilityGate:
    """Filters scored concepts and writes passing ones to Postgres."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def filter(
        self,
        scored: list[ScoredConcept],
        consecutive_rejects: int,
    ) -> ViabilityGateResult:
        threshold = DEFAULT_VIABILITY_THRESHOLD
        fallback_triggered = False

        if consecutive_rejects >= MAX_CONSECUTIVE_REJECTS:
            threshold = FALLBACK_THRESHOLD
            fallback_triggered = True
            log.warning(
                "viability_gate.fallback_mode",
                consecutive_rejects=consecutive_rejects,
                new_threshold=threshold,
            )

        passing = [c for c in scored if c.opportunity_score >= threshold]
        rejected = [c for c in scored if c.opportunity_score < threshold]

        if not passing and scored:
            # Force-pass the best concept regardless of score
            passing = [scored[0]]
            rejected = scored[1:]
            log.warning(
                "viability_gate.forced_best_concept",
                score=scored[0].opportunity_score,
            )

        for concept in passing:
            await self._write_to_db(concept)

        log.info(
            "viability_gate.complete",
            passing=len(passing),
            rejected=len(rejected),
            threshold=threshold,
            fallback=fallback_triggered,
        )
        return ViabilityGateResult(
            passing=passing,
            rejected=rejected,
            threshold_used=threshold,
            fallback_triggered=fallback_triggered,
        )

    async def _write_to_db(self, concept: ScoredConcept) -> None:
        concept_json = {
            "mechanic_tag": concept.mechanic_tag,
            "genre": concept.genre,
            "opportunity_score": concept.opportunity_score,
            "signal_strength": concept.signal_strength,
            "velocity_score": concept.velocity_score,
            "sustained_ccu": concept.sustained_ccu,
            "differentiation_score": concept.differentiation_score,
            "closest_existing_game": concept.gap_result.closest_existing_game,
            "differentiation_suggestions": concept.gap_result.differentiation_suggestions,
        }
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO concept_queue
                    (id, created_at, status, concept_json, opportunity_score, genre, mechanic_tag)
                VALUES ($1, $2, 'queued', $3, $4, $5, $6)
                ON CONFLICT (id) DO NOTHING
                """,
                uuid.UUID(concept.concept_id),
                datetime.now(timezone.utc),
                json.dumps(concept_json),
                concept.opportunity_score,
                concept.genre,
                concept.mechanic_tag,
            )
        log.info(
            "viability_gate.concept_queued",
            concept_id=concept.concept_id,
            score=concept.opportunity_score,
        )

    async def update_consecutive_rejects(
        self, pool: asyncpg.Pool, count: int
    ) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_state (key, value, updated_at)
                VALUES ('consecutive_viability_rejects', $1, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                str(count),
            )

    async def get_consecutive_rejects(self, pool: asyncpg.Pool) -> int:
        async with pool.acquire() as conn:
            val = await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = 'consecutive_viability_rejects'"
            )
            return int(val or 0)


class FeedbackLoop:
    """Adjusts per-mechanic signal weights based on live game performance."""

    async def get_weights(self, pool: asyncpg.Pool) -> dict[str, float]:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT mechanic_tag, weight FROM signal_weights")
            return {row["mechanic_tag"]: row["weight"] for row in rows}

    async def adjust_weights(self, pool: asyncpg.Pool) -> None:
        """
        Run after each PerformanceMonitor cycle:
        - Games CCU > 50 within 7 days → +10% weight for that mechanic
        - Games CCU never > 5 after 14 days → -10% weight
        - Cap: ±40% from baseline (0.6–1.4 range)
        """
        async with pool.acquire() as conn:
            # Boost mechanics from high-performing games
            boostable = await conn.fetch(
                """
                SELECT DISTINCT c.mechanic_tag
                FROM published_games pg
                JOIN concept_queue c ON c.id = pg.concept_id
                JOIN game_metrics gm ON gm.game_id = pg.id
                WHERE gm.ccu > 50
                  AND gm.timestamp >= NOW() - INTERVAL '7 days'
                """
            )
            for row in boostable:
                tag = row["mechanic_tag"]
                await conn.execute(
                    """
                    UPDATE signal_weights
                    SET weight = LEAST(1.4, weight * 1.10),
                        last_updated = NOW()
                    WHERE mechanic_tag = $1
                    """,
                    tag,
                )
                log.info("feedback_loop.boosted", mechanic=tag)

            # Reduce mechanics from underperforming games
            reduceable = await conn.fetch(
                """
                SELECT DISTINCT c.mechanic_tag
                FROM published_games pg
                JOIN concept_queue c ON c.id = pg.concept_id
                WHERE pg.published_at <= NOW() - INTERVAL '14 days'
                  AND NOT EXISTS (
                      SELECT 1 FROM game_metrics gm
                      WHERE gm.game_id = pg.id AND gm.ccu > 5
                  )
                """
            )
            for row in reduceable:
                tag = row["mechanic_tag"]
                await conn.execute(
                    """
                    UPDATE signal_weights
                    SET weight = GREATEST(0.6, weight * 0.90),
                        last_updated = NOW()
                    WHERE mechanic_tag = $1
                    """,
                    tag,
                )
                log.info("feedback_loop.reduced", mechanic=tag)
