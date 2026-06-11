"""
ConceptGenerator (spec 4.1) — expands a viability-gated concept from
concept_queue into a full game concept JSON (title, loop, systems,
monetization, toolbox keywords) using DeepSeek V3.
"""
import json
import uuid

import asyncpg
import structlog

from intelligence.llm_client import DEEPSEEK_V3, chat_json
from intelligence.name_blacklist import check_similarity, get_blacklist

log = structlog.get_logger()

MAX_TITLE_REGENS = 3

# Maps mechanic_tag → genre account name (spec Section 2)
GENRE_ACCOUNTS = {
    "idle_tycoon":     "idle",
    "incremental_sim": "sim",
    "pet_collect":     "sim",
    "survival_horror": "horror",
    "obby":            "sim",
    "rpg_dungeon":     "sim",
}

CONCEPT_SCHEMA_HINT = """{
  "game_title": "string",
  "tagline": "string",
  "mechanic_tag": "string",
  "core_loop": "string (30-second description)",
  "systems": ["string"],
  "monetization": {
    "game_passes": [{"name": "string", "price_robux": 0, "benefit": "string"}],
    "currency_name": "string",
    "shop_items": [{"name": "string", "price": 0, "type": "cosmetic|boost|unlock"}],
    "vip_server": true
  },
  "toolbox_keywords": ["string"],
  "target_genre_account": "string"
}"""


class ConceptGenerator:
    """Turns a queued concept row into a buildable game concept."""

    async def generate(self, pool: asyncpg.Pool, concept_id: str) -> dict:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT concept_json, genre, mechanic_tag FROM concept_queue WHERE id = $1",
                uuid.UUID(concept_id),
            )
        if not row:
            raise ValueError(f"concept {concept_id} not found in concept_queue")

        seed = json.loads(row["concept_json"]) if isinstance(row["concept_json"], str) else dict(row["concept_json"])
        mechanic_tag = row["mechanic_tag"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a Roblox game designer. Expand the seed opportunity below into "
                    "a complete, family-friendly game concept. The game MUST use the given "
                    "mechanic_tag as its core loop. Monetization must follow Roblox norms: "
                    "game passes 99-499 Robux, shop items priced in soft currency. "
                    "toolbox_keywords should be 5-8 short search phrases for free Roblox "
                    "Toolbox models matching the theme. "
                    "Avoid any weapons-realism, gore, or adult themes (TOS-safe). "
                    f"Return JSON exactly matching this schema:\n{CONCEPT_SCHEMA_HINT}"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Seed opportunity:\n"
                    f"  mechanic_tag: {mechanic_tag}\n"
                    f"  genre: {row['genre']}\n"
                    f"  differentiation_suggestions: {seed.get('differentiation_suggestions', [])}\n"
                    f"  closest_existing_game (avoid cloning): {seed.get('closest_existing_game', 'n/a')}"
                ),
            },
        ]
        concept = await chat_json(DEEPSEEK_V3, messages, temperature=0.8)
        await self._ensure_distinct_title(concept)

        # Enforce invariants regardless of what the model returned
        concept["mechanic_tag"] = mechanic_tag
        concept["target_genre_account"] = GENRE_ACCOUNTS.get(mechanic_tag, "sim")
        concept.setdefault("toolbox_keywords", [])
        concept.setdefault("monetization", {})
        concept["monetization"].setdefault("game_passes", [])
        concept["monetization"].setdefault("shop_items", [])
        concept["monetization"].setdefault("currency_name", "Coins")
        concept["monetization"].setdefault("vip_server", False)

        log.info(
            "concept_generator.complete",
            concept_id=concept_id,
            title=concept.get("game_title"),
        )
        return concept

    async def _ensure_distinct_title(self, concept: dict) -> None:
        """Fuzzy-check the title against the top-50 blacklist (>0.75 means
        too close to an existing hit) and regenerate the name until it
        clears or MAX_TITLE_REGENS is exhausted. Mutates concept in place;
        a still-colliding title after all retries is kept with a warning
        rather than failing the build — GapAnalyzer already gates clones."""
        blacklist = await get_blacklist()
        if not blacklist:
            return

        rejected: list[str] = []
        for _ in range(MAX_TITLE_REGENS + 1):
            title = str(concept.get("game_title", "")).strip()
            collision = check_similarity(title, blacklist) if title else ("", 1.0)
            if collision is None:
                return
            rejected.append(title)
            log.info(
                "concept_generator.title_collision",
                title=title,
                closest=collision[0],
                score=round(collision[1], 3),
            )
            concept["game_title"] = await self._regenerate_title(concept, rejected)

        log.warning(
            "concept_generator.title_still_similar",
            title=concept.get("game_title"),
            attempts=MAX_TITLE_REGENS,
        )

    async def _regenerate_title(self, concept: dict, rejected: list[str]) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "You name Roblox games. Produce ONE new, family-friendly title "
                    "for the concept below. It must be clearly distinct from every "
                    "title in the rejected list (those were too similar to existing "
                    "top games). Keep it short and punchy. "
                    'Return JSON: {"game_title": "string"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Concept tagline: {concept.get('tagline', '')}\n"
                    f"Core loop: {concept.get('core_loop', '')}\n"
                    f"Mechanic: {concept.get('mechanic_tag', '')}\n"
                    f"Rejected titles (avoid anything similar): {rejected}"
                ),
            },
        ]
        result = await chat_json(DEEPSEEK_V3, messages, temperature=0.9)
        new_title = str(result.get("game_title", "")).strip()
        return new_title or f"{concept.get('game_title', 'Untitled')} Frenzy"
