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
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import structlog

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from monitor.discord_reporter import DiscordReporter

log = structlog.get_logger()

APIS_BASE = "https://apis.roblox.com"
PUBLISH_COOLDOWN_HOURS = 4

_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_HEADER_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_MD_QUOTE_RE = re.compile(r"(?m)^\s{0,3}>\s?")


def strip_markdown(text: str | None) -> str:
    """Strip markdown so Roblox metadata is clean plain text. The `**` emphasis
    markers in particular trip Roblox's WAF (HTTP 403 code 9009) on the
    universe displayName/description PATCH — and Roblox renders descriptions as
    plain text anyway, so markdown only shows up as literal asterisks."""
    if not text:
        return text or ""
    text = _MD_LINK_RE.sub(r"\1", text)   # [label](url) -> label
    text = _MD_HEADER_RE.sub("", text)    # # headers
    text = _MD_QUOTE_RE.sub("", text)     # > blockquotes
    text = text.replace("*", "")          # **bold** / *italic*  (the WAF trigger)
    text = text.replace("`", "")          # `code`
    text = re.sub(r"_{2,}", "", text)     # __bold__
    return text


async def _set_game_thumbnail(
    genre: str, universe_id: int, image_bytes: bytes
) -> tuple[bool | None, str]:
    """Upload a game thumbnail. Returns (result, detail): True = uploaded,
    False = failed, None = skipped (not possible).

    Open Cloud API keys CANNOT set game thumbnails — the only working endpoint
    is the legacy publish.roblox.com one, which needs a .ROBLOSECURITY cookie +
    XSRF token (the old /universes/v1/{id}/thumbnails path never existed → 404).
    If ROBLOX_COOKIE_{GENRE} (or the global ROBLOX_THUMBNAIL_COOKIE) is set we
    use it; otherwise we skip without error and the game keeps its default
    thumbnail."""
    cookie = (
        os.environ.get(f"ROBLOX_COOKIE_{genre.upper()}")
        or os.environ.get("ROBLOX_THUMBNAIL_COOKIE")
        or ""
    ).strip()
    if not cookie:
        return None, (
            "no account cookie configured — Open Cloud API keys cannot upload "
            f"thumbnails; set ROBLOX_COOKIE_{genre.upper()} to enable"
        )
    url = f"https://publish.roblox.com/v1/games/{universe_id}/thumbnail/image"
    files = {"Files": ("thumbnail.png", image_bytes, "image/png")}
    async with httpx.AsyncClient(
        timeout=120, cookies={".ROBLOSECURITY": cookie}
    ) as client:
        resp = await client.post(url, files=files)
        # Legacy endpoints answer the first call with 403 + an XSRF token to echo
        if resp.status_code == 403 and resp.headers.get("x-csrf-token"):
            resp = await client.post(
                url,
                headers={"X-CSRF-TOKEN": resp.headers["x-csrf-token"]},
                files=files,
            )
    if resp.status_code in (200, 201):
        return True, "ok"
    return False, f"HTTP {resp.status_code}: {resp.text[:200]}"


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
    pool_exhausted: bool = False


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


async def free_place_count(pool: asyncpg.Pool, genre: str) -> tuple[int, int]:
    """Bug 2: returns (free_slots, total_slots) for a genre account — the
    env-configured (universe, place) slots minus those already hosting a game.
    Used for proactive low-slot warnings and pool-recovery detection."""
    slots = genre_slots(genre)
    if not slots:
        return (0, 0)
    async with pool.acquire() as conn:
        used = await conn.fetch(
            "SELECT DISTINCT place_id FROM published_games WHERE genre_account = $1",
            genre,
        )
    occupied = {row["place_id"] for row in used}
    free = sum(1 for _universe_id, place_id in slots if place_id not in occupied)
    return (free, len(slots))


async def upload_thumbnail(
    genre: str, universe_id: int, thumbnail_path: pathlib.Path
) -> None:
    """Standalone thumbnail upload to a specific game's universe — used by
    breakout regen (spec 6.2), low-CTR refresh (spec 5.2), and seasonal
    reskins, outside the full publish flow."""
    if dry_run_enabled():
        log.info("publisher.dry_run_thumbnail_skipped", genre=genre)
        return
    result, detail = await _set_game_thumbnail(
        genre, universe_id, thumbnail_path.read_bytes()
    )
    if result is True:
        log.info("publisher.thumbnail_refreshed", genre=genre, universe_id=universe_id)
    elif result is None:
        log.info("publisher.thumbnail_skipped", genre=genre, reason=detail)
    else:
        log.warning("publisher.thumbnail_refresh_failed", genre=genre, detail=detail)


class OpenCloudPublisher:
    def __init__(
        self, pool: asyncpg.Pool, reporter: "DiscordReporter | None" = None
    ) -> None:
        self._pool = pool
        self._reporter = reporter

    async def _alert(self, message: str) -> None:
        """Bug 1: publish-step failures (title/thumbnail) must never fail
        silently. Sends a Discord alert via the wired reporter, falling back to
        a pool-backed reporter so alerts fire regardless of how the publisher
        was constructed. Never raises."""
        try:
            reporter = self._reporter
            if reporter is None:
                from monitor.discord_reporter import DiscordReporter

                reporter = DiscordReporter(self._pool)
            await reporter.alert(message)
        except Exception as exc:
            log.error("publisher.alert_failed", error=str(exc))

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
            # Bug 2: pool exhaustion is handled specially upstream (one alert,
            # pause the account, leave the row queued) — flag it as such.
            return PublishResult(
                success=False,
                pool_exhausted=True,
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
            log.info(
                "publisher.place_upload.start",
                genre=genre,
                universe_id=universe_id,
                place_id=place_id,
                title=game_title,
                rbxl_bytes=rbxl_path.stat().st_size if rbxl_path.exists() else 0,
            )
            resp = await client.post(
                f"{APIS_BASE}/universes/v1/{universe_id}"
                f"/places/{place_id}/versions",
                params={"versionType": "Published"},
                headers={**headers, "Content-Type": "application/octet-stream"},
                content=rbxl_path.read_bytes(),
            )
            if resp.status_code != 200:
                log.error(
                    "publisher.place_upload.failed",
                    genre=genre,
                    universe_id=universe_id,
                    place_id=place_id,
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                return PublishResult(
                    success=False,
                    error=f"place upload failed ({resp.status_code}): {resp.text[:500]}",
                )
            log.info(
                "publisher.place_upload.ok",
                genre=genre,
                universe_id=universe_id,
                status=resp.status_code,
            )

            # Step 2: set name + description (Open Cloud v2). A failure here
            # means the game ships with the wrong/placeholder title — alert
            # loudly, never swallow it (Bug 1).
            log.info(
                "publisher.metadata.start",
                genre=genre,
                universe_id=universe_id,
                title=game_title,
                description_len=len(description or ""),
            )
            try:
                resp = await client.patch(
                    f"{APIS_BASE}/cloud/v2/universes/{universe_id}",
                    params={"updateMask": "displayName,description"},
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "displayName": strip_markdown(game_title),
                        "description": strip_markdown(description),
                    },
                )
            except Exception as exc:
                log.error(
                    "publisher.metadata.exception",
                    genre=genre,
                    universe_id=universe_id,
                    error=str(exc),
                )
                await self._alert(
                    f"⚠️ Title/description update ERRORED for **{game_title}** "
                    f"[{genre}] (universe {universe_id}): {str(exc)[:400]}. The "
                    f"game may be live with the wrong title — fix and re-run."
                )
            else:
                if resp.status_code not in (200, 201):
                    log.error(
                        "publisher.metadata.failed",
                        genre=genre,
                        universe_id=universe_id,
                        status=resp.status_code,
                        body=resp.text[:500],
                    )
                    await self._alert(
                        f"⚠️ Title/description update FAILED for **{game_title}** "
                        f"[{genre}] (universe {universe_id}) — HTTP "
                        f"{resp.status_code}: {resp.text[:400]}. The game is live "
                        f"with the wrong title — fix and re-run."
                    )
                else:
                    log.info(
                        "publisher.metadata.ok",
                        genre=genre,
                        universe_id=universe_id,
                        status=resp.status_code,
                        title=game_title,
                    )

            # Step 3: upload thumbnail. A failure here means the game ships
            # with no/placeholder thumbnail (kills CTR) — alert loudly (Bug 1).
            # TODO: Open Cloud thumbnail upload is still the v1 endpoint per
            # spec 5.1; if Roblox moves it to /cloud/v2, update here.
            thumb_exists = thumbnail_path.exists()
            log.info(
                "publisher.thumbnail.start",
                genre=genre,
                universe_id=universe_id,
                thumbnail_path=str(thumbnail_path),
                thumbnail_bytes=thumbnail_path.stat().st_size if thumb_exists else 0,
            )
            if not thumb_exists:
                log.error(
                    "publisher.thumbnail.missing_file",
                    genre=genre,
                    universe_id=universe_id,
                    thumbnail_path=str(thumbnail_path),
                )
                await self._alert(
                    f"⚠️ Thumbnail MISSING for **{game_title}** [{genre}] "
                    f"(universe {universe_id}) — file not found at "
                    f"{thumbnail_path}. Published with no custom thumbnail."
                )
            else:
                result, detail = await _set_game_thumbnail(
                    genre, universe_id, thumbnail_path.read_bytes()
                )
                if result is True:
                    log.info(
                        "publisher.thumbnail.ok", genre=genre, universe_id=universe_id
                    )
                elif result is None:
                    # Open Cloud x-api-key cannot set thumbnails — expected, not
                    # a failure. Don't alert; the game keeps its default image.
                    log.info(
                        "publisher.thumbnail.skipped",
                        genre=genre,
                        universe_id=universe_id,
                        reason=detail,
                    )
                else:
                    log.error(
                        "publisher.thumbnail.failed",
                        genre=genre,
                        universe_id=universe_id,
                        detail=detail,
                    )
                    await self._alert(
                        f"⚠️ Thumbnail upload FAILED for **{game_title}** "
                        f"[{genre}] (universe {universe_id}): {detail}. Published "
                        f"with no custom thumbnail."
                    )

            # Step 4: set place public
            log.info(
                "publisher.visibility.start", genre=genre, universe_id=universe_id
            )
            resp = await client.patch(
                f"{APIS_BASE}/cloud/v2/universes/{universe_id}",
                params={"updateMask": "visibility"},
                headers={**headers, "Content-Type": "application/json"},
                json={"visibility": "PUBLIC"},
            )
            if resp.status_code not in (200, 201):
                log.error(
                    "publisher.visibility.failed",
                    genre=genre,
                    universe_id=universe_id,
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                await self._alert(
                    f"⚠️ Visibility (set-public) FAILED for **{game_title}** "
                    f"[{genre}] (universe {universe_id}) — HTTP "
                    f"{resp.status_code}: {resp.text[:400]}. The game may not be "
                    f"publicly visible — check the universe."
                )
            else:
                log.info(
                    "publisher.visibility.ok",
                    genre=genre,
                    universe_id=universe_id,
                    status=resp.status_code,
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

    async def update_title(self, genre: str, universe_id: int, new_title: str) -> bool:
        """Improvement 5: set a live game's display name via Open Cloud v2.
        Used by TitleABTester to rotate and lock in title variants."""
        if dry_run_enabled():
            log.info("publisher.dry_run_title_skipped", genre=genre)
            return False
        try:
            account = load_genre_account(genre)
        except RuntimeError as exc:
            log.warning("publisher.update_title_no_account", genre=genre, error=str(exc))
            return False
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.patch(
                f"{APIS_BASE}/cloud/v2/universes/{universe_id}",
                params={"updateMask": "displayName"},
                headers={"x-api-key": account.api_key, "Content-Type": "application/json"},
                json={"displayName": new_title},
            )
        if resp.status_code not in (200, 201):
            log.warning(
                "publisher.update_title_failed",
                genre=genre,
                status=resp.status_code,
                body=resp.text[:300],
            )
            return False
        log.info("publisher.title_updated", genre=genre, universe_id=universe_id, title=new_title)
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
