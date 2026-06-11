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
from intelligence.seasonal_context import get_seasonal_context

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
    "vip_server": true,
    "casual_tier": {
      "starter_pack_contents": "string (what the 99-Robux welcome pack contains, themed)",
      "daily_deal_pool": ["3-6 shop item names eligible for the rotating daily deal"],
      "currency_bundles": [
        {"name": "Small", "price": 75, "amount": 0},
        {"name": "Medium", "price": 150, "amount": 0, "badge": "BEST VALUE"},
        {"name": "Large", "price": 300, "amount": 0}
      ]
    },
    "mid_tier": {
      "season_pass_price": 499,
      "season_pass_perks": ["strings: 2x multiplier, exclusive cosmetic name, daily bonus, 20-tier track"],
      "season_pass_exclusive_cosmetic": "string (themed cosmetic name)",
      "vip_pass_price": 999,
      "vip_pass_perks": ["strings"],
      "vip_exclusive_feature": "string (genre-appropriate VIP-only area/feature)"
    },
    "whale_tier": {
      "limited_items": [{"name": "string", "price": 0, "stock": 0}],
      "founders_pack_price": 4999,
      "founders_pack_limit": 100,
      "custom_nametag_price": 2499
    },
    "fomo": {
      "flash_sale_frequency_days": 3,
      "seasonal_items": ["2-3 themed cosmetic names for seasonal events"]
    }
  },
  "toolbox_keywords": ["string"],
  "target_genre_account": "string"
}"""

# Fixed price points for the three-tier framework (enforced in code so a
# model reply can never reprice the framework)
TIER_PRICES = {
    "starter_pack": 99,
    "bundle_small": 75,
    "bundle_medium": 150,
    "bundle_large": 300,
    "season_pass": 499,
    "vip_pass": 999,
    "custom_nametag": 2499,
    "founders_pack": 4999,
}


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

        season = get_seasonal_context()
        season_note = (
            f"Seasonal context: {season.theming_hint}\n"
            if season.is_seasonal
            else ""
        )

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
                    + season_note
                    + f"Return JSON exactly matching this schema:\n{CONCEPT_SCHEMA_HINT}"
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
        self._normalize_monetization_tiers(concept["monetization"])

        log.info(
            "concept_generator.complete",
            concept_id=concept_id,
            title=concept.get("game_title"),
        )
        return concept

    @staticmethod
    def _normalize_monetization_tiers(monetization: dict) -> None:
        """Force the three-tier framework into a valid shape: fixed price
        points, medium-bundle anchoring (3x currency for 2x price), sane
        limited-item stock/prices. Models theme names; code owns numbers.

        Two requested mechanics are intentionally NOT part of the
        framework: the starter pack ships without a countdown timer, and
        there is no purchase-streak reward — countdown pressure and
        spend-streak loops on a child-majority platform are the dark
        patterns the FTC's Fortnite consent order targeted. Login streak
        rewards (RetentionService) cover the habit loop by rewarding
        play instead.
        """
        casual = monetization.setdefault("casual_tier", {})
        casual.setdefault("starter_pack_contents", "a themed welcome bundle of currency")
        casual["starter_pack_price"] = TIER_PRICES["starter_pack"]
        pool = [str(n) for n in casual.get("daily_deal_pool", []) if str(n).strip()]
        casual["daily_deal_pool"] = pool or [
            str(i.get("name")) for i in monetization.get("shop_items", [])[:4]
        ]
        # Anchored bundles: medium gives 3x small's currency for 2x the price
        small_amount = 500
        for bundle in casual.get("currency_bundles", []):
            if str(bundle.get("name", "")).lower() == "small":
                try:
                    small_amount = max(100, int(bundle.get("amount", 500)))
                except (TypeError, ValueError):
                    pass
        casual["currency_bundles"] = [
            {"name": "Small", "price": TIER_PRICES["bundle_small"], "amount": small_amount},
            {"name": "Medium", "price": TIER_PRICES["bundle_medium"],
             "amount": small_amount * 3, "badge": "BEST VALUE"},
            {"name": "Large", "price": TIER_PRICES["bundle_large"], "amount": small_amount * 7},
        ]

        mid = monetization.setdefault("mid_tier", {})
        mid["season_pass_price"] = TIER_PRICES["season_pass"]
        mid["vip_pass_price"] = TIER_PRICES["vip_pass"]
        mid.setdefault("season_pass_perks", [
            "2x earnings for 30 days", "exclusive cosmetic",
            "boosted daily login bonus", "20-tier reward track",
        ])
        mid.setdefault("season_pass_exclusive_cosmetic", "Season Champion Aura")
        mid.setdefault("vip_pass_perks", ["1.5x permanent earnings", "VIP chat tag"])
        mid.setdefault("vip_exclusive_feature", "VIP lounge area")

        whale = monetization.setdefault("whale_tier", {})
        whale["founders_pack_price"] = TIER_PRICES["founders_pack"]
        whale["founders_pack_limit"] = 100
        whale["custom_nametag_price"] = TIER_PRICES["custom_nametag"]
        limited = []
        for item in (whale.get("limited_items") or [])[:3]:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            try:
                price = min(3000, max(1500, int(item.get("price", 2000))))
                stock = min(500, max(25, int(item.get("stock", 100))))
            except (TypeError, ValueError):
                price, stock = 2000, 100
            limited.append({"name": name, "price": price, "stock": stock})
        whale["limited_items"] = limited or [
            {"name": "Founders Crown", "price": 2500, "stock": 100},
            {"name": "Eternal Flame Aura", "price": 2000, "stock": 150},
            {"name": "Mythic Banner", "price": 1500, "stock": 200},
        ]

        fomo = monetization.setdefault("fomo", {})
        fomo["flash_sale_frequency_days"] = 3
        seasonal = [str(n) for n in fomo.get("seasonal_items", []) if str(n).strip()]
        fomo["seasonal_items"] = seasonal[:3] or ["Seasonal Aura", "Festive Trail"]

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
