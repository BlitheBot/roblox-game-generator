"""
DiscordReporter (spec 6.4) — weekly digest + big-decision alerts.

Weekly digest (Mondays 09:00, scheduled by the orchestrator):
total games live, top 3 by CCU, 7-day revenue with per-game breakdown
(spec 17), breakout/underperform flags, next cycle's top opportunity.

Threshold checks (run every monitor cycle, deduped via orchestrator_state):
- build failure rate > 50% in last 24h
- OpenRouter spend > $15 in last 7 days (llm_spend table)
- TOS-flagged content pre-publish (build_failures stage 'tos_flag')
- any single game earning > 10,000 Robux in 7 days (spec 17)
Breakout alerts are sent directly by BreakoutDetector.
"""
import os
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import structlog

log = structlog.get_logger()

BUILD_FAILURE_RATE_LIMIT = 0.50
BUILD_FAILURE_MIN_BUILDS = 2
WEEKLY_SPEND_LIMIT_USD = 15.0
DAILY_SPEND_LIMIT_USD = 10.0
REVENUE_SPIKE_ROBUX = 10_000
ALERT_COOLDOWN_HOURS = 24
DISCORD_CONTENT_LIMIT = 2000


class DiscordReporter:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    # ── outbound ────────────────────────────────────────────

    async def alert(self, message: str) -> None:
        """Immediate big-decision alert via Discord webhook."""
        await self._post(f"🚨 **[RobloxStudio]** {message}")

    async def _post(self, content: str) -> None:
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
        if not webhook_url:
            log.warning("discord.not_configured", message=content[:200])
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    webhook_url, json={"content": content[:DISCORD_CONTENT_LIMIT]}
                )
                resp.raise_for_status()
        except Exception as exc:
            log.error("discord.post_failed", error=str(exc))

    # ── weekly digest ───────────────────────────────────────

    async def weekly_digest(self) -> None:
        async with self._pool.acquire() as conn:
            live_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM published_games
                WHERE status IN ('live', 'breakout', 'flagged')
                """
            )
            top_games = await conn.fetch(
                """
                SELECT pg.game_title, pg.status, gm.ccu
                FROM published_games pg
                JOIN LATERAL (
                    SELECT ccu FROM game_metrics
                    WHERE game_id = pg.id
                    ORDER BY timestamp DESC LIMIT 1
                ) gm ON TRUE
                WHERE pg.status IN ('live', 'breakout', 'flagged')
                ORDER BY gm.ccu DESC
                LIMIT 3
                """
            )
            revenue_total = await conn.fetchval(
                """
                SELECT COALESCE(SUM(revenue_robux), 0) FROM game_metrics
                WHERE timestamp > NOW() - INTERVAL '7 days'
                """
            )
            revenue_rows = await conn.fetch(
                """
                SELECT pg.game_title, SUM(gm.revenue_robux) AS robux
                FROM game_metrics gm
                JOIN published_games pg ON pg.id = gm.game_id
                WHERE gm.timestamp > NOW() - INTERVAL '7 days'
                GROUP BY pg.game_title
                HAVING SUM(gm.revenue_robux) > 0
                ORDER BY robux DESC
                LIMIT 5
                """
            )
            breakouts = await conn.fetch(
                "SELECT game_title FROM published_games WHERE status = 'breakout'"
            )
            flagged = await conn.fetch(
                "SELECT game_title FROM published_games WHERE status = 'flagged'"
            )
            top_opportunity = await conn.fetchrow(
                """
                SELECT genre, mechanic_tag, opportunity_score
                FROM concept_queue WHERE status = 'queued'
                ORDER BY opportunity_score DESC LIMIT 1
                """
            )

        lines = [
            "📊 **[RobloxStudio] Weekly Digest**",
            f"**Games live:** {live_count}",
        ]
        if top_games:
            lines.append("**Top 3 by CCU:**")
            for i, g in enumerate(top_games, 1):
                tag = " 🚀" if g["status"] == "breakout" else ""
                lines.append(f"  {i}. {g['game_title']} — {g['ccu']} CCU{tag}")
        lines.append(f"**Revenue (7d):** {revenue_total:,} Robux")
        for r in revenue_rows:
            lines.append(f"  • {r['game_title']} — {r['robux']:,} Robux")
        if breakouts:
            lines.append("**Breakout:** " + ", ".join(b["game_title"] for b in breakouts))
        if flagged:
            lines.append("**Underperforming:** " + ", ".join(f["game_title"] for f in flagged))
        if top_opportunity:
            lines.append(
                f"**Next top opportunity:** {top_opportunity['mechanic_tag']} "
                f"({top_opportunity['genre']}) — score "
                f"{top_opportunity['opportunity_score']:.2f}"
            )
        else:
            lines.append("**Next top opportunity:** queue empty")

        await self._post("\n".join(lines))
        log.info("discord.weekly_digest_sent", games=live_count)

    # ── threshold checks ────────────────────────────────────

    async def run_threshold_checks(self) -> None:
        for check in (
            self._check_build_failure_rate,
            self._check_openrouter_spend,
            self._check_daily_llm_spend,
            self._check_tos_flags,
            self._check_revenue_spikes,
        ):
            try:
                await check()
            except Exception as exc:
                log.error("discord.threshold_check_failed", check=check.__name__, error=str(exc))

    async def _check_build_failure_rate(self) -> None:
        async with self._pool.acquire() as conn:
            failed = await conn.fetchval(
                """
                SELECT COUNT(DISTINCT bf.concept_id)
                FROM build_failures bf
                JOIN concept_queue cq ON cq.id = bf.concept_id
                WHERE bf.timestamp > NOW() - INTERVAL '24 hours'
                  AND cq.status = 'failed'
                """
            )
            # Successes = published, plus builds parked in the supervised
            # approval queue (built fine, just not published yet)
            published = await conn.fetchval(
                "SELECT COUNT(*) FROM published_games WHERE published_at > NOW() - INTERVAL '24 hours'"
            )
            queued = await conn.fetchval(
                "SELECT COUNT(*) FROM pending_approvals WHERE created_at > NOW() - INTERVAL '24 hours'"
            )
        total = (failed or 0) + (published or 0) + (queued or 0)
        if total < BUILD_FAILURE_MIN_BUILDS:
            return
        rate = (failed or 0) / total
        if rate > BUILD_FAILURE_RATE_LIMIT and await self._cooldown_ok("build_failure_rate"):
            await self.alert(
                f"Build failure rate is {rate:.0%} over the last 24h "
                f"({failed}/{total} builds failed). Check build_failures table."
            )
            await self._mark_alerted("build_failure_rate")

    async def _check_openrouter_spend(self) -> None:
        async with self._pool.acquire() as conn:
            spend = await conn.fetchval(
                """
                SELECT COALESCE(SUM(cost_usd), 0) FROM llm_spend
                WHERE timestamp > NOW() - INTERVAL '7 days'
                """
            )
        if spend > WEEKLY_SPEND_LIMIT_USD and await self._cooldown_ok("openrouter_spend"):
            await self.alert(
                f"OpenRouter spend is ${spend:.2f} over the last 7 days "
                f"(limit ${WEEKLY_SPEND_LIMIT_USD:.0f})."
            )
            await self._mark_alerted("openrouter_spend")

    async def _check_daily_llm_spend(self) -> None:
        """FIX 7: if OpenRouter spend exceeds $10 in 24h, alert and pause the
        orchestrator (operator resumes with !resume after review)."""
        async with self._pool.acquire() as conn:
            spend = await conn.fetchval(
                """
                SELECT COALESCE(SUM(cost_usd), 0) FROM llm_spend
                WHERE timestamp > NOW() - INTERVAL '24 hours'
                """
            )
        if spend > DAILY_SPEND_LIMIT_USD and await self._cooldown_ok("daily_llm_spend"):
            await self._set_state("paused", "true")
            await self.alert(
                f"⛔ OpenRouter spend is ${spend:.2f} in the last 24h "
                f"(limit ${DAILY_SPEND_LIMIT_USD:.0f}). Builds paused — review "
                f"and `!resume` when ready."
            )
            await self._mark_alerted("daily_llm_spend")

    async def _check_tos_flags(self) -> None:
        """Alert on new TOS-flagged builds since the last cursor position."""
        async with self._pool.acquire() as conn:
            cursor_str = await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = 'tos_alert_cursor'"
            )
            cursor = (
                datetime.fromisoformat(cursor_str)
                if cursor_str
                else datetime.now(timezone.utc) - timedelta(days=1)
            )
            rows = await conn.fetch(
                """
                SELECT concept_id, timestamp, error_message FROM build_failures
                WHERE stage = 'tos_flag' AND timestamp > $1
                ORDER BY timestamp
                """,
                cursor,
            )
        for row in rows:
            await self.alert(
                f"TOS-flagged content detected pre-publish — concept "
                f"{row['concept_id']}: {row['error_message'][:300]}"
            )
        if rows:
            await self._set_state("tos_alert_cursor", rows[-1]["timestamp"].isoformat())

    async def _check_revenue_spikes(self) -> None:
        """Spec 17: any single game > 10,000 Robux in a 7-day window."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT pg.id, pg.game_title, SUM(gm.revenue_robux) AS robux
                FROM game_metrics gm
                JOIN published_games pg ON pg.id = gm.game_id
                WHERE gm.timestamp > NOW() - INTERVAL '7 days'
                GROUP BY pg.id, pg.game_title
                HAVING SUM(gm.revenue_robux) > $1
                """,
                REVENUE_SPIKE_ROBUX,
            )
        for row in rows:
            key = f"revenue_spike:{row['id']}"
            if await self._cooldown_ok(key, hours=7 * 24):
                await self.alert(
                    f"💰 Game **{row['game_title']}** earned {row['robux']:,} Robux "
                    f"in the last 7 days — worth your attention."
                )
                await self._mark_alerted(key)

    # ── alert dedup via orchestrator_state ──────────────────

    async def _cooldown_ok(self, name: str, hours: int = ALERT_COOLDOWN_HOURS) -> bool:
        async with self._pool.acquire() as conn:
            last_str = await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = $1",
                f"alert_cooldown:{name}",
            )
        if not last_str:
            return True
        last = datetime.fromisoformat(last_str)
        return datetime.now(timezone.utc) - last >= timedelta(hours=hours)

    async def _mark_alerted(self, name: str) -> None:
        await self._set_state(
            f"alert_cooldown:{name}", datetime.now(timezone.utc).isoformat()
        )

    async def _set_state(self, key: str, value: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestrator_state (key, value, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at
                """,
                key,
                value,
            )
