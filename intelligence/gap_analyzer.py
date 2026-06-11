"""
GapAnalyzer — scores how differentiated a proposed concept is from the
current top-50 live Roblox games. Flags concepts with similarity > 0.8
for mutation before proceeding.
"""
import asyncio
from dataclasses import dataclass, field

import structlog

from .llm_client import DEEPSEEK_V3, chat_json
from .mechanic_mapper import MappedSignal
from .roblox_games import fetch_top_games

log = structlog.get_logger()


@dataclass
class GapAnalysisResult:
    concept_id: str
    mechanic_tag: str
    raw_genre: str
    similarity_score: float
    closest_existing_game: str
    differentiation_suggestions: list[str] = field(default_factory=list)

    @property
    def is_differentiated(self) -> bool:
        return self.similarity_score <= 0.8


class GapAnalyzer:
    """Checks proposed concepts against current Roblox top-50 for differentiation."""

    CACHE_TTL_SECONDS = 6 * 3600  # one intelligence-cycle interval

    def __init__(self) -> None:
        self._top_games_cache: list[dict] = []
        self._cache_fetched_at: float = 0.0

    async def analyze(self, mapped_signals: list[MappedSignal]) -> list[GapAnalysisResult]:
        top_games = await self._fetch_top_games()
        tasks = [
            self._analyze_one(signal, top_games)
            for signal in mapped_signals
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid = []
        for r in results:
            if isinstance(r, Exception):
                log.warning("gap_analyzer.failed", error=str(r))
            else:
                valid.append(r)
        log.info("gap_analyzer.complete", total=len(valid))
        return valid

    async def _fetch_top_games(self) -> list[dict]:
        import time

        # The analyzer instance lives as long as the orchestrator — expire
        # the cache so differentiation isn't scored against a stale top-50
        if not self._top_games_cache or (
            time.monotonic() - self._cache_fetched_at > self.CACHE_TTL_SECONDS
        ):
            # fetch_top_games returns [] on failure — degrade gracefully
            self._top_games_cache = [
                {"name": g["name"], "playing": g["playing"], "up_votes": g["up_votes"]}
                for g in await fetch_top_games(50)
            ]
            self._cache_fetched_at = time.monotonic()
        return self._top_games_cache

    async def _analyze_one(
        self, signal: MappedSignal, top_games: list[dict]
    ) -> GapAnalysisResult:
        import uuid
        concept_id = str(uuid.uuid4())

        games_str = str(top_games)[:5000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Roblox market analyst. "
                    "Given a proposed game concept (genre + mechanic) and the current top-50 Roblox games, "
                    "calculate a similarity_score (0.0–1.0, where 1.0 = identical to existing games). "
                    "Identify the closest existing game and provide 2–3 differentiation suggestions "
                    "if similarity > 0.8. "
                    "Return JSON with keys: similarity_score (float), closest_existing_game (string), "
                    "differentiation_suggestions (list of strings)."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Proposed concept:\n"
                    f"  genre: {signal.raw_genre}\n"
                    f"  mechanic_tag: {signal.mechanic_tag}\n"
                    f"  trend: {signal.raw_trend}\n\n"
                    f"Current top-50 Roblox games:\n{games_str}"
                ),
            },
        ]
        result = await chat_json(DEEPSEEK_V3, messages, temperature=0.2)

        return GapAnalysisResult(
            concept_id=concept_id,
            mechanic_tag=signal.mechanic_tag,
            raw_genre=signal.raw_genre,
            similarity_score=float(result.get("similarity_score", 0.5)),
            closest_existing_game=result.get("closest_existing_game", ""),
            differentiation_suggestions=result.get("differentiation_suggestions", []),
        )
