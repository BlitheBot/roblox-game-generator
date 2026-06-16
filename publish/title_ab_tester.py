"""
TitleABTester (Improvement 5) — finds the highest-CTR game title by testing.

Process:
1. ConceptGenerator produces one base title.
2. TitleABTester generates 2 alternative titles in different proven patterns.
3. Game publishes with the base title; a title_ab_tests row is opened.
4. Every 16 hours for 48 hours, rotate to the next variant via Open Cloud.
5. After 48 hours, the period with the highest visit velocity (CCU proxy for
   CTR — Roblox doesn't expose per-title CTR) wins and is set permanently.

LLM + Open Cloud calls are wrapped by callers so a failure is never fatal.
"""
import uuid
from datetime import datetime, timezone

import asyncpg
import structlog

from intelligence.llm_client import DEEPSEEK_V3, chat_json

log = structlog.get_logger()

ROTATION_HOURS = 16
TEST_DURATION_HOURS = 48

# Genre keyword used in the search-optimized variant
GENRE_KEYWORDS = {
    "idle_tycoon": "Tycoon",
    "pet_collect": "Simulator",
    "survival_horror": "Horror",
    "incremental_sim": "Simulator",
}


class TitleABTester:
    async def generate_title_variants(
        self, base_concept: dict, base_title: str
    ) -> list[str]:
        """Generate 2 alternative titles. Returns [base_title, variant_a, variant_b]."""
        mechanic_tag = base_concept.get("mechanic_tag", "")
        core_loop = base_concept.get("core_loop", "")
        theme = base_concept.get("tagline", "")
        genre_keyword = GENRE_KEYWORDS.get(mechanic_tag, "")

        messages = [
            {
                "role": "system",
                "content": (
                    "You generate alternative Roblox game titles for A/B testing. "
                    "Generate exactly 2 alternative titles for the game described. "
                    "Title A must follow the 'Verb a Noun' pattern (e.g. 'Grow a Garden', "
                    "'Pet a Dragon'). Title B must be '[Theme Word] [Genre Keyword]' "
                    "(e.g. 'Cookie Tycoon', 'Dragon Simulator'). Both titles must be 2-4 "
                    "words maximum. Family friendly. No special characters. "
                    'Return JSON: {"title_a": "string", "title_b": "string"}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Game concept: {core_loop}\n"
                    f"Theme: {theme}\n"
                    f"Genre keyword to use: {genre_keyword}\n"
                    f"Original title (do not repeat): {base_title}"
                ),
            },
        ]
        result = await chat_json(DEEPSEEK_V3, messages, temperature=0.8)
        title_a = str(result.get("title_a", "") or "").strip() or base_title
        title_b = str(result.get("title_b", "") or "").strip() or base_title

        if title_a == base_title:
            title_a = f"{base_title} Adventure"
        if title_b == base_title or title_b == title_a:
            title_b = f"{base_title} World"
        return [base_title, title_a, title_b]

    async def start_title_test(
        self,
        pool: asyncpg.Pool,
        game_id: str,
        universe_id: int,
        genre_account: str,
        variants: list[str],
    ) -> None:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO title_ab_tests
                    (id, game_id, universe_id, genre_account,
                     variant_0, variant_1, variant_2,
                     current_variant, test_started_at, test_ends_at, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, 0, NOW(),
                        NOW() + make_interval(hours => $8), 'running')
                """,
                uuid.uuid4(),
                uuid.UUID(game_id),
                universe_id,
                genre_account,
                variants[0],
                variants[1],
                variants[2],
                TEST_DURATION_HOURS,
            )
        log.info("title_ab_test.started", game_id=game_id, variants=variants)

    async def process_title_rotations(
        self, pool: asyncpg.Pool, publisher, reporter
    ) -> None:
        """Runs every 16 hours. Rotates running tests to the next variant;
        completes tests past 48 hours and locks in the winner."""
        async with pool.acquire() as conn:
            active_tests = await conn.fetch(
                "SELECT * FROM title_ab_tests WHERE status = 'running'"
            )
        for test in active_tests:
            now = datetime.now(timezone.utc)
            if test["test_ends_at"] is not None and now >= test["test_ends_at"]:
                await self._complete_test(pool, publisher, reporter, test)
                continue

            next_variant = (test["current_variant"] + 1) % 3
            new_title = test[f"variant_{next_variant}"]
            ok = await publisher.update_title(
                test["genre_account"], test["universe_id"], new_title
            )
            if ok:
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE title_ab_tests
                        SET current_variant = $1, last_rotation_at = NOW()
                        WHERE id = $2
                        """,
                        next_variant,
                        test["id"],
                    )
                log.info(
                    "title_ab_test.rotated",
                    game_id=str(test["game_id"]),
                    new_title=new_title,
                    variant=next_variant,
                )

    async def _complete_test(self, pool: asyncpg.Pool, publisher, reporter, test) -> None:
        """Pick the highest-velocity period as the winner and lock it in."""
        async with pool.acquire() as conn:
            metrics = await conn.fetch(
                """
                SELECT timestamp, ccu FROM game_metrics
                WHERE game_id = $1 AND timestamp >= $2
                ORDER BY timestamp ASC
                """,
                test["game_id"],
                test["test_started_at"],
            )

        if not metrics or len(metrics) < 3:
            winning_variant = 0  # not enough data — keep the original title
        else:
            period_size = len(metrics) // 3
            period_ccus = []
            for i in range(3):
                chunk = metrics[i * period_size : (i + 1) * period_size]
                avg = sum((m["ccu"] or 0) for m in chunk) / max(len(chunk), 1)
                period_ccus.append(avg)
            winning_variant = period_ccus.index(max(period_ccus))

        winning_title = test[f"variant_{winning_variant}"]
        await publisher.update_title(
            test["genre_account"], test["universe_id"], winning_title
        )
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE published_games SET game_title = $1 WHERE id = $2",
                winning_title,
                test["game_id"],
            )
            await conn.execute(
                """
                UPDATE title_ab_tests
                SET status = 'complete', winning_variant = $1,
                    winning_title = $2, completed_at = NOW()
                WHERE id = $3
                """,
                winning_variant,
                winning_title,
                test["id"],
            )
        log.info(
            "title_ab_test.complete",
            game_id=str(test["game_id"]),
            winning_title=winning_title,
            winning_variant=winning_variant,
        )
        if reporter is not None:
            await reporter.alert(
                f"🏆 Title A/B test complete!\n"
                f"Winner: **{winning_title}** (variant {winning_variant})\n"
                f"Tested: {test['variant_0']} | {test['variant_1']} | {test['variant_2']}"
            )
