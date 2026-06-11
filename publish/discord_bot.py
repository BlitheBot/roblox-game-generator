"""
ApprovalBot (spec Section 12 + 16) — Discord bot that DMs the operator a
publish preview and listens for decision commands in that DM:

    !approve <game_id>            approve a pending publish
    !skip <game_id>               reject a pending publish (build is discarded)
    !resume <genre>               un-pause a genre account after moderation review
    !unsuppress <mechanic> <genre>  re-enable a FailureMemory-suppressed combo

Requires DISCORD_BOT_TOKEN and DISCORD_OWNER_ID. When unset, the
ApprovalGate falls back to webhook previews and decisions must be made
directly in the pending_approvals table.
"""
import os
import uuid

import asyncpg
import discord
import structlog

log = structlog.get_logger()


class ApprovalBot(discord.Client):
    def __init__(self, pool: asyncpg.Pool) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        self._pool = pool
        self._owner_id = int(os.environ["DISCORD_OWNER_ID"])

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
        if content.startswith("!approve "):
            await self._decide(message, content.removeprefix("!approve ").strip(), "approved")
        elif content.startswith("!skip "):
            await self._decide(message, content.removeprefix("!skip ").strip(), "skipped")
        elif content.startswith("!resume "):
            await self._resume(message, content.removeprefix("!resume ").strip())
        elif content.startswith("!unsuppress "):
            await self._unsuppress(message, content.removeprefix("!unsuppress ").strip())

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


def create_bot(pool: asyncpg.Pool) -> ApprovalBot | None:
    """Returns a configured bot, or None when bot env vars are unset."""
    if not os.environ.get("DISCORD_BOT_TOKEN") or not os.environ.get("DISCORD_OWNER_ID"):
        log.warning(
            "discord_bot.not_configured",
            hint="set DISCORD_BOT_TOKEN + DISCORD_OWNER_ID to enable DM approvals",
        )
        return None
    return ApprovalBot(pool)
