"""
GapAnalyzer — scores how differentiated a proposed concept is from the
current top-50 live Roblox games. Flags concepts with similarity > 0.8
for mutation before proceeding.
"""
import asyncio
from dataclasses import dataclass, field

import httpx
import structlog

from .llm_client import DEEPSEEK_V3, chat_json
from .mechanic_mapper import MappedSignal

log = structlog.get_logger()

ROBLOX_GAMES_LIST = "https://www.roblox.com/games/list-json"


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

    def __init__(self) -> None:
        self._top_games_cache: list[dict] = []

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
        if self._top_games_cache:
            return self._top_games_cache
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    ROBLOX_GAMES_LIST,
                    params={
                        "sortToken": "",
                        "gameFilter": "0",
                        "timeFilter": "0",
                        "genreFilter": "0",
                        "startRows": "0",
                        "maxRows": "50",
                    },
                    headers={"User-Agent": "RobloxStudioBot/1.0"},
                )
                resp.raise_for_status()
                data = resp.json()
                games = data.get("Games", [])
                self._top_games_cache = [
                    {
                        "name": g.get("Name", ""),
                        "playing": g.get("Playing", 0),
                        "description": g.get("GameDescription", ""),
                    }
                    for g in games[:50]
                ]
        except Exception as exc:
            log.warning("gap_analyzer.fetch_games_failed", error=str(exc))
            self._top_games_cache = []
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
