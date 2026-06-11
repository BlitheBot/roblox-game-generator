"""
ScriptGenerator (marketing step 1) — DeepSeek V3 writes a 15-30 second
short-form video script for a freshly published game.

Output dict:
    hook              first-3-seconds scroll-stopper line
    description       what makes the game fun/unique (spoken middle)
    cta               call to action ("Play now on Roblox — link in bio")
    voiceover_text    TTS-ready transcript (no stage directions)
    suggested_hashtags  list like ["#roblox", "#petsim", ...]
"""
import structlog

from intelligence.llm_client import DEEPSEEK_V3, chat_json

log = structlog.get_logger()

SCRIPT_SCHEMA_HINT = """{
  "hook": "string (one punchy line, <= 12 words)",
  "description": "string (2-3 short spoken sentences on what makes it fun)",
  "cta": "string (one line call to action)",
  "voiceover_text": "string (hook + description + cta as pure spoken text, no stage directions, 40-75 words total)",
  "suggested_hashtags": ["#tag1", "#tag2"]
}"""


async def generate_script(concept: dict) -> dict:
    """Generate the marketing video script from a game's concept JSON."""
    messages = [
        {
            "role": "system",
            "content": (
                "You write scripts for 15-30 second vertical short-form videos "
                "(TikTok / Reels / Shorts) promoting Roblox games to a young "
                "audience. The hook must stop the scroll in the first 3 seconds. "
                "Keep everything family-friendly, high-energy, and concrete — "
                "name what the player actually DOES in the game. voiceover_text "
                "must read naturally aloud in 15-30 seconds (40-75 words) and "
                "contain no stage directions, emoji, or hashtags. Suggest 4-6 "
                "lowercase hashtags relevant to the game and genre. "
                f"Return JSON exactly matching this schema:\n{SCRIPT_SCHEMA_HINT}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Game title: {concept.get('game_title', 'Roblox Game')}\n"
                f"Tagline: {concept.get('tagline', '')}\n"
                f"Genre/mechanic: {concept.get('mechanic_tag', '')}\n"
                f"Core loop: {concept.get('core_loop', '')}\n"
                f"Systems: {concept.get('systems', [])}"
            ),
        },
    ]
    script = await chat_json(DEEPSEEK_V3, messages, temperature=0.8)

    # Normalize so downstream steps never KeyError on a sloppy model reply
    script.setdefault("hook", concept.get("tagline") or concept.get("game_title", ""))
    script.setdefault("description", concept.get("core_loop", ""))
    script.setdefault("cta", "Play now on Roblox — link in bio!")
    if not script.get("voiceover_text"):
        script["voiceover_text"] = " ".join(
            part for part in (script["hook"], script["description"], script["cta"]) if part
        )
    hashtags = script.get("suggested_hashtags") or []
    script["suggested_hashtags"] = [
        tag if str(tag).startswith("#") else f"#{tag}"
        for tag in hashtags
        if str(tag).strip()
    ]

    log.info(
        "marketing.script_generated",
        title=concept.get("game_title"),
        words=len(script["voiceover_text"].split()),
        hashtags=len(script["suggested_hashtags"]),
    )
    return script
