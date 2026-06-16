"""
ApprovalBot (spec Section 12 + 16) — Discord bot that DMs the operator a
publish preview and listens for decision + ops commands in that DM:

    !approve <game_id>              approve a pending publish
    !skip <game_id>                 reject a pending publish (build discarded)
    !retry <game_id>                re-trigger a stuck approved publish
    !resume <genre>                 un-pause a genre account after review
    !resume-account <genre>         alias of !resume <genre> (ban-handling, spec 19)
    !resume                         resume the orchestrator (after !pause)
    !pause                          pause the orchestrator after this cycle
    !force                          run one scout/build cycle immediately
    !unsuppress <mechanic> <genre>  re-enable a FailureMemory-suppressed combo
    !status                         system status snapshot
    !top5                           top 5 games by 7-day average CCU
    !revenue                        revenue summary
    !games                          list all published games
    !pipeline                       concept queue / approval pipeline status

Requires DISCORD_BOT_TOKEN and DISCORD_OWNER_ID. When unset, the
ApprovalGate falls back to webhook previews and decisions must be made
directly in the pending_approvals table.
"""
import asyncio
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import discord
import structlog

from .rate_limiter import PublishRateLimiter, _get_limits

log = structlog.get_logger()

# Roblox DevEx conversion rate (USD per Robux) — for the !revenue estimate
ROBUX_TO_USD = 0.0035


class ApprovalBot(discord.Client):
    def __init__(self, pool: asyncpg.Pool) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._pool = pool
        self._rate_limiter = PublishRateLimiter()
        self._owner_id = int(os.environ["DISCORD_OWNER_ID"])
        # Wired post-construction by the orchestrator via attach()
        self._orchestrator = None
        self._approval_gate = None
        self._publisher = None
        self._marketer = None

    def attach(
        self,
        orchestrator=None,
        approval_gate=None,
        publisher=None,
        marketer=None,
    ) -> None:
        """Give the bot the references the ops commands need (orchestrator for
        !force/!status, approval gate + publisher + marketer for !retry)."""
        self._orchestrator = orchestrator
        self._approval_gate = approval_gate
        self._publisher = publisher
        self._marketer = marketer

    async def on_ready(self) -> None:
        log.info("discord_bot.ready", user=str(self.user))

    # ── outbound: approval preview DM ───────────────────────

    async def send_approval_request(
        self,
        game_id: str,
        game_title: str,
        summary: str,
        thumbnail_path: str,
        genre: str,
    ) -> None:
        owner = await self.fetch_user(self._owner_id)
        embed = discord.Embed(
            title=f"📋 Publish approval needed: {game_title}",
            description=summary[:2000],
        )
        embed.add_field(name="Genre account", value=genre)
        embed.add_field(
            name="Respond with",
            value=f"`!approve {game_id}` or `!skip {game_id}`",
            inline=False,
        )
        if thumbnail_path and os.path.exists(thumbnail_path):
            embed.set_image(url="attachment://thumbnail.png")
            await owner.send(
                embed=embed,
                file=discord.File(thumbnail_path, filename="thumbnail.png"),
            )
        else:
            await owner.send(embed=embed)
        log.info("discord_bot.approval_requested", game_id=game_id, title=game_title)

    # ── inbound: DM commands ────────────────────────────────

    async def on_message(self, message: discord.Message) -> None:
        if message.author.id != self._owner_id or message.guild is not None:
            return
        content = message.content.strip()
        if not content.startswith("!"):
            return
        parts = content.split()
        cmd = parts[0].lower()
        arg = content[len(parts[0]):].strip()  # everything after the command word

        try:
            if cmd == "!approve" and arg:
                await self._decide(message, arg, "approved")
            elif cmd == "!skip" and arg:
                await self._decide(message, arg, "skipped")
            elif cmd == "!retry" and arg:
                await self._retry(message, arg)
            elif cmd == "!resume-account" and arg:
                await self._resume(message, arg)
            elif cmd == "!resume":
                if arg:
                    await self._resume(message, arg)        # genre account resume
                else:
                    await self._resume_orchestrator(message)  # orchestrator resume
            elif cmd == "!pause":
                await self._pause(message)
            elif cmd == "!unsuppress":
                await self._unsuppress(message, arg)
            elif cmd == "!force":
                await self._force(message)
            elif cmd == "!status":
                await self._status(message)
            elif cmd == "!top5":
                await self._top5(message)
            elif cmd == "!revenue":
                await self._revenue(message)
            elif cmd == "!games":
                await self._games(message)
            elif cmd == "!pipeline":
                await self._pipeline(message)
        except Exception as exc:
            log.error("discord_bot.command_failed", cmd=cmd, error=str(exc))
            await message.reply(f"Command `{cmd}` failed: {str(exc)[:300]}")

    # ── decisions ───────────────────────────────────────────

    async def _decide(
        self, message: discord.Message, game_id_str: str, status: str
    ) -> None:
        try:
            game_id = uuid.UUID(game_id_str)
        except ValueError:
            await message.reply(f"`{game_id_str}` is not a valid game id.")
            return
        async with self._pool.acquire() as conn:
            title = await conn.fetchval(
                """
                UPDATE pending_approvals
                SET status = $2, decided_at = NOW()
                WHERE game_id = $1 AND status = 'pending'
                RETURNING game_title
                """,
                game_id,
                status,
            )
        if title is None:
            await message.reply(f"No pending approval found for `{game_id_str}`.")
            return
        verb = "✅ Approved" if status == "approved" else "⏭️ Skipped"
        await message.reply(
            f"{verb} **{title}**. "
            + ("It will publish within a few minutes." if status == "approved" else "Build discarded.")
        )
        log.info("discord_bot.decision", game_id=game_id_str, status=status)

    async def _retry(self, message: discord.Message, game_id_str: str) -> None:
        """FIX 1/2: manually re-trigger a stuck approved publish."""
        if not (self._approval_gate and self._publisher and self._marketer):
            await message.reply("Retry unavailable — publisher not wired to the bot.")
            return
        result = await self._approval_gate.retry(
            game_id_str, self._publisher, self._marketer
        )
        await message.reply(result)
        log.info("discord_bot.retry", game_id=game_id_str)

    # ── account / orchestrator control ──────────────────────

    async def _resume(self, message: discord.Message, genre: str) -> None:
        """Spec 16: re-activate a paused genre account after manual review."""
        async with self._pool.acquire() as conn:
            updated = await conn.fetchval(
                """
                UPDATE genre_accounts SET status = 'active', last_checked = NOW()
                WHERE genre = $1 AND status = 'paused'
                RETURNING genre
                """,
                genre,
            )
        if updated is None:
            await message.reply(f"No paused account found for genre `{genre}`.")
        else:
            await message.reply(f"▶️ Publishing resumed on genre account `{genre}`.")
            log.info("discord_bot.account_resumed", genre=genre)

    async def _pause(self, message: discord.Message) -> None:
        await self._set_state("paused", "true")
        await message.reply("⏸️ Orchestrator paused after current cycle.")
        log.info("discord_bot.orchestrator_paused")

    async def _resume_orchestrator(self, message: discord.Message) -> None:
        await self._set_state("paused", "false")
        await message.reply("▶️ Orchestrator resumed.")
        log.info("discord_bot.orchestrator_resumed")

    async def _force(self, message: discord.Message) -> None:
        if self._orchestrator is None:
            await message.reply("Force unavailable — orchestrator not wired to the bot.")
            return
        await message.reply("⚡ Forcing immediate scout cycle...")
        asyncio.create_task(self._orchestrator.run_one_cycle(force=True))
        log.info("discord_bot.force_cycle")

    async def _unsuppress(self, message: discord.Message, args: str) -> None:
        """Improvement 6: re-enable a FailureMemory-suppressed combo."""
        from monitor.failure_memory import FailureMemory

        parts = args.split()
        if len(parts) != 2:
            await message.reply("Usage: `!unsuppress <mechanic> <genre>`")
            return
        mechanic, genre = parts
        if await FailureMemory(self._pool).unsuppress(mechanic, genre):
            await message.reply(
                f"✅ Combo `{mechanic} / {genre}` re-enabled with a fresh "
                f"3-strike counter. The scoring engine will consider it again."
            )
            log.info("discord_bot.combo_unsuppressed", mechanic=mechanic, genre=genre)
        else:
            await message.reply(
                f"No suppressed combo found for `{mechanic} / {genre}`."
            )

    # ── read-only status commands ───────────────────────────

    async def _status(self, message: discord.Message) -> None:
        async with self._pool.acquire() as conn:
            live = await conn.fetchval(
                "SELECT COUNT(*) FROM published_games WHERE status IN ('live','breakout','flagged')"
            )
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = 'pending'"
            )
            stuck = await conn.fetchval(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = 'approved' AND processed_at IS NULL"
            )
            failures_24h = await conn.fetchval(
                "SELECT COUNT(*) FROM build_failures WHERE timestamp > NOW() - INTERVAL '24 hours'"
            )
        last_cycle = await self._get_state("last_cycle_completed") or "never"
        paused = (await self._get_state("paused")) == "true"
        next_cycle = "n/a"
        if self._orchestrator is not None:
            try:
                job = self._orchestrator._scheduler.get_job("intelligence_cycle")
                if job and job.next_run_time:
                    next_cycle = job.next_run_time.isoformat()
            except Exception:
                pass
        alerts = []
        if paused:
            alerts.append("orchestrator PAUSED")
        if stuck:
            alerts.append(f"{stuck} approved publish(es) not yet processed")
        if failures_24h:
            alerts.append(f"{failures_24h} build failure(s) in 24h")

        schedule = await self._rate_limiter.get_schedule_summary(self._pool)
        total_this_week = sum(s["games_this_week"] for s in schedule.values())
        weekly_cap = _get_limits()["max_per_week_all_accounts"]

        lines = [
            "**System Status:**",
            f"🟢 Orchestrator: {'paused' if paused else 'running'}",
            f"⏰ Last cycle: {last_cycle}",
            f"🔄 Next cycle: {next_cycle}",
            "",
            "📅 **This Week's Publish Schedule:**",
        ]
        for account in ("idle", "horror", "sim"):
            s = schedule.get(account)
            if not s:
                continue
            lines.append(
                f"  {account+':':7} {s['games_this_week']}/{s['weekly_limit']} "
                f"games published | next slot: {s['next_publish_window']}"
            )
        lines += [
            "",
            f"📊 Total this week: {total_this_week}/{weekly_cap} games",
            f"🎮 Games live: {live or 0}",
            f"⏳ Pending approval: {pending or 0}",
            f"🔔 Active alerts: {', '.join(alerts) if alerts else 'none'}",
        ]
        await message.reply("\n".join(lines)[:1900])

    async def _top5(self, message: discord.Message) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT pg.game_title, pg.genre_account,
                       AVG(gm.ccu) AS avg_ccu,
                       COALESCE(SUM(gm.revenue_robux), 0) AS robux
                FROM published_games pg
                JOIN game_metrics gm ON gm.game_id = pg.id
                WHERE gm.timestamp > NOW() - INTERVAL '7 days'
                GROUP BY pg.id, pg.game_title, pg.genre_account
                ORDER BY avg_ccu DESC
                LIMIT 5
                """
            )
        if not rows:
            await message.reply("No CCU metrics recorded in the last 7 days yet.")
            return
        lines = ["**Top 5 Games by CCU (7-day avg):**"]
        for i, r in enumerate(rows, 1):
            lines.append(
                f"{i}. {r['game_title']} ({r['genre_account']}) — "
                f"{r['avg_ccu']:.0f} CCU — {int(r['robux']):,} Robux this week"
            )
        await message.reply("\n".join(lines)[:1900])

    async def _revenue(self, message: discord.Message) -> None:
        async with self._pool.acquire() as conn:
            all_time = await conn.fetchval(
                "SELECT COALESCE(SUM(revenue_robux), 0) FROM game_metrics"
            )
            this_week = await conn.fetchval(
                "SELECT COALESCE(SUM(revenue_robux), 0) FROM game_metrics "
                "WHERE timestamp > NOW() - INTERVAL '7 days'"
            )
            top = await conn.fetchrow(
                """
                SELECT pg.game_title, SUM(gm.revenue_robux) AS robux
                FROM game_metrics gm
                JOIN published_games pg ON pg.id = gm.game_id
                GROUP BY pg.game_title
                HAVING SUM(gm.revenue_robux) > 0
                ORDER BY robux DESC LIMIT 1
                """
            )
        usd = (all_time or 0) * ROBUX_TO_USD
        lines = [
            "**Revenue Summary:**",
            f"Total all time: {int(all_time or 0):,} Robux (~${usd:,.2f} DevEx est.)",
            f"This week: {int(this_week or 0):,} Robux",
        ]
        if top:
            lines.append(f"Top earner: {top['game_title']} — {int(top['robux']):,} Robux")
        else:
            lines.append("Top earner: none yet")
        await message.reply("\n".join(lines)[:1900])

    async def _games(self, message: discord.Message) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT pg.game_title, pg.genre_account, pg.status,
                       GREATEST(0, EXTRACT(DAY FROM NOW() - pg.published_at))::int AS days_live,
                       (SELECT ccu FROM game_metrics gm WHERE gm.game_id = pg.id
                        ORDER BY timestamp DESC LIMIT 1) AS ccu
                FROM published_games pg
                ORDER BY pg.published_at DESC
                """
            )
        if not rows:
            await message.reply("No published games yet.")
            return
        lines = [f"**All Published Games ({len(rows)} total):**"]
        for r in rows:
            ccu = r["ccu"] if r["ccu"] is not None else 0
            lines.append(
                f"- {r['game_title']} | {r['genre_account']} | {r['status']} | "
                f"{r['days_live']} days live | {ccu} CCU"
            )
        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1900] + "\n… (truncated)"
        await message.reply(text)

    async def _pipeline(self, message: discord.Message) -> None:
        async with self._pool.acquire() as conn:
            queued = await conn.fetchval(
                "SELECT COUNT(*) FROM concept_queue WHERE status = 'queued'"
            )
            building = await conn.fetch(
                "SELECT mechanic_tag, genre FROM concept_queue WHERE status = 'building'"
            )
            pending = await conn.fetchval(
                "SELECT COUNT(*) FROM pending_approvals WHERE status = 'pending'"
            )
            rate_limited = await conn.fetchval(
                """
                SELECT COUNT(*) FROM pending_approvals
                WHERE status = 'approved' AND processed_at IS NULL
                  AND scheduled_publish_after IS NOT NULL
                  AND scheduled_publish_after > NOW()
                """
            )
            last3 = await conn.fetch(
                """
                SELECT game_title, genre_account,
                       EXTRACT(EPOCH FROM (NOW() - published_at)) AS age_seconds
                FROM published_games ORDER BY published_at DESC LIMIT 3
                """
            )
        building_str = (
            ", ".join(f"{b['mechanic_tag']} ({b['genre']})" for b in building)
            if building
            else "idle"
        )
        schedule = await self._rate_limiter.get_schedule_summary(self._pool)
        lines = [
            "**Pipeline Status:**",
            f"💡 Queued concepts: {queued or 0}",
            f"🔨 Currently building: {building_str}",
            f"✅ Pending approval: {pending or 0}",
            f"⏳ Rate-limited (waiting for slot): {rate_limited or 0}",
            "",
            "Next publish slots:",
        ]
        for account in ("idle", "horror", "sim"):
            s = schedule.get(account)
            if not s:
                continue
            lines.append(
                f"  {account+':':7} {s['next_publish_window']} "
                f"({s['slots_remaining']} slots remaining)"
            )
        lines += ["", "Last 3 published:"]
        if last3:
            for r in last3:
                lines.append(
                    f"  • {r['game_title']} ({r['genre_account']}) — "
                    f"{self._ago(r['age_seconds'])}"
                )
        else:
            lines.append("  • none")
        await message.reply("\n".join(lines)[:1900])

    @staticmethod
    def _ago(seconds) -> str:
        """Human-readable 'time ago' for a publish age in seconds."""
        s = int(seconds or 0)
        if s < 3600:
            return f"{max(1, s // 60)}m ago"
        if s < 86400:
            return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"

    # ── orchestrator_state helpers ──────────────────────────

    async def _get_state(self, key: str) -> str | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT value FROM orchestrator_state WHERE key = $1", key
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


def create_bot(pool: asyncpg.Pool) -> ApprovalBot | None:
    """Returns a configured bot, or None when bot env vars are unset."""
    if not os.environ.get("DISCORD_BOT_TOKEN") or not os.environ.get("DISCORD_OWNER_ID"):
        log.warning(
            "discord_bot.not_configured",
            hint="set DISCORD_BOT_TOKEN + DISCORD_OWNER_ID to enable DM approvals",
        )
        return None
    return ApprovalBot(pool)
