"""
MechanicMapper — maps incoming cultural trend signals to proven Roblox
core loop mechanics using DeepSeek V3 + a static mechanic library.
"""
from dataclasses import dataclass

import structlog

from .llm_client import DEEPSEEK_V3, chat_json
from .meta_scout import Signal
from .trend_predictor import PreArrivalTrend

log = structlog.get_logger()

# Static mechanic library — spec Section 3.3
MECHANIC_LIBRARY: dict[str, str] = {
    "idle_tycoon":     "Build and expand a production facility, prestige loop",
    "pet_collect":     "Collect/hatch/trade named entities with rarity tiers",
    "survival_horror": "Escape/survive against a threat, rounds-based",
    "obby":            "Obstacle course with checkpoints and cosmetic rewards",
    "rpg_dungeon":     "Stats, gear, and dungeon clearing with progression",
    "incremental_sim": "Grow a thing over time, sell for currency, rebirth",
}

VALID_TAGS = set(MECHANIC_LIBRARY.keys())


@dataclass
class MappedSignal:
    source_type: str        # 'meta_scout' | 'trend_predictor'
    raw_genre: str
    raw_trend: str
    mechanic_tag: str
    confidence: float       # 0.0–1.0


class MechanicMapper:
    """Adds mechanic_tag to each signal from MetaScout and TrendPredictor."""

    async def map_signals(
        self,
        meta_signals: list[Signal],
        pre_arrival_trends: list[PreArrivalTrend],
    ) -> list[MappedSignal]:
        items = [
            {
                "id": i,
                "source_type": "meta_scout",
                "genre": s.genre,
                "trend": s.genre,
                "hint_mechanic": s.mechanic_tag,
            }
            for i, s in enumerate(meta_signals)
        ] + [
            {
                "id": len(meta_signals) + i,
                "source_type": "trend_predictor",
                "genre": t.suggested_mechanic,
                "trend": t.trend_name,
                "hint_mechanic": t.suggested_mechanic,
            }
            for i, t in enumerate(pre_arrival_trends)
        ]

        if not items:
            return []

        result = await self._call_llm(items)
        mapped: list[MappedSignal] = []

        all_sources = meta_signals + pre_arrival_trends  # type: ignore[operator]
        for entry in result.get("mappings", []):
            idx = entry.get("id", -1)
            mechanic_tag = entry.get("mechanic_tag", "")
            confidence = float(entry.get("confidence", 0.5))

            if mechanic_tag not in VALID_TAGS:
                mechanic_tag = self._best_guess_from_hint(
                    items[idx]["hint_mechanic"] if idx < len(items) else ""
                )

            source_entry = items[idx] if 0 <= idx < len(items) else {}
            mapped.append(
                MappedSignal(
                    source_type=source_entry.get("source_type", "unknown"),
                    raw_genre=source_entry.get("genre", ""),
                    raw_trend=source_entry.get("trend", ""),
                    mechanic_tag=mechanic_tag,
                    confidence=confidence,
                )
            )

        log.info("mechanic_mapper.complete", mapped_count=len(mapped))
        return mapped

    async def _call_llm(self, items: list[dict]) -> dict:
        library_desc = "\n".join(
            f"- {tag}: {desc}" for tag, desc in MECHANIC_LIBRARY.items()
        )
        payload_str = str(items)[:6000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Roblox game design expert. "
                    "Map each incoming trend/signal to the best matching core mechanic "
                    "from the library below. Each signal has an 'id' field you must preserve.\n\n"
                    f"Mechanic library:\n{library_desc}\n\n"
                    "For each input item return: id (same integer), mechanic_tag (from library), "
                    "confidence (0.0–1.0). "
                    "Return JSON with key 'mappings' as an array."
                ),
            },
            {
                "role": "user",
                "content": f"Signals to map:\n{payload_str}",
            },
        ]
        return await chat_json(DEEPSEEK_V3, messages, temperature=0.2)

    @staticmethod
    def _best_guess_from_hint(hint: str) -> str:
        """Fall back to hint if valid, else default to incremental_sim."""
        if hint in VALID_TAGS:
            return hint
        return "incremental_sim"
