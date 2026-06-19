"""
SeasonalReskin (LiveOps step 4) — when a seasonal window is active or
opens within 14 days, dress the game up for the season:

  * title → "<emoji> <Original> — <Season> Edition" (Open Cloud PATCH)
  * thumbnail regenerated with a seasonal prompt + uploaded
  * description rewritten with seasonal keywords
  * one limited-time seasonal shop item injected into the concept

Originals are stored in seasonal_overrides with
revert_after = window end + 3 days; the orchestrator's daily 6am revert
job restores them. Skips entirely outside seasonal windows.
"""
import json
import pathlib
import uuid
from datetime import datetime, time, timedelta, timezone

import asyncpg
import httpx
import structlog

from build.asset_generator import AssetGenerator
from intelligence.llm_client import DEEPSEEK_V3, chat
from intelligence.seasonal_context import (
    SeasonalContext,
    season_window_end,
    upcoming_season,
)
from publish.open_cloud_publisher import (
    APIS_BASE,
    dry_run_enabled,
    load_genre_account,
    strip_markdown,
    upload_thumbnail,
)

log = structlog.get_logger()

PRESTAGE_DAYS = 14
REVERT_GRACE_DAYS = 3

SEASON_EMOJI = {
    "halloween": "🎃",
    "christmas": "🎄",
    "summer": "🌞",
    "back_to_school": "📚",
}

SEASONAL_THUMBNAIL_PROMPT = (
    "Roblox game thumbnail, {game_title}, {genre} style, {season} themed: "
    "{season_keywords}, vibrant cartoon 3D art, festive atmosphere, no text, "
    "eye-catching for a young audience"
)

SEASONAL_ITEM = {
    "halloween":      {"name": "Haunted {noun} (Limited)", "price": 6666, "type": "cosmetic"},
    "christmas":      {"name": "Festive {noun} (Limited)", "price": 5000, "type": "cosmetic"},
    "summer":         {"name": "Sunshine {noun} (Limited)", "price": 4000, "type": "cosmetic"},
    "back_to_school": {"name": "Scholar {noun} (Limited)", "price": 3000, "type": "cosmetic"},
}


async def maybe_reskin(
    pool: asyncpg.Pool,
    game: dict,
    concept: dict,
    build_thumbnail_dir: pathlib.Path,
) -> list[str] | None:
    """Apply a seasonal reskin when a window is active/near. Returns
    change lines, or None when no season applies or the game already has
    an active (un-reverted) override for this season."""
    season = upcoming_season(PRESTAGE_DAYS)
    if season is None:
        log.info("liveops.seasonal.no_window_near")
        return None

    game_id = uuid.UUID(game["game_id"])
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            """
            SELECT 1 FROM seasonal_overrides
            WHERE game_id = $1 AND season = $2 AND reverted = FALSE
            """,
            game_id,
            season.name,
        )
    if existing:
        log.info("liveops.seasonal.already_reskinned", game=game["game_title"])
        return None

    changes: list[str] = []
    emoji = SEASON_EMOJI.get(season.name, "✨")
    original_title = game["game_title"]
    seasonal_title = f"{emoji} {original_title} — {season.display_name} Edition"

    original_description = await _fetch_description(game)
    seasonal_description = await _seasonal_description(
        original_title, concept, season
    )

    # Push title + description via Open Cloud
    await _push_title_description(game, seasonal_title, seasonal_description)
    changes.append(f"title → {seasonal_title}")
    changes.append("description rewritten with seasonal keywords")

    # Seasonal thumbnail
    original_thumbnail = build_thumbnail_dir / "thumbnail.png"
    try:
        assets = AssetGenerator()
        prompt = SEASONAL_THUMBNAIL_PROMPT.format(
            game_title=original_title,
            genre=concept.get("mechanic_tag", "simulator").replace("_", " "),
            season=season.display_name,
            season_keywords=", ".join(season.keywords[:5]),
        )
        image = await assets._generate_image(prompt)
        seasonal_path = build_thumbnail_dir / "thumbnail_seasonal.png"
        assets._save_resized(image, seasonal_path, (1920, 1080))
        await upload_thumbnail(game["genre_account"], game["universe_id"], seasonal_path)
        changes.append("seasonal thumbnail uploaded")
    except Exception as exc:
        log.warning("liveops.seasonal.thumbnail_failed", error=str(exc))

    # Limited-time seasonal shop item (ships with the cycle's rebuild)
    template = SEASONAL_ITEM[season.name]
    noun = concept.get("monetization", {}).get("currency_name", "Trail")
    item = {
        "name": template["name"].format(noun=noun),
        "price": template["price"],
        "type": template["type"],
    }
    shop_items = concept.setdefault("monetization", {}).setdefault("shop_items", [])
    if not any(i.get("name") == item["name"] for i in shop_items):
        shop_items.append(item)
        changes.append(f"limited seasonal item: {item['name']}")

    # Store originals + scheduled revert (window end + 3 days, 06:00 UTC)
    revert_after = datetime.combine(
        season_window_end(season.name), time(6, 0), tzinfo=timezone.utc
    ) + timedelta(days=REVERT_GRACE_DAYS)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO seasonal_overrides
                (game_id, original_title, original_description,
                 original_thumbnail_url, season, revert_after)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            game_id,
            original_title,
            original_description,
            str(original_thumbnail) if original_thumbnail.exists() else None,
            season.name,
            revert_after,
        )

    log.info(
        "liveops.seasonal_reskin_applied",
        game=original_title,
        season=season.name,
        revert_after=revert_after.isoformat(),
    )
    return changes


async def revert_due_overrides(pool: asyncpg.Pool) -> list[str]:
    """Daily 6am job: restore title/description/thumbnail for overrides
    past revert_after. Returns the titles reverted (for Discord)."""
    reverted_titles: list[str] = []
    async with pool.acquire() as conn:
        due = await conn.fetch(
            """
            SELECT so.id, so.game_id, so.original_title, so.original_description,
                   so.original_thumbnail_url, so.season,
                   pg.genre_account, pg.universe_id
            FROM seasonal_overrides so
            JOIN published_games pg ON pg.id = so.game_id
            WHERE so.revert_after < NOW() AND so.reverted = FALSE
            """
        )
    for row in due:
        try:
            game = {
                "genre_account": row["genre_account"],
                "universe_id": row["universe_id"],
            }
            await _push_title_description(
                game, row["original_title"], row["original_description"] or ""
            )
            thumb = row["original_thumbnail_url"]
            if thumb and pathlib.Path(thumb).exists():
                await upload_thumbnail(row["genre_account"], row["universe_id"], pathlib.Path(thumb))
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE seasonal_overrides SET reverted = TRUE WHERE id = $1",
                    row["id"],
                )
                await conn.execute(
                    "UPDATE published_games SET game_title = $2 WHERE id = $1",
                    row["game_id"],
                    row["original_title"],
                )
            reverted_titles.append(f"{row['original_title']} ({row['season']})")
            log.info("liveops.seasonal_reverted", game=row["original_title"])
        except Exception as exc:
            log.error(
                "liveops.seasonal_revert_failed",
                game=row["original_title"],
                error=str(exc),
            )
    return reverted_titles


# ── helpers ─────────────────────────────────────────────────


async def _fetch_description(game: dict) -> str:
    """Current live description (for the revert), best effort."""
    if dry_run_enabled():
        return ""
    try:
        account = load_genre_account(game["genre_account"])
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{APIS_BASE}/cloud/v2/universes/{game['universe_id']}",
                headers={"x-api-key": account.api_key},
            )
            resp.raise_for_status()
            return resp.json().get("description", "")
    except Exception as exc:
        log.warning("liveops.seasonal.description_fetch_failed", error=str(exc))
        return ""


async def _seasonal_description(
    title: str, concept: dict, season: SeasonalContext
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                f"Rewrite this Roblox game description for the "
                f"{season.display_name} season. Weave in seasonal keywords "
                f"({', '.join(season.keywords[:6])}) naturally and mention the "
                "limited-time seasonal event. Max 1000 characters, "
                "family-friendly, punchy. Output description text only."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Game: {title}\nCore loop: {concept.get('core_loop', '')}"
            ),
        },
    ]
    description = await chat(DEEPSEEK_V3, messages, temperature=0.7, max_tokens=600)
    return description.strip().strip('"')[:1000]


async def _push_title_description(game: dict, title: str, description: str) -> None:
    if dry_run_enabled():
        log.info("liveops.seasonal.dry_run_push_skipped")
        return
    account = load_genre_account(game["genre_account"])
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.patch(
            f"{APIS_BASE}/cloud/v2/universes/{game['universe_id']}",
            params={"updateMask": "displayName,description"},
            headers={"x-api-key": account.api_key, "Content-Type": "application/json"},
            json={
                "displayName": strip_markdown(title),
                "description": strip_markdown(description),
            },
        )
        resp.raise_for_status()
