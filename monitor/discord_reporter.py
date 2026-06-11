"""
DiscordReporter (spec 6.4) — big-decision alerts + weekly digest.
Alert side built first (PerformanceMonitor needs it); digest and
threshold checks completed in Phase 3 step 6.
"""
import os

import asyncpg
import httpx
import structlog

log = structlog.get_logger()


class DiscordReporter:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def alert(self, message: str) -> None:
        """Immediate big-decision alert via Discord webhook."""
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not webhook_url:
            log.warning("discord.not_configured", message=message[:200])
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    webhook_url, json={"content": f"🚨 **[RobloxStudio]** {message}"}
                )
                resp.raise_for_status()
        except Exception as exc:
            log.error("discord.alert_failed", error=str(exc))
