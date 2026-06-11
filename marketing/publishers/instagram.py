"""
Instagram publisher (marketing step 6) — publishes the video as a Reel
via the Instagram Graph API (resumable upload, no public hosting URL
needed).

Requires a Facebook-connected Instagram Business/Creator account.
Auth env vars: INSTAGRAM_ACCESS_TOKEN, INSTAGRAM_ACCOUNT_ID
(setup in DEPLOY.md).

Flow: create REELS media container (upload_type=resumable) → POST the
bytes to rupload.facebook.com → poll container status → media_publish
→ fetch permalink.
"""
import asyncio
import os
import pathlib

import httpx
import structlog

log = structlog.get_logger()

GRAPH = "https://graph.facebook.com/v21.0"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload/v21.0"
STATUS_POLL_SECONDS = 5
STATUS_POLL_ATTEMPTS = 60  # Reels processing can take a few minutes


def configured() -> bool:
    return all(
        os.environ.get(v) for v in ("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_ACCOUNT_ID")
    )


async def publish(video_path: pathlib.Path, metadata: dict) -> str:
    """Publish as a Reel; returns the permalink (or media id fallback)."""
    caption_parts = [
        metadata.get("hook", ""),
        " ".join(metadata.get("hashtags", [])),
        "#roblox #robloxgame #reels",
    ]
    caption = " ".join(p for p in caption_parts if p).strip()[:2200]

    token = os.environ["INSTAGRAM_ACCESS_TOKEN"]
    account_id = os.environ["INSTAGRAM_ACCOUNT_ID"]
    video_bytes = video_path.read_bytes()

    async with httpx.AsyncClient(timeout=600) as client:
        # 1) Create a resumable REELS container
        container = await client.post(
            f"{GRAPH}/{account_id}/media",
            params={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption,
                "share_to_feed": "true",
                "access_token": token,
            },
        )
        container.raise_for_status()
        container_id = container.json()["id"]

        # 2) Upload the bytes
        upload = await client.post(
            f"{RUPLOAD}/{container_id}",
            headers={
                "Authorization": f"OAuth {token}",
                "offset": "0",
                "file_size": str(len(video_bytes)),
                "Content-Type": "application/octet-stream",
            },
            content=video_bytes,
        )
        if upload.status_code not in (200, 201):
            raise RuntimeError(
                f"Instagram upload failed ({upload.status_code}): {upload.text[:300]}"
            )

        # 3) Wait for processing
        for _ in range(STATUS_POLL_ATTEMPTS):
            status = await client.get(
                f"{GRAPH}/{container_id}",
                params={"fields": "status_code", "access_token": token},
            )
            status.raise_for_status()
            code = status.json().get("status_code", "")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError("Instagram container processing failed")
            await asyncio.sleep(STATUS_POLL_SECONDS)
        else:
            raise RuntimeError("Instagram container never finished processing")

        # 4) Publish
        published = await client.post(
            f"{GRAPH}/{account_id}/media_publish",
            params={"creation_id": container_id, "access_token": token},
        )
        published.raise_for_status()
        media_id = published.json()["id"]

        # 5) Permalink (best effort)
        permalink = ""
        link = await client.get(
            f"{GRAPH}/{media_id}",
            params={"fields": "permalink", "access_token": token},
        )
        if link.status_code == 200:
            permalink = link.json().get("permalink", "")

    url = permalink or f"media_id={media_id}"
    log.info("marketing.instagram_published", url=url)
    return url
