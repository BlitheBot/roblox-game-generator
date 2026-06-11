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

THUMBNAIL_PROMPT = (
    "Roblox game thumbnail, {game_title}, {genre} style, vibrant colors, "
    "cartoon 3D art style, dynamic action scene, no text overlays, "
    "high contrast, eye-catching for young audience"
)

# Higher-effort variant used for breakout games and A/B testing (spec 5.2, 6.2)
THUMBNAIL_PROMPT_ALT = (
    "Roblox game thumbnail, {game_title}, {genre} theme, dramatic lighting, "
    "cinematic composition, cartoon 3D render, expressive character close-up, "
    "saturated colors, no text, designed to maximize click-through for kids"
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
        genre = concept.get("mechanic_tag", "simulator").replace("_", " ")

        template = THUMBNAIL_PROMPT_ALT if alt_prompt else THUMBNAIL_PROMPT
        prompt = template.format(game_title=game_title, genre=genre)

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
                    "Write an SEO-optimized Roblox game description. Hard limit: 1000 "
                    "characters. Include genre keywords, action verbs, and the provided "
                    "trending terms naturally. Family-friendly tone, short punchy "
                    "sentences, 2-4 relevant emoji max. Output the description text only "
                    "— no headers, no quotes."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Game: {concept.get('game_title')}\n"
                    f"Tagline: {concept.get('tagline', '')}\n"
                    f"Core loop: {concept.get('core_loop', '')}\n"
                    f"Systems: {concept.get('systems', [])}\n"
                    f"Trending keywords to weave in: {meta_keywords[:10]}"
                ),
            },
        ]
        description = await chat(DEEPSEEK_V3, messages, temperature=0.7, max_tokens=600)
        description = description.strip().strip('"')
        return description[:1000]
