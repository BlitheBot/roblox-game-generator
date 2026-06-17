"""
AssetGenerator (spec 4.5) — generates the game thumbnail (1920x1080),
icon (512x512), and SEO-optimized description.

Images: image-output model via OpenRouter chat completions (the image
comes back as a base64 data URL on the message). The spec named FLUX,
but black-forest-labs/flux-1.1-pro was delisted from OpenRouter —
default is now gemini-2.5-flash-image, overridable via IMAGE_MODEL.
Description: DeepSeek V3, max 1000 chars.
"""
import base64
import io
import json
import os
import pathlib

import httpx
import structlog
from PIL import Image

from intelligence.llm_client import DEEPSEEK_V3, OPENROUTER_BASE, chat

log = structlog.get_logger()

IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-2.5-flash-image")

# Genre-specific thumbnail prompts — tuned to produce compelling, scroll-
# stopping store art. Keyed by mechanic_tag; falls back to GENERIC.
THUMBNAIL_PROMPTS = {
    "idle_tycoon": (
        "Roblox game thumbnail, {game_title}, colorful cartoon tycoon factory, "
        "coins and money flying everywhere, happy cartoon characters working machines, "
        "bright vibrant colors, dynamic diagonal composition, professional game art style, "
        "no text, high contrast, exciting and energetic"
    ),
    "pet_collect": (
        "Roblox game thumbnail, {game_title}, cute cartoon pets floating on magical island, "
        "rainbow colors, sparkles and stars everywhere, glowing egg in center, "
        "adorable character expressions, pastel color palette, professional Roblox art style, "
        "no text, magical and cute atmosphere"
    ),
    "survival_horror": (
        "Roblox game thumbnail, {game_title}, dark scary abandoned building at night, "
        "cartoon character running from monster shadow, dramatic red lighting, "
        "fog and atmosphere, intense horror mood, professional Roblox game art, "
        "no text, dark color palette with red accents"
    ),
    "incremental_sim": (
        "Roblox game thumbnail, {game_title}, clean modern facility with glowing progress bars, "
        "cartoon character surrounded by floating numbers and coins, "
        "satisfying progression visual, blue and white color scheme, "
        "professional clean art style, no text, modern and satisfying"
    ),
}

GENERIC_THUMBNAIL_PROMPT = (
    "Roblox game thumbnail, {game_title}, {genre} style, vibrant colors, "
    "cartoon 3D art style, dynamic action scene, no text overlays, "
    "high contrast, eye-catching for young audience"
)

# Appended for the higher-effort variant used on breakout games / A-B testing
# (spec 5.2, 6.2) — pushes the same genre scene toward cinematic close-ups.
THUMBNAIL_ALT_SUFFIX = (
    ", dramatic cinematic lighting, expressive character close-up, "
    "maximized click-through, premium splash-art quality"
)


class AssetGenerator:
    """Generates thumbnail, icon, and description for a game build."""

    async def generate_all(
        self,
        concept: dict,
        build_dir: pathlib.Path,
        meta_keywords: list[str] | None = None,
        alt_prompt: bool = False,
    ) -> dict:
        """
        Writes thumbnail.png (1920x1080) and icon.png (512x512) into
        build_dir and returns {"thumbnail": path, "icon": path, "description": str}.
        """
        game_title = concept.get("game_title", "Roblox Game")
        mechanic_tag = concept.get("mechanic_tag", "simulator")
        genre = mechanic_tag.replace("_", " ")

        template = THUMBNAIL_PROMPTS.get(mechanic_tag, GENERIC_THUMBNAIL_PROMPT)
        prompt = template.format(game_title=game_title, genre=genre)
        if alt_prompt:
            prompt += THUMBNAIL_ALT_SUFFIX

        image = await self._generate_image(prompt)

        thumbnail_path = build_dir / "thumbnail.png"
        icon_path = build_dir / "icon.png"
        self._save_resized(image, thumbnail_path, (1920, 1080))
        self._save_resized(image, icon_path, (512, 512))

        description = await self._write_description(concept, meta_keywords or [])
        (build_dir / "description.txt").write_text(description, encoding="utf-8")

        log.info(
            "asset_generator.complete",
            game_title=game_title,
            thumbnail=str(thumbnail_path),
            description_len=len(description),
        )
        return {
            "thumbnail": thumbnail_path,
            "icon": icon_path,
            "description": description,
        }

    async def _generate_image(self, prompt: str) -> Image.Image:
        headers = {
            "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}",
            "Content-Type": "application/json",
        }
        body = {
            "model": IMAGE_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "modalities": ["image", "text"],
        }
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE}/chat/completions", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()

        message = data["choices"][0]["message"]
        images = message.get("images", [])
        if not images:
            raise RuntimeError(
                f"{IMAGE_MODEL} returned no images: {json.dumps(data)[:500]}"
            )
        data_url = images[0]["image_url"]["url"]
        # data URL format: data:image/png;base64,<payload>
        b64_payload = data_url.split(",", 1)[1]
        raw = base64.b64decode(b64_payload)
        return Image.open(io.BytesIO(raw)).convert("RGB")

    @staticmethod
    def _save_resized(
        image: Image.Image, path: pathlib.Path, size: tuple[int, int]
    ) -> None:
        target_w, target_h = size
        # Cover-crop to target aspect ratio, then resize
        src_w, src_h = image.size
        target_ratio = target_w / target_h
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            cropped = image.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            cropped = image.crop((0, top, src_w, top + new_h))
        cropped.resize(size, Image.LANCZOS).save(path, "PNG")

    async def _write_description(
        self, concept: dict, meta_keywords: list[str]
    ) -> str:
        messages = [
            {
                "role": "system",
                "content": (
                    "Write a compelling Roblox game description that sells the game. "
                    "Structure exactly like this:\n"
                    "1. First line: a hook that creates curiosity or excitement (one sentence)\n"
                    "2. Second line: blank\n"
                    "3. 3-4 bullet points using emoji, each describing a key feature/benefit\n"
                    "4. Blank line\n"
                    "5. A call to action sentence\n"
                    "6. Relevant hashtag-style keywords at the very end\n\n"
                    "Hard limit: 1000 characters total. Family-friendly tone. "
                    "Use action verbs. Make it feel exciting, not corporate. "
                    "Include 2-3 of the provided trending keywords naturally. "
                    "Output the description text only — no markdown headers, no quotes."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Game: {concept.get('game_title')}\n"
                    f"Tagline: {concept.get('tagline', '')}\n"
                    f"Core loop: {concept.get('core_loop', '')}\n"
                    f"Systems: {concept.get('systems', [])}\n"
                    f"Key monetization hooks: {concept.get('monetization', {}).get('game_passes', [])}\n"
                    f"Trending keywords to weave in: {meta_keywords[:10]}\n\n"
                    f"Example structure:\n"
                    f"Build the ultimate empire from nothing! 🏗️\n\n"
                    f"⚡ Collect resources and upgrade your factory\n"
                    f"💰 Earn coins faster with powerful boosts\n"
                    f"🏆 Climb the leaderboard and prestige for rewards\n"
                    f"🎁 Daily rewards keep getting better\n\n"
                    f"Start your empire today — the grind never felt this good!\n"
                    f"#tycoon #idle #simulator"
                ),
            },
        ]
        description = await chat(DEEPSEEK_V3, messages, temperature=0.75, max_tokens=600)
        description = description.strip().strip('"')
        return description[:1000]
