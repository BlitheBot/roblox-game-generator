"""
ContentDropGenerator (LiveOps step 2) — Claude Sonnet designs a weekly
content drop for a live game, themed around current trending keywords.

The patch only touches config-level data that already flows through
LuauAgent placeholders (shop items, pet name pools, the survival map
list) — core mechanics scripts are never modified. Template limits:
"new machines / prestige tiers" have no extensible config slot in the
base templates, so for idle/incremental the drop lands as new themed
shop items.

The patched concept is persisted to concept_queue and the game is
rebuilt + republished by the pipeline.
"""
import structlog

from intelligence.llm_client import CLAUDE_SONNET, chat_json

log = structlog.get_logger()

PATCH_SCHEMA_HINT = """{
  "new_shop_items": [{"name": "string", "price": 0, "type": "cosmetic|boost|unlock"}],
  "new_pets": {"Common|Uncommon|Rare|Epic|Legendary": ["name"]},
  "new_map": "string or null",
  "drop_summary": "string (one line describing the drop for the changelog)"
}"""

GENRE_GUIDANCE = {
    "idle_tycoon": (
        "Generate 2-3 new purchasable machines/buildings as shop items "
        "(type 'boost' or 'unlock', priced in soft currency 500-50000) "
        "named like production equipment for this game's theme."
    ),
    "incremental_sim": (
        "Generate 2-3 new progression boosters as shop items (type 'boost' "
        "or 'unlock', priced 500-50000 soft currency) that feel like a new "
        "prestige tier or resource for this game's theme."
    ),
    "pet_collect": (
        "Generate 3-5 new collectible pets spread across rarities "
        "(mostly Rare/Epic/Legendary so the drop feels special) in new_pets."
    ),
    "survival_horror": (
        "Generate one new map variant name in new_map (atmospheric, "
        "family-friendly spooky) plus 1-2 themed cosmetic shop items."
    ),
}


async def generate_content_patch(
    concept: dict, meta_keywords: list[str]
) -> dict:
    """Ask Claude Sonnet for a config-only content drop patch."""
    mechanic = concept.get("mechanic_tag", "incremental_sim")
    guidance = GENRE_GUIDANCE.get(mechanic, GENRE_GUIDANCE["incremental_sim"])
    messages = [
        {
            "role": "system",
            "content": (
                "You design weekly content drops for a live Roblox game. "
                "You may ONLY add config data — never gameplay logic. "
                + guidance
                + " Keep every name family-friendly and on-theme. Weave in the "
                "trending keywords where they fit naturally. Unused fields "
                "should be empty lists/objects or null. "
                f"Return JSON exactly matching this schema:\n{PATCH_SCHEMA_HINT}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Game: {concept.get('game_title')}\n"
                f"Mechanic: {mechanic}\n"
                f"Core loop: {concept.get('core_loop', '')}\n"
                f"Existing shop items: {concept.get('monetization', {}).get('shop_items', [])}\n"
                f"Trending keywords: {meta_keywords[:10]}"
            ),
        },
    ]
    patch = await chat_json(CLAUDE_SONNET, messages, temperature=0.8)
    patch.setdefault("new_shop_items", [])
    patch.setdefault("new_pets", {})
    patch.setdefault("new_map", None)
    patch.setdefault("drop_summary", "weekly content drop")
    return patch


def apply_content_patch(concept: dict, patch: dict) -> list[str]:
    """Merge the patch into the concept dict (config-only). Returns
    human-readable change lines for the digest."""
    changes: list[str] = []

    monetization = concept.setdefault("monetization", {})
    shop_items = monetization.setdefault("shop_items", [])
    existing_names = {str(i.get("name", "")).lower() for i in shop_items}
    for item in patch.get("new_shop_items") or []:
        name = str(item.get("name", "")).strip()
        if not name or name.lower() in existing_names:
            continue
        shop_items.append(
            {
                "name": name,
                "price": max(1, int(item.get("price", 1000))),
                "type": item.get("type", "boost"),
            }
        )
        changes.append(f"new shop item: {name}")

    new_pets = patch.get("new_pets") or {}
    if new_pets:
        # Seed with LuauAgent's defaults so adding pets never wipes the
        # pools a first build shipped with
        pools = concept.setdefault(
            "pet_name_pools",
            {
                "Common": ["Scrappy", "Bubbles", "Pip"],
                "Uncommon": ["Marble", "Comet"],
                "Rare": ["Aurora", "Blaze"],
                "Epic": ["Tempest", "Nova"],
                "Legendary": ["Eternity"],
            },
        )
        for rarity, names in new_pets.items():
            if rarity not in pools or not isinstance(names, list):
                continue
            for name in names:
                name = str(name).strip()
                if name and name not in pools[rarity]:
                    pools[rarity].append(name)
                    changes.append(f"new {rarity} pet: {name}")

    new_map = patch.get("new_map")
    if new_map and str(new_map).strip():
        maps = concept.setdefault("maps", ["Crypt", "Shipwreck", "Lighthouse"])
        if new_map not in maps:
            maps.append(str(new_map).strip())
            changes.append(f"new map: {new_map}")

    log.info("liveops.content_patch_applied", changes=len(changes))
    return changes
