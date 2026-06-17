"""
LuauAgent (spec 4.2) — customizes a base Luau template into a complete
game source tree. Claude Sonnet picks themed values; deterministic Python
code performs the actual placeholder substitution so output always parses.

Escalation: the pipeline passes model=CLAUDE_OPUS after 3 validator
failures (spec 4.6).
"""
import json
import os
import pathlib
import shutil

import structlog

from intelligence.llm_client import CLAUDE_SONNET, chat_json

log = structlog.get_logger()

TEMPLATES_DIR = pathlib.Path(__file__).parent.parent / "templates"

# Shared, genre-agnostic UI layer injected into every build regardless of
# template. The canonical source lives in templates/shared/; these land in the
# build's src tree (so the existing project.json folder mappings pick them up)
# with the same placeholder substitution applied as the template files.
# LoadingScreen.client.luau deliberately overwrites the template's own loading
# screen so every game ships the one polished version.
SHARED_DIR = TEMPLATES_DIR / "shared"
SHARED_FILE_TARGETS = {
    "DesignSystem.luau": "src/shared/DesignSystem.luau",
    "HUDClient.client.luau": "src/client/HUDClient.client.luau",
    "ShopClient.client.luau": "src/client/ShopClient.client.luau",
    "LoadingScreen.client.luau": "src/StarterGui/LoadingScreen.client.luau",
    # Sound layer (GAP 1): shared id table + client playback/settings + server
    # persistence. SoundConfig is required by both sides.
    "SoundConfig.luau": "src/shared/SoundConfig.luau",
    "SoundClient.client.luau": "src/client/SoundClient.client.luau",
    "SoundSystem.server.luau": "src/ServerScriptService/SoundSystem.server.luau",
    # Onboarding layer (GAP 2): first-time player guide (server gate + client UI).
    "OnboardingService.server.luau": "src/ServerScriptService/OnboardingService.server.luau",
    "OnboardingClient.client.luau": "src/client/OnboardingClient.client.luau",
}

# Placeholders filled by code (numerics, monetization tables, titles) —
# never offered to the theming LLM and never overridable by its output
PROGRAMMATIC_PLACEHOLDERS = {
    "{{GAME_TITLE}}",
    "{{TAGLINE}}",
    "{{MECHANIC_TAG}}",
    "{{CURRENCY_NAME}}",
    "{{VIP_SERVER_ENABLED}}",
    "{{ROUND_SECONDS}}",
    "{{BASE_DROP_VALUE}}",
    "{{DROP_INTERVAL_SECONDS}}",
    "{{STARTING_CURRENCY}}",
    "{{PET_STARTING_CURRENCY}}",
    "{{BASE_INCOME_PER_SECOND}}",
    "{{BASE_GROWTH_PER_TICK}}",
    "{{BASE_SELL_VALUE}}",
    "{{SURVIVAL_REWARD}}",
    "{{RETENTION_REWARD_BOOST}}",
}

TEMPLATE_FOR_TAG = {
    "idle_tycoon":     "idle_tycoon_base",
    "pet_collect":     "pet_collect_base",
    "survival_horror": "survival_horror_base",
    "incremental_sim": "incremental_sim_base",
    # TODO: obby and rpg_dungeon have no dedicated base template yet (spec 4.2
    # lists only four). Fall back to the closest core loop until templates exist.
    "obby":            "incremental_sim_base",
    "rpg_dungeon":     "survival_horror_base",
}


def _lua_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _to_lua(value) -> str:
    """Serialize a Python value to a Lua table literal."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{_lua_escape(value)}"'
    if isinstance(value, list):
        return "{ " + ", ".join(_to_lua(v) for v in value) + " }"
    if isinstance(value, dict):
        parts = []
        for key, val in value.items():
            if isinstance(key, str) and key.isidentifier():
                parts.append(f"{key} = {_to_lua(val)}")
            else:
                parts.append(f"[{_to_lua(key)}] = {_to_lua(val)}")
        return "{ " + ", ".join(parts) + " }"
    return "nil"


class LuauAgent:
    """Generates the full game source tree from a template + concept JSON."""

    async def generate(
        self,
        concept: dict,
        game_id: str,
        builds_root: str | None = None,
        model: str = CLAUDE_SONNET,
        error_context: str | None = None,
    ) -> pathlib.Path:
        """
        Returns the path to the generated build directory:
        {builds_root}/active/{game_id}/ containing src/ + default.project.json
        """
        mechanic_tag = concept["mechanic_tag"]
        template_name = TEMPLATE_FOR_TAG.get(mechanic_tag)
        if not template_name:
            raise ValueError(f"no template for mechanic_tag {mechanic_tag}")
        template_dir = TEMPLATES_DIR / template_name

        manifest = json.loads((template_dir / "manifest.json").read_text())

        theme_values = await self._pick_theme_values(concept, manifest, model, error_context)
        substitutions = self._build_substitutions(concept, manifest, theme_values)

        builds_root = builds_root or os.environ.get("BUILDS_ROOT", "/builds")
        out_dir = pathlib.Path(builds_root) / "active" / game_id
        if out_dir.exists():
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True)

        for rel_path in manifest["files"]:
            src_file = template_dir / rel_path
            dst_file = out_dir / rel_path
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            content = src_file.read_text(encoding="utf-8")
            for placeholder, replacement in substitutions.items():
                content = content.replace(placeholder, replacement)
            dst_file.write_text(content, encoding="utf-8", newline="\n")

        # Inject the shared UI layer (DesignSystem + unified HUD/Shop/Loading)
        # into every build, applying the same substitutions. Overwrites any
        # same-path template file (e.g. the old LoadingScreen) on purpose.
        for filename, rel_target in SHARED_FILE_TARGETS.items():
            shared_src = SHARED_DIR / filename
            if not shared_src.exists():
                continue
            dst_file = out_dir / rel_target
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            content = shared_src.read_text(encoding="utf-8")
            for placeholder, replacement in substitutions.items():
                content = content.replace(placeholder, replacement)
            dst_file.write_text(content, encoding="utf-8", newline="\n")

        # Record the concept alongside the build for later pipeline stages
        (out_dir / "concept.json").write_text(json.dumps(concept, indent=2), encoding="utf-8")

        log.info(
            "luau_agent.generated",
            game_id=game_id,
            template=template_name,
            model=model,
            out_dir=str(out_dir),
        )
        return out_dir

    async def _pick_theme_values(
        self, concept: dict, manifest: dict, model: str, error_context: str | None
    ) -> dict:
        """Ask the LLM for themed values for the template's free-text placeholders."""
        free_text_placeholders = [
            p for p in manifest["placeholders"]
            if not p.endswith("_LUA}}") and p not in PROGRAMMATIC_PLACEHOLDERS
        ]
        if not free_text_placeholders:
            return {}

        error_note = (
            f"\nA previous attempt failed validation with this error — avoid repeating it:\n{error_context}"
            if error_context
            else ""
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are theming a Roblox game template. For each placeholder, return a "
                    "short, family-friendly, theme-appropriate value. Values are inserted into "
                    "Luau string literals, so use plain text without quotes or special characters. "
                    "For {{PET_NAMES_LUA}}-style pools you will NOT be asked. "
                    "For {{ROUND_SECONDS}} you will NOT be asked. "
                    "Return a JSON object mapping each placeholder (including braces) to its value."
                    + error_note
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Game concept:\n{json.dumps(concept, indent=2)[:3000]}\n\n"
                    f"Placeholders to fill: {free_text_placeholders}"
                ),
            },
        ]
        result = await chat_json(model, messages, temperature=0.7)
        # Sanitize: strip quotes/newlines the model may have included
        return {
            k: str(v).replace('"', "").replace("\n", " ").strip()
            for k, v in result.items()
            if k in free_text_placeholders
        }

    def _build_substitutions(
        self, concept: dict, manifest: dict, theme_values: dict
    ) -> dict[str, str]:
        monetization = concept.get("monetization", {})

        game_passes_lua = _to_lua([
            {
                "name": gp.get("name", "Pass"),
                "id": int(gp.get("id", 0)),  # real pass ids assigned post-publish
                "price_robux": int(gp.get("price_robux", 99)),
                "effect": gp.get("effect", "income_x2"),
            }
            for gp in monetization.get("game_passes", [])
        ])
        shop_items_lua = _to_lua([
            {
                "name": item.get("name", "Item"),
                "price": int(item.get("price", 100)),
                "type": item.get("type", "cosmetic"),
            }
            for item in monetization.get("shop_items", [])
        ])
        asset_ids_lua = _to_lua([
            int(asset["asset_id"])
            for asset in concept.get("resolved_assets", [])
            if str(asset.get("asset_id", "")).isdigit()
        ])
        # Sibling games on the same genre account (cross-promotion billboards);
        # the pipeline injects cross_promo_siblings before generation
        cross_promo_lua = _to_lua([
            {
                "title": str(s.get("title", "")),
                "universe_id": int(s.get("universe_id", 0)),
                "place_id": int(s.get("place_id", 0)),
            }
            for s in concept.get("cross_promo_siblings", [])
        ])

        substitutions: dict[str, str] = {
            "{{GAME_TITLE}}": concept.get("game_title", "Untitled Game"),
            "{{TAGLINE}}": concept.get("tagline", "An exciting new adventure awaits!"),
            "{{MECHANIC_TAG}}": concept.get("mechanic_tag", ""),
            "{{CURRENCY_NAME}}": monetization.get("currency_name", "Coins"),
            "{{GAME_PASSES_LUA}}": game_passes_lua,
            "{{SHOP_ITEMS_LUA}}": shop_items_lua,
            "{{VIP_SERVER_ENABLED}}": "true" if monetization.get("vip_server") else "false",
            "{{TOOLBOX_ASSET_IDS_LUA}}": asset_ids_lua,
            "{{CROSS_PROMO_LUA}}": cross_promo_lua,
            "{{ROUND_SECONDS}}": "120",
        }

        # LiveOps-tunable balance knobs (concept.balance, improvement 8).
        # Values are forced through float() so a malformed patch can never
        # inject non-numeric text into Luau source.
        balance = concept.get("balance", {}) or {}

        def _num(key: str, default: float) -> str:
            try:
                value = float(balance.get(key, default))
            except (TypeError, ValueError):
                value = default
            return str(int(value)) if value == int(value) else str(value)

        substitutions.update({
            "{{BASE_DROP_VALUE}}":        _num("base_drop_value", 1),
            "{{DROP_INTERVAL_SECONDS}}":  _num("drop_interval_seconds", 2.0),
            "{{STARTING_CURRENCY}}":      _num("starting_currency", 0),
            "{{PET_STARTING_CURRENCY}}":  _num("pet_starting_currency", 250),
            "{{BASE_INCOME_PER_SECOND}}": _num("base_income_per_second", 1),
            "{{BASE_GROWTH_PER_TICK}}":   _num("base_growth_per_tick", 1),
            "{{BASE_SELL_VALUE}}":        _num("base_sell_value", 1),
            "{{SURVIVAL_REWARD}}":        _num("survival_reward", 50),
            "{{RETENTION_REWARD_BOOST}}": _num("retention_reward_boost", 1),
        })

        # Three-tier monetization config for MonetizationService
        # (improvement 9). product_ids map platform-created developer
        # product / game pass ids; they stay 0 until assigned post-publish,
        # which hides those purchases client-side instead of breaking.
        monetization_config = {
            "shop_items": [
                {
                    "name": item.get("name", "Item"),
                    "price": int(item.get("price", 100)),
                    "type": item.get("type", "cosmetic"),
                }
                for item in monetization.get("shop_items", [])
            ],
            "casual_tier": monetization.get("casual_tier", {}),
            "mid_tier": monetization.get("mid_tier", {}),
            "whale_tier": monetization.get("whale_tier", {}),
            "fomo": monetization.get("fomo", {}),
            "product_ids": {
                key: int(value)
                for key, value in (monetization.get("product_ids") or {}).items()
                if str(value).lstrip("-").isdigit()
            },
        }
        substitutions["{{MONETIZATION_LUA}}"] = _to_lua(monetization_config)

        # Survival map list — content drops append variants via concept.maps
        maps = [str(m) for m in (concept.get("maps") or []) if str(m).strip()]
        substitutions["{{MAPS_LUA}}"] = _to_lua(
            maps or ["Crypt", "Shipwreck", "Lighthouse"]
        )

        # Themed pet name pools for pet_collect template
        if "{{PET_NAMES_LUA}}" in manifest["placeholders"]:
            pools = concept.get("pet_name_pools") or {
                "Common": ["Scrappy", "Bubbles", "Pip"],
                "Uncommon": ["Marble", "Comet"],
                "Rare": ["Aurora", "Blaze"],
                "Epic": ["Tempest", "Nova"],
                "Legendary": ["Eternity"],
            }
            substitutions["{{PET_NAMES_LUA}}"] = _to_lua(pools)

        # Theming values never override programmatic/numeric placeholders
        substitutions.update({
            k: v for k, v in theme_values.items()
            if k not in PROGRAMMATIC_PLACEHOLDERS and not k.endswith("_LUA}}")
        })

        # Any placeholder still unfilled gets a safe default so output parses
        for placeholder in manifest["placeholders"]:
            if placeholder not in substitutions:
                substitutions[placeholder] = "Item"

        return substitutions
