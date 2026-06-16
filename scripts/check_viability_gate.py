"""Offline regression check for viability gate fallback semantics (spec
Section 20): normal cycles reject everything below 0.65 (arming the
consecutive-reject counter), the 4th consecutive rejection cycle lowers
the threshold to 0.50, and only that fallback cycle may force-pass the
highest-scoring concept.

Run: python scripts/check_viability_gate.py
"""
import asyncio
import sys

sys.path.insert(0, ".")

from intelligence.gap_analyzer import GapAnalysisResult
from intelligence.scoring_engine import ScoredConcept, ViabilityGate


def concept(score: float) -> ScoredConcept:
    gap = GapAnalysisResult(
        concept_id="00000000-0000-0000-0000-000000000001",
        mechanic_tag="idle_tycoon",
        raw_genre="idle",
        similarity_score=0.5,
        closest_existing_game="X",
    )
    return ScoredConcept(
        concept_id=gap.concept_id,
        mechanic_tag="idle_tycoon",
        genre="idle",
        opportunity_score=score,
        signal_strength=0.5,
        velocity_score=0.5,
        sustained_ccu=False,
        differentiation_score=0.5,
        gap_result=gap,
    )


async def main() -> None:
    gate = ViabilityGate(pool=None)  # type: ignore[arg-type]
    written = []

    async def fake_write(c):
        written.append(c.concept_id)

    gate._write_to_db = fake_write  # type: ignore[method-assign]

    # Normal cycle, all below 0.65 -> must reject everything (counter arms)
    r = await gate.filter([concept(0.40), concept(0.30)], consecutive_rejects=0)
    assert not r.passing and len(r.rejected) == 2 and not r.fallback_triggered, r
    assert r.threshold_used == 0.65

    # Normal cycle, one above threshold -> passes normally
    r = await gate.filter([concept(0.70), concept(0.30)], consecutive_rejects=0)
    assert len(r.passing) == 1 and not r.fallback_triggered

    # 4th cycle (3 consecutive rejects) -> fallback threshold 0.50
    r = await gate.filter([concept(0.55)], consecutive_rejects=3)
    assert r.fallback_triggered and r.threshold_used == 0.50 and len(r.passing) == 1

    # 4th cycle, nothing even above 0.50 -> force-pass best concept
    r = await gate.filter([concept(0.20), concept(0.45)], consecutive_rejects=3)
    assert r.fallback_triggered and len(r.passing) == 1
    assert r.passing[0].opportunity_score == 0.45

    print("GATE LOGIC OK")


asyncio.run(main())
