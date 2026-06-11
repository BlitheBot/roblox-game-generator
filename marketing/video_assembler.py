"""
VideoAssembler (marketing step 3) — stitches the generated stills and a
TTS voiceover into a single 1080x1920 30fps MP4 (max 58s) with:

  * slides 2-4s each, paced to cover the voiceover
  * hook text overlay (big bold white, black outline, centered, first 3s)
  * subtitles for the full voiceover (white, bottom third)

Voiceover: OpenAI TTS (tts-1, onyx) when OPENAI_API_KEY is set, else
gTTS (free, no key). Text overlays are rendered with Pillow rather than
MoviePy's TextClip so no ImageMagick/font setup is needed on the VPS.
"""
import asyncio
import os
import pathlib

import httpx
import structlog
from PIL import Image, ImageDraw

import numpy as np

from .visual_generator import PORTRAIT, _load_font, _wrap_lines

log = structlog.get_logger()

FPS = 30
MAX_SECONDS = 58
MIN_SLIDE_SECONDS = 2.0
MAX_SLIDE_SECONDS = 4.0
HOOK_SECONDS = 3.0
SUBTITLE_WORDS_PER_CHUNK = 7


# ── voiceover ────────────────────────────────────────────────


async def synthesize_voiceover(text: str, out_dir: pathlib.Path) -> pathlib.Path:
    """Write voiceover.mp3 via OpenAI TTS, falling back to gTTS."""
    out_path = out_dir / "voiceover.mp3"
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if api_key:
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": "tts-1", "voice": "onyx", "input": text},
                )
                resp.raise_for_status()
                out_path.write_bytes(resp.content)
            log.info("marketing.voiceover_openai", chars=len(text))
            return out_path
        except Exception as exc:
            log.warning("marketing.openai_tts_failed_falling_back", error=str(exc))

    # gTTS is sync — run off the event loop
    def _gtts() -> None:
        from gtts import gTTS

        gTTS(text=text, lang="en").save(str(out_path))

    await asyncio.to_thread(_gtts)
    log.info("marketing.voiceover_gtts", chars=len(text))
    return out_path


# ── overlay rendering (Pillow → RGBA arrays for MoviePy) ────


def _render_overlay(
    text: str,
    font_size: int,
    center_y_frac: float,
    max_width_frac: float = 0.86,
) -> np.ndarray:
    """Transparent 1080x1920 RGBA frame with outlined white text centered
    horizontally around the given vertical fraction."""
    canvas = Image.new("RGBA", PORTRAIT, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _load_font(font_size)
    max_width = int(PORTRAIT[0] * max_width_frac)
    lines = _wrap_lines(draw, text, font, max_width)
    line_height = int(font_size * 1.18)
    block_height = len(lines) * line_height
    y = int(PORTRAIT[1] * center_y_frac) - block_height // 2
    stroke = max(3, font_size // 14)
    for line in lines:
        x = (PORTRAIT[0] - draw.textlength(line, font=font)) // 2
        draw.text(
            (x, y), line, font=font, fill="white",
            stroke_width=stroke, stroke_fill="black",
        )
        y += line_height
    return np.array(canvas)


def _subtitle_chunks(voiceover_text: str) -> list[str]:
    words = voiceover_text.split()
    return [
        " ".join(words[i : i + SUBTITLE_WORDS_PER_CHUNK])
        for i in range(0, len(words), SUBTITLE_WORDS_PER_CHUNK)
    ]


# ── assembly ─────────────────────────────────────────────────


def _assemble_sync(
    image_paths: list[pathlib.Path],
    voiceover_path: pathlib.Path,
    hook: str,
    voiceover_text: str,
    out_path: pathlib.Path,
) -> pathlib.Path:
    from moviepy import (
        AudioFileClip,
        CompositeVideoClip,
        ImageClip,
        concatenate_videoclips,
    )

    audio = AudioFileClip(str(voiceover_path))
    total = min(max(audio.duration + 0.6, MIN_SLIDE_SECONDS * len(image_paths)), MAX_SECONDS)
    per_slide = min(MAX_SLIDE_SECONDS, max(MIN_SLIDE_SECONDS, total / len(image_paths)))
    total = min(per_slide * len(image_paths), MAX_SECONDS)

    slides = [
        ImageClip(str(p)).with_duration(per_slide) for p in image_paths
    ]
    base = concatenate_videoclips(slides, method="compose").with_duration(total)

    overlays = []

    # Hook — first 3 seconds, large and centered
    hook_frame = _render_overlay(hook, font_size=96, center_y_frac=0.42)
    overlays.append(
        ImageClip(hook_frame, transparent=True)
        .with_duration(min(HOOK_SECONDS, total))
        .with_start(0)
    )

    # Subtitles — bottom third, spread across the voiceover duration
    chunks = _subtitle_chunks(voiceover_text)
    if chunks:
        speech_span = min(audio.duration, total)
        chunk_duration = speech_span / len(chunks)
        for index, chunk in enumerate(chunks):
            frame = _render_overlay(chunk, font_size=58, center_y_frac=0.82)
            overlays.append(
                ImageClip(frame, transparent=True)
                .with_duration(chunk_duration)
                .with_start(index * chunk_duration)
            )

    video = CompositeVideoClip([base, *overlays], size=PORTRAIT).with_duration(total)
    video = video.with_audio(audio.subclipped(0, min(audio.duration, total)))
    video.write_videofile(
        str(out_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        logger=None,
    )
    video.close()
    audio.close()
    return out_path


async def assemble_video(
    image_paths: list[pathlib.Path],
    script: dict,
    marketing_dir: pathlib.Path,
) -> pathlib.Path:
    """Voiceover + assembly → {marketing_dir}/final_video.mp4."""
    voiceover_path = await synthesize_voiceover(
        script["voiceover_text"], marketing_dir
    )
    out_path = marketing_dir / "final_video.mp4"
    # MoviePy rendering is CPU-bound sync work — keep the loop responsive
    await asyncio.to_thread(
        _assemble_sync,
        image_paths,
        voiceover_path,
        script.get("hook", ""),
        script.get("voiceover_text", ""),
        out_path,
    )
    log.info("marketing.video_assembled", path=str(out_path))
    return out_path
