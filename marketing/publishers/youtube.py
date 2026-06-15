"""
YouTube publisher (marketing step 4) — uploads the short via the
YouTube Data API v3 resumable upload.

Auth: OAuth2 refresh-token flow. Env vars:
    YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN
(one-time refresh-token generation steps are in DEPLOY.md).

Title:    [Game Title] — New Roblox Game {year} #roblox #{genre}
Category: Gaming (20), Privacy: Public
Thumbnail: the game's existing 1920x1080 AssetGenerator thumbnail.
"""
import os
import pathlib
from datetime import datetime, timezone

import httpx
import structlog

log = structlog.get_logger()

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
THUMBNAIL_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"
GAMING_CATEGORY_ID = "20"


def configured() -> bool:
    return all(
        os.environ.get(v)
        for v in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    )


async def _access_token(client: httpx.AsyncClient) -> str:
    resp = await client.post(
        TOKEN_URL,
        data={
            "client_id": os.environ["YOUTUBE_CLIENT_ID"],
            "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def publish(video_path: pathlib.Path, metadata: dict) -> str:
    """Upload and return the watch URL. metadata keys:
    game_title, genre, description, hashtags (list), tags (list),
    thumbnail_path (optional)."""
    year = datetime.now(timezone.utc).year
    genre_tag = str(metadata.get("genre", "game")).replace("_", "")
    title = (
        f"{metadata['game_title']} — New Roblox Game {year} #roblox #{genre_tag}"
    )[:100]
    hashtags = " ".join(metadata.get("hashtags", []))
    description = f"{metadata.get('description', '')}\n\n{hashtags}".strip()[:4900]
    tags = [t.lstrip("#") for t in metadata.get("tags", [])][:30]

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": GAMING_CATEGORY_ID,
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": True,  # Roblox promo content targets kids
        },
    }

    video_bytes = video_path.read_bytes()
    async with httpx.AsyncClient(timeout=600) as client:
        token = await _access_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        # Resumable upload: init → PUT bytes
        init = await client.post(
            UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers={
                **headers,
                "X-Upload-Content-Type": "video/mp4",
                "X-Upload-Content-Length": str(len(video_bytes)),
            },
            json=body,
        )
        init.raise_for_status()
        upload_url = init.headers["Location"]

        upload = await client.put(
            upload_url,
            headers={**headers, "Content-Type": "video/mp4"},
            content=video_bytes,
        )
        upload.raise_for_status()
        video_id = upload.json()["id"]

        # Thumbnail (best effort — requires a verified channel for customs)
        thumbnail_path = metadata.get("thumbnail_path")
        if thumbnail_path and pathlib.Path(thumbnail_path).exists():
            thumb = await client.post(
                THUMBNAIL_URL,
                params={"videoId": video_id},
                headers={**headers, "Content-Type": "image/png"},
                content=pathlib.Path(thumbnail_path).read_bytes(),
            )
            if thumb.status_code not in (200, 201):
                log.warning(
                    "marketing.youtube_thumbnail_failed",
                    status=thumb.status_code,
                    body=thumb.text[:300],
                )

    url = f"https://www.youtube.com/watch?v={video_id}"
    log.info("marketing.youtube_published", url=url)
    return url
