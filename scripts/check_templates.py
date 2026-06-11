"""
Compile-check every Luau base template (no LLM, no network).

For each template: substitute placeholders with canned values via
LuauAgent's own substitution logic, run `rojo build`, then AutoValidator.
Exits non-zero if any template fails — run before deploys and after any
template edit:

    python -m scripts.check_templates
"""
import asyncio
import sys
import tempfile

import dotenv


CANNED_CONCEPT = {
    "game_title": "Template Check Game",
    "tagline": "A quick compile check.",
    "core_loop": "Earn coins, buy upgrades, prestige.",
    "monetization": {
        "currency_name": "Coins",
        "game_passes": [
            {"name": "Double Coins", "price_robux": 199, "effect": "income_x2"}
        ],
        "shop_items": [{"name": "Sparkle Trail", "price": 500, "type": "cosmetic"}],
        "vip_server": True,
    },
    "resolved_assets": [{"keyword": "tree", "asset_id": 123456, "name": "Tree"}],
}


async def check_template(mechanic: str, template_name: str) -> bool:
    from build.auto_validator import AutoValidator
    from build.luau_agent import LuauAgent
    from build.rojo_builder import RojoBuilder

    agent = LuauAgent()

    async def no_llm_theme_values(*args, **kwargs):
        return {}

    agent._pick_theme_values = no_llm_theme_values  # offline: defaults fill in

    concept = dict(CANNED_CONCEPT, mechanic_tag=mechanic)
    with tempfile.TemporaryDirectory() as tmp_root:
        build_dir = await agent.generate(
            concept, f"check_{mechanic}", builds_root=tmp_root
        )
        rojo_result = await RojoBuilder().build(build_dir)
        validation = await AutoValidator().validate(build_dir, rojo_result)

    status = "PASS" if validation.passed else "FAIL"
    print(f"[{status}] {template_name} (mechanic: {mechanic})")
    for failure in validation.failures:
        print(f"    - {failure[:300]}")
    return validation.passed


async def amain() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    dotenv.load_dotenv()  # for ROJO_BINARY / BUILDS_ROOT

    from build.luau_agent import TEMPLATE_FOR_TAG

    # One representative mechanic per distinct template
    template_to_mechanic: dict[str, str] = {}
    for mechanic, template in TEMPLATE_FOR_TAG.items():
        template_to_mechanic.setdefault(template, mechanic)

    results = []
    for template, mechanic in sorted(template_to_mechanic.items()):
        results.append(await check_template(mechanic, template))

    ok = all(results)
    print(f"\n{sum(results)}/{len(results)} templates compile cleanly")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
