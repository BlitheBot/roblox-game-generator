"""
OpenCloudPublisher (spec 5.1) — publishes a validated build to Roblox
via the Open Cloud API.

Steps:
1. Upload .rbxl to the genre account's place (versions endpoint)
2. Set game name + description (Open Cloud v2 universe PATCH)
3. Upload thumbnail
4. Set place public
5. Insert published_games row

Rate limit: max 1 publish per genre account per 4 hours (checked
against published_games.published_at).
"""
import os
import pathlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import structlog

log = structlog.get_logger()

APIS_BASE = "https://apis.roblox.com"
PUBLISH_COOLDOWN_HOURS = 4


def dry_run_enabled() -> bool:
    """Spec Phase 4 step 2: DRY_RUN=true builds everything but never
    touches live Roblox universes."""
    return os.environ.get("DRY_RUN", "").strip().lower() in ("true", "1", "yes")


@dataclass
class GenreAccount:
    genre: str
    api_key: str
    universe_id: int


@dataclass
class PublishResult:
    success: bool
    game_id: str | None = None
    universe_id: int | None = None
    place_id: int | None = None
    error: str | None = None
    rate_limited: bool = False


def load_genre_account(genre: str) -> GenreAccount:
    """Reads ROBLOX_API_KEY_{GENRE} / UNIVERSE_ID from env."""
    suffix = genre.upper()
    try:
        return GenreAccount(
            genre=genre,
            api_key=os.environ[f"ROBLOX_API_KEY_{suffix}"],
            universe_id=int(os.environ[f"ROBLOX_UNIVERSE_ID_{suffix}"]),
        )
    except KeyError as exc:
        raise RuntimeError(
            f"genre account '{genre}' not configured — missing env var {exc}"
        ) from exc


def genre_slots(genre: str) -> list[tuple[int, int]]:
    """Publishing slots for a genre account as (universe_id, place_id) pairs.
    Each Roblox game is its own universe with its own place, so a slot is a
    matched pair — not several places under one shared universe.

    Canonical form: ROBLOX_SLOTS_{GENRE} = "universe:place,universe:place,...".
    Backward-compatible fallback for single-universe accounts: pair the one
    ROBLOX_UNIVERSE_ID_{GENRE} with each id in ROBLOX_PLACE_IDS_{GENRE}, or
    with ROBLOX_PLACE_ID_{GENRE}."""
    suffix = genre.upper()
    slots_raw = os.environ.get(f"ROBLOX_SLOTS_{suffix}", "").strip()
    if slots_raw:
        slots: list[tuple[int, int]] = []
        for pair in slots_raw.split(","):
            pair = pair.strip()
            if not pair:
                continue
            universe_str, _, place_str = pair.partition(":")
            slots.append((int(universe_str.strip()), int(place_str.strip())))
        return slots
    uni = os.environ.get(f"ROBLOX_UNIVERSE_ID_{suffix}", "").strip()
    if not uni:
        return []
    universe_id = int(uni)
    multi = os.environ.get(f"ROBLOX_PLACE_IDS_{suffix}", "").strip()
    if multi:
        return [(universe_id, int(p.strip())) for p in multi.split(",") if p.strip()]
    single = os.environ.get(f"ROBLOX_PLACE_ID_{suffix}", "").strip()
    return [(universe_id, int(single))] if single else []


async def upload_thumbnail(
    genre: str, universe_id: int, thumbnail_path: pathlib.Path
) -> None:
    """Standalone thumbnail upload to a specific game's universe — used by
    breakout regen (spec 6.2), low-CTR refresh (spec 5.2), and seasonal
    reskins, outside the full publish flow."""
    if dry_run_enabled():
        log.info("publisher.dry_run_thumbnail_skipped", genre=genre)
        return
    account = load_genre_account(genre)
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{APIS_BASE}/universes/v1/{universe_id}/thumbnails",
            headers={"x-api-key": account.api_key},
            files={"file": ("thumbnail.png", thumbnail_path.read_bytes(), "image/png")},
        )
        resp.raise_for_status()
    log.info("publisher.thumbnail_refreshed", genre=genre, universe_id=universe_id)


class OpenCloudPublisher:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def publish(
        self,
        concept_id: str,
        rbxl_path: pathlib.Path,
        thumbnail_path: pathlib.Path,
        game_title: str,
        description: str,
        genre: str,
    ) -> PublishResult:
        # Defense in depth — ApprovalGate already short-circuits dry runs
        if dry_run_enabled():
            return PublishResult(
                success=False, error="DRY_RUN is enabled — publish blocked"
            )

        # Account paused/banned check (spec 16/19)
        async with self._pool.acquire() as conn:
            account_status = await conn.fetchval(
                "SELECT status FROM genre_accounts WHERE genre = $1", genre
            )
        if account_status in ("paused", "banned"):
            return PublishResult(
                success=False,
                error=f"genre account '{genre}' is {account_status} — publishing suspended",
            )

        if await self._is_rate_limited(genre):
            return PublishResult(
                success=False,
                rate_limited=True,
                error=f"genre '{genre}' published within last {PUBLISH_COOLDOWN_HOURS}h",
            )

        # Spec 13: each game gets its own universe+place slot — never
        # overwrite a live one
        slot = await self._select_free_slot(genre)
        if slot is None:
            return PublishResult(
                success=False,
                error=(
                    f"no free slot on genre account '{genre}' — every "
                    f"universe:place pair already hosts a game. Create a new "
                    f"experience and add its pair to ROBLOX_SLOTS_{genre.upper()}."
                ),
            )
        universe_id, place_id = slot

        # Missing/misconfigured genre credentials must surface as a normal
        # failed PublishResult (which the ApprovalGate alerts on) rather than
        # raising — a raise here is swallowed silently by the queue processor.
        try:
            account = load_genre_account(genre)
        except RuntimeError as exc:
            return PublishResult(success=False, error=str(exc))
        headers = {"x-api-key": account.api_key}

        async with httpx.AsyncClient(timeout=300) as client:
            # Step 1: upload place version
            resp = await client.post(
                f"{APIS_BASE}/universes/v1/{universe_id}"
                f"/places/{place_id}/versions",
                params={"versionType": "Published"},
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=rbxl_path.read_bytes(),
            )
            if resp.status_code != 200:
                return PublishResult(
                    success=False,
                    error=f"place upload failed ({resp.status_code}): {resp.text[:500]}",
                )

            # Step 2: set name + description (Open Cloud v2)
            resp = await client.patch(
                f"{APIS_BASE}/cloud/v2/universes/{universe_id}",
                params={"updateMask": "displayName,description"},
                headers={**headers, "Content-Type": "application/json"},
                json={"displayName": game_title, "description": description},
            )
            if resp.status_code not in (200, 201):
                log.warning(
                    "publisher.metadata_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                )

            # Step 3: upload thumbnail
            # TODO: Open Cloud thumbnail upload is still the v1 endpoint per
            # spec 5.1; if Roblox moves it to /cloud/v2, update here.
            resp = await client.post(
                f"{APIS_BASE}/universes/v1/{universe_id}/thumbnails",
                headers=headers,
                files={"file": ("thumbnail.png", thumbnail_path.read_bytes(), "image/png")},
            )
            if resp.status_code not in (200, 201):
                log.warning(
                    "publisher.thumbnail_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                )

            # Step 4: set place public
            resp = await client.patch(
                f"{APIS_BASE}/cloud/v2/universes/{universe_id}",
                params={"updateMask": "visibility"},
                headers={**headers, "Content-Type": "application/json"},
                json={"visibility": "PUBLIC"},
            )
            if resp.status_code not in (200, 201):
                log.warning(
                    "publisher.visibility_failed",
                    status=resp.status_code,
                    body=resp.text[:300],
                )

        # Step 5: record in published_games
        game_id = str(uuid.uuid4())
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO published_games
                    (id, concept_id, universe_id, place_id, genre_account,
                     published_at, game_title, status, last_description_refresh)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 'live', NOW())
                """,
                uuid.UUID(game_id),
                uuid.UUID(concept_id),
                universe_id,
                place_id,
                genre,
                datetime.now(timezone.utc),
                game_title,
            )
            await conn.execute(
                "UPDATE concept_queue SET status = 'published' WHERE id = $1",
                uuid.UUID(concept_id),
            )
            await conn.execute(
                """
                INSERT INTO genre_accounts (genre, account_name, status, places_used)
                VALUES ($1, $2, 'active', 1)
                ON CONFLICT (genre) DO UPDATE
                    SET places_used = genre_accounts.places_used + 1
                """,
                genre,
                f"Studio{genre.capitalize()}_",
            )

        log.info(
            "publisher.published",
            game_id=game_id,
            title=game_title,
            genre=genre,
            universe_id=universe_id,
        )
        return PublishResult(
            success=True,
            game_id=game_id,
            universe_id=universe_id,
            place_id=place_id,
        )

    async def _select_free_slot(self, genre: str) -> tuple[int, int] | None:
        """First (universe_id, place_id) slot whose place hosts no published
        game, else None."""
        slots = genre_slots(genre)
        async with self._pool.acquire() as conn:
            used = await conn.fetch(
                "SELECT DISTINCT place_id FROM published_games WHERE genre_account = $1",
                genre,
            )
        occupied = {row["place_id"] for row in used}
        for universe_id, place_id in slots:
            if place_id not in occupied:
                return universe_id, place_id
        return None

    async def publish_update(
        self, genre: str, universe_id: int, place_id: int, rbxl_path: pathlib.Path
    ) -> bool:
        """Spec 14: push a new place version to an already-live game.
        Targets the game's own universe+place — no new published_games row."""
        if dry_run_enabled():
            log.info("publisher.dry_run_update_skipped", genre=genre)
            return False
        account = load_genre_account(genre)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{APIS_BASE}/universes/v1/{universe_id}"
                f"/places/{place_id}/versions",
                params={"versionType": "Published"},
                headers={
                    "x-api-key": account.api_key,
                    "Content-Type": "application/octet-stream",
                },
                content=rbxl_path.read_bytes(),
            )
        if resp.status_code != 200:
            log.warning(
                "publisher.update_failed",
                genre=genre,
                status=resp.status_code,
                body=resp.text[:300],
            )
            return False
        log.info("publisher.update_published", genre=genre)
        return True

    async def _is_rate_limited(self, genre: str) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=PUBLISH_COOLDOWN_HOURS)
        async with self._pool.acquire() as conn:
            recent = await conn.fetchval(
                """
                SELECT COUNT(*) FROM published_games
                WHERE genre_account = $1 AND published_at > $2
                """,
                genre,
                cutoff,
            )
        return (recent or 0) > 0
