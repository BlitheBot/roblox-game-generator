"""
TikTok publisher (marketing step 5) — Content Posting API v2 direct
post (FILE_UPLOAD source).

Auth env vars: TIKTOK_ACCESS_TOKEN, TIKTOK_OPEN_ID (setup in DEPLOY.md).

GOTCHA: until the TikTok app passes TikTok's content-posting audit,
the API forces SELF_ONLY visibility regardless of the privacy_level
requested — videos land as private drafts. TIKTOK_PRIVACY_LEVEL env
var (default PUBLIC_TO_EVERYONE) lets you run SELF_ONLY pre-audit.

The API returns a publish_id rather than a video URL; the pipeline
stores the profile link + publish id.
"""
import asyncio
import os
import pathlib

import httpx
import structlog

log = structlog.get_logger()

API_BASE = "https://open.tiktokapis.com/v2"
CHUNK_SIZE = 10_000_000  # 10MB, the API's standard chunk size
STATUS_POLL_SECONDS = 5
STATUS_POLL_ATTEMPTS = 24  # ~2 minutes


def configured() -> bool:
    return all(os.environ.get(v) for v in ("TIKTOK_ACCESS_TOKEN", "TIKTOK_OPEN_ID"))


async def publish(video_path: pathlib.Path, metadata: dict) -> str:
    """Direct-post the video; returns a reference string
    (publish id + profile URL — the API exposes no direct video URL)."""
    caption_parts = [
        metadata.get("hook", ""),
        " ".join(metadata.get("hashtags", [])),
        "#roblox #robloxgame #fyp",
    ]
    caption = " ".join(p for p in caption_parts if p).strip()[:2200]

    token = os.environ["TIKTOK_ACCESS_TOKEN"]
    privacy = os.environ.get("TIKTOK_PRIVACY_LEVEL", "PUBLIC_TO_EVERYONE")
    video_bytes = video_path.read_bytes()
    total = len(video_bytes)
    chunk_count = max(1, (total + CHUNK_SIZE - 1) // CHUNK_SIZE)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    init_body = {
        "post_info": {
            "title": caption,
            "privacy_level": privacy,
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": total,
            "chunk_size": CHUNK_SIZE if chunk_count > 1 else total,
            "total_chunk_count": chunk_count,
        },
    }

    async with httpx.AsyncClient(timeout=600) as client:
        init = await client.post(
            f"{API_BASE}/post/publish/video/init/", headers=headers, json=init_body
        )
        init.raise_for_status()
        data = init.json()["data"]
        publish_id = data["publish_id"]
        upload_url = data["upload_url"]

        # Upload chunks (single PUT when the video fits one chunk)
        sent = 0
        chunk_size = init_body["source_info"]["chunk_size"]
        while sent < total:
            chunk = video_bytes[sent : sent + chunk_size]
            end = sent + len(chunk) - 1
            resp = await client.put(
                upload_url,
                headers={
                    "Content-Type": "video/mp4",
                    "Content-Range": f"bytes {sent}-{end}/{total}",
                    "Content-Length": str(len(chunk)),
                },
                content=chunk,
            )
            if resp.status_code not in (200, 201, 206):
                raise RuntimeError(
                    f"TikTok chunk upload failed ({resp.status_code}): {resp.text[:300]}"
                )
            sent += len(chunk)

        # Poll until processing settles
        for _ in range(STATUS_POLL_ATTEMPTS):
            status = await client.post(
                f"{API_BASE}/post/publish/status/fetch/",
                headers=headers,
                json={"publish_id": publish_id},
            )
            status.raise_for_status()
            state = status.json().get("data", {}).get("status", "")
            if state == "PUBLISH_COMPLETE":
                break
            if state in ("FAILED", "PUBLISH_FAILED"):
                reason = status.json().get("data", {}).get("fail_reason", "unknown")
                raise RuntimeError(f"TikTok publish failed: {reason}")
            await asyncio.sleep(STATUS_POLL_SECONDS)

    open_id = os.environ["TIKTOK_OPEN_ID"]
    reference = f"publish_id={publish_id} (profile: https://www.tiktok.com/@{open_id})"
    log.info("marketing.tiktok_published", publish_id=publish_id)
    return reference
