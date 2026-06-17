"""
PublishRateLimiter (core feature) — enforces a sane publish cadence.

Overnight the bot published 8 games on one account; the target is 2-3 per
account per week with proper spacing. can_publish() checks every limit before
any publish is allowed; blocked games stay queued (scheduled_publish_after) and
are retried by the publish_queue_processor without spamming Discord.

All limits are read from env (PUBLISH_LIMIT_*) with safe defaults.
"""
import os
import random
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog

log = structlog.get_logger()

# Genre accounts whose publish cadence is tracked
ACCOUNTS = ("idle", "horror", "sim")

# Roblox peak hours in UTC (≈ 9am-4pm EST) — prefer publishing in this window
PEAK_HOURS = (13, 14, 15, 16, 17, 18, 19, 20)

# An opportunity score at/above this unlocks the higher weekly per-account cap
HIGH_OPPORTUNITY_SCORE = 0.85


def _get_limits() -> dict:
    """Read limits from env with safe defaults."""
    return {
        "per_account_per_week": int(
            os.environ.get("PUBLISH_LIMIT_PER_ACCOUNT_PER_WEEK", "2")
        ),
        "per_account_per_week_max": int(
            os.environ.get("PUBLISH_LIMIT_MAX_PER_ACCOUNT_PER_WEEK", "3")
        ),
        "min_hours_between_same_account": int(
            os.environ.get("PUBLISH_MIN_HOURS_SAME_ACCOUNT", "60")
        ),
        "min_hours_between_any_publish": int(
            os.environ.get("PUBLISH_MIN_HOURS_ANY", "12")
        ),
        "max_per_day_all_accounts": int(os.environ.get("PUBLISH_MAX_PER_DAY", "1")),
        "max_per_week_all_accounts": int(os.environ.get("PUBLISH_MAX_PER_WEEK", "6")),
    }


class PublishRateLimiter:
    async def get_backlog_allowance(
        self, pool: asyncpg.Pool, genre_account: str
    ) -> int:
        """
        How many backlog games may publish today for this account, on top of the
        normal weekly limit. Applies ONLY to games approved before the rate
        limiter existed (queued > 24h), never to fresh builds.

        Conservative: at most 1 extra backlog game per account per day, and it
        never bypasses the same-account / any-publish minimum gaps — so the
        backlog clears over ~1-2 weeks instead of in a suspicious 24h burst.
        """
        async with pool.acquire() as conn:
            backlog_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM pending_approvals
                WHERE status = 'approved'
                  AND processed_at IS NULL
                  AND created_at < NOW() - INTERVAL '24 hours'
                """
            )
        if not backlog_count:
            return 0
        return 1

    async def can_publish(
        self,
        pool: asyncpg.Pool,
        genre_account: str,
        opportunity_score: float = 0.0,
        backlog_allowance: int = 0,
    ) -> tuple[bool, str]:
        """Returns (allowed, reason). Checks all rate limits before allowing
        any publish. backlog_allowance (max +1/day) relaxes only the weekly and
        daily *caps* — never the same-account (60h) or any-publish (12h) gaps."""
        limits = _get_limits()
        backlog_allowance = max(0, int(backlog_allowance or 0))
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        day_ago = now - timedelta(days=1)

        async with pool.acquire() as conn:
            # Check 1: weekly limit for this specific account
            weekly_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM published_games
                WHERE genre_account = $1
                  AND published_at > $2
                  AND status NOT IN ('failed')
                """,
                genre_account,
                week_ago,
            )

            weekly_limit = limits["per_account_per_week"]
            if opportunity_score >= HIGH_OPPORTUNITY_SCORE:
                weekly_limit = limits["per_account_per_week_max"]
            weekly_limit += backlog_allowance

            if weekly_count >= weekly_limit:
                next_slot = await self._next_available_slot(conn, genre_account, limits)
                return False, (
                    f"{genre_account} account has published {weekly_count}/{weekly_limit} "
                    f"games this week. Next slot available: "
                    f"{next_slot.strftime('%A %H:%M UTC')}"
                )

            # Check 2: minimum gap between publishes on the same account
            last_on_account = await conn.fetchval(
                """
                SELECT MAX(published_at) FROM published_games
                WHERE genre_account = $1 AND status NOT IN ('failed')
                """,
                genre_account,
            )
            if last_on_account:
                hours_since = (now - last_on_account).total_seconds() / 3600
                min_hours = limits["min_hours_between_same_account"]
                if hours_since < min_hours:
                    hours_remaining = min_hours - hours_since
                    return False, (
                        f"{genre_account} account published {hours_since:.0f}h ago. "
                        f"Minimum gap is {min_hours}h. "
                        f"Next publish in {hours_remaining:.0f}h."
                    )

            # Check 3: minimum gap between ANY publish across all accounts
            last_any = await conn.fetchval(
                "SELECT MAX(published_at) FROM published_games WHERE status NOT IN ('failed')"
            )
            if last_any:
                hours_since_any = (now - last_any).total_seconds() / 3600
                min_any = limits["min_hours_between_any_publish"]
                if hours_since_any < min_any:
                    hours_remaining = min_any - hours_since_any
                    return False, (
                        f"A game was published {hours_since_any:.0f}h ago on another account. "
                        f"Minimum gap between any publishes is {min_any}h. "
                        f"Next publish in {hours_remaining:.0f}h."
                    )

            # Check 4: daily ceiling across all accounts
            daily_count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM published_games
                WHERE published_at > $1 AND status NOT IN ('failed')
                """,
                day_ago,
            )
            max_per_day = limits["max_per_day_all_accounts"] + backlog_allowance
            if daily_count >= max_per_day:
                return False, (
                    f"Already published {daily_count} game(s) today "
                    f"(daily limit: {max_per_day}). "
                    f"Next publish available tomorrow."
                )

            # Check 5: weekly ceiling across all accounts
            weekly_total = await conn.fetchval(
                """
                SELECT COUNT(*) FROM published_games
                WHERE published_at > $1 AND status NOT IN ('failed')
                """,
                week_ago,
            )
            max_per_week = limits["max_per_week_all_accounts"] + backlog_allowance
            if weekly_total >= max_per_week:
                return False, (
                    f"Published {weekly_total}/{max_per_week} games this week across all "
                    f"accounts. Weekly limit reached — resuming next week."
                )

        return True, "ok"

    async def _next_available_slot(
        self,
        conn: asyncpg.Connection,
        genre_account: str,
        limits: dict,
    ) -> datetime:
        """Calculate the earliest datetime this account can next publish."""
        now = datetime.now(timezone.utc)

        last_publish = await conn.fetchval(
            "SELECT MAX(published_at) FROM published_games WHERE genre_account = $1",
            genre_account,
        )

        if not last_publish:
            return now

        # Must be at least min_hours after the last publish on this account
        min_gap = timedelta(hours=limits["min_hours_between_same_account"])
        earliest = last_publish + min_gap

        # Prefer peak Roblox hours; if outside the window, push to the next one
        candidate = max(now, earliest)
        for _ in range(48):  # search up to 48 hours ahead
            if candidate.hour in PEAK_HOURS:
                break
            candidate += timedelta(hours=1)

        # Small random jitter (0-3 hours) so publishes aren't predictable
        jitter = timedelta(minutes=random.randint(0, 180))
        return candidate + jitter

    async def next_available_slot(
        self, pool: asyncpg.Pool, genre_account: str
    ) -> datetime:
        """Public wrapper around _next_available_slot for callers that need a
        slot time but don't already hold a connection."""
        limits = _get_limits()
        async with pool.acquire() as conn:
            return await self._next_available_slot(conn, genre_account, limits)

    async def get_schedule_summary(self, pool: asyncpg.Pool) -> dict:
        """Full publishing schedule summary for the !status / !pipeline
        Discord commands."""
        limits = _get_limits()
        now = datetime.now(timezone.utc)
        week_ago = now - timedelta(days=7)
        summary: dict = {}

        async with pool.acquire() as conn:
            for account in ACCOUNTS:
                weekly_count = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM published_games
                    WHERE genre_account = $1 AND published_at > $2
                      AND status NOT IN ('failed')
                    """,
                    account,
                    week_ago,
                ) or 0

                next_slot = await self._next_available_slot(conn, account, limits)
                slots_remaining = max(0, limits["per_account_per_week"] - weekly_count)

                summary[account] = {
                    "games_this_week": weekly_count,
                    "weekly_limit": limits["per_account_per_week"],
                    "slots_remaining": slots_remaining,
                    "next_publish_window": next_slot.strftime("%a %d %b %H:%M UTC"),
                    "can_publish_now": slots_remaining > 0 and next_slot <= now,
                }

        return summary
