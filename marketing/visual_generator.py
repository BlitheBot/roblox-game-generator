"""
VisualGenerator (marketing step 2) — 5-8 portrait stills (1080x1920) for
the short-form video, via the env-configured image model on OpenRouter
(same call pattern as build/asset_generator.py):

    1 title card        game name in bold text over a genre background
    3-4 gameplay scenes action moments from the core loop
    1 "Play Now" end card

Image models render text unreliably, so card text is drawn with Pillow
over the generated backgrounds. Files land in
{archived_build}/marketing/slide_NN_*.png and are returned in video order.
"""
import base64
import io
import json
import os
import pathlib

import httpx
import structlog
from PIL import Image, ImageDraw, ImageFont

from intelligence.llm_client import OPENROUTER_BASE

log = structlog.get_logger()

IMAGE_MODEL = os.environ.get("IMAGE_MODEL", "google/gemini-2.5-flash-image")
PORTRAIT = (1080, 1920)
GAMEPLAY_SLIDES = 4  # 1 title + 4 scenes + 1 end card = 6 stills

TITLE_BG_PROMPT = (
    "Vertical 9:16 background art for a Roblox game title card, {genre} theme, "
    "{title} setting, vibrant cartoon 3D style, dramatic depth, no text, "
    "no characters in the center area, eye-catching colors for a young audience"
)
SCENE_PROMPT = (
    "Vertical 9:16 Roblox gameplay scene illustration, {title}, {genre} style, "
    "action moment: {moment}, cartoon 3D render, vibrant saturated colors, "
    "dynamic camera angle, no text overlays, no UI"
)
END_BG_PROMPT = (
    "Vertical 9:16 celebratory background for a 'play now' end card, {genre} "
    "theme, confetti and glow accents, cartoon 3D style, bright and inviting, "
    "no text, empty center area"
)

# Font candidates across the Windows dev box and the Linux VPS
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if pathlib.Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


async def _generate_image(prompt: str) -> Image.Image:
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
        raise RuntimeError(f"{IMAGE_MODEL} returned no images: {json.dumps(data)[:500]}")
    b64_payload = images[0]["image_url"]["url"].split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(b64_payload))).convert("RGB")


def _cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    src_w, src_h = image.size
    target_ratio = target_w / target_h
    src_ratio = src_w / src_h
    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        left = (src_w - new_w) // 2
        image = image.crop((left, 0, left + new_w, src_h))
    else:
        new_h = int(src_w / target_ratio)
        top = (src_h - new_h) // 2
        image = image.crop((0, top, src_w, top + new_h))
    return image.resize(size, Image.LANCZOS)


def _wrap_lines(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_card_text(
    image: Image.Image, text: str, subtitle: str | None = None
) -> Image.Image:
    """Bold white text with a black outline, vertically centered."""
    draw = ImageDraw.Draw(image)
    font = _load_font(120)
    max_width = image.width - 140
    lines = _wrap_lines(draw, text, font, max_width)

    line_height = 134
    block_height = len(lines) * line_height + (90 if subtitle else 0)
    y = (image.height - block_height) // 2
    for line in lines:
        x = (image.width - draw.textlength(line, font=font)) // 2
        draw.text(
            (x, y), line, font=font, fill="white",
            stroke_width=8, stroke_fill="black",
        )
        y += line_height

    if subtitle:
        sub_font = _load_font(56)
        x = (image.width - draw.textlength(subtitle, font=sub_font)) // 2
        draw.text(
            (x, y + 24), subtitle, font=sub_font, fill="white",
            stroke_width=5, stroke_fill="black",
        )
    return image


def _scene_moments(concept: dict) -> list[str]:
    """Concrete action moments to illustrate, from the concept's systems."""
    moments = [str(s) for s in concept.get("systems", []) if str(s).strip()]
    core_loop = concept.get("core_loop", "")
    if core_loop:
        moments.insert(0, core_loop)
    while len(moments) < GAMEPLAY_SLIDES:
        moments.append("an exciting moment from the core gameplay loop")
    return moments[:GAMEPLAY_SLIDES]


async def generate_visuals(concept: dict, marketing_dir: pathlib.Path) -> list[pathlib.Path]:
    """Generate all stills into marketing_dir; returns paths in video order
    (title card, scenes, end card)."""
    marketing_dir.mkdir(parents=True, exist_ok=True)
    title = concept.get("game_title", "Roblox Game")
    genre = concept.get("mechanic_tag", "simulator").replace("_", " ")
    paths: list[pathlib.Path] = []

    # Title card
    bg = await _generate_image(TITLE_BG_PROMPT.format(title=title, genre=genre))
    card = _draw_card_text(_cover_resize(bg, PORTRAIT), title, subtitle=f"NEW {genre.upper()} GAME")
    path = marketing_dir / "slide_01_title.png"
    card.save(path, "PNG")
    paths.append(path)

    # Gameplay scenes
    for index, moment in enumerate(_scene_moments(concept), start=1):
        scene = await _generate_image(
            SCENE_PROMPT.format(title=title, genre=genre, moment=moment[:200])
        )
        path = marketing_dir / f"slide_{index + 1:02d}_scene.png"
        _cover_resize(scene, PORTRAIT).save(path, "PNG")
        paths.append(path)

    # "Play Now" end card. The Roblox logo placeholder is text-only — using
    # the actual Roblox logo in generated marketing requires brand-license
    # review, so a styled "on ROBLOX" wordmark stands in.
    bg = await _generate_image(END_BG_PROMPT.format(genre=genre))
    card = _draw_card_text(_cover_resize(bg, PORTRAIT), "PLAY NOW", subtitle=f"{title} — on ROBLOX")
    path = marketing_dir / f"slide_{len(paths) + 1:02d}_endcard.png"
    card.save(path, "PNG")
    paths.append(path)

    log.info("marketing.visuals_generated", count=len(paths), dir=str(marketing_dir))
    return paths
