"""
One-time script to force build and publish a game to the sim genre account.
Bypasses the intelligence cycle and viability gate.
Uses a hardcoded high-quality pet collect concept since that is the sim account's genre.

NOTE ON BEHAVIOUR (verified against the current pipeline):
- The hardcoded CONCEPT below is written to concept_queue as the *seed*. The
  BuildPipeline's ConceptGenerator then expands a seed into the full game
  concept via the LLM, so the published game will be a pet_collect game on the
  sim account but its exact title/monetization may differ from the literal
  "Pet Galaxy" values here. (Changing that would require editing existing
  pipeline code, which this script intentionally does not do.)
- ApprovalGate/OpenCloudPublisher signatures require a reporter, publisher and
  marketer, so those are constructed here and wired up.
- SUPERVISED_MODE is forced to "false" so the build auto-approves and publishes
  immediately (that's the point of a force script). The publish rate limiter
  still applies: if the sim account already hit its weekly/spacing limit the
  row is parked with a scheduled_publish_after slot instead of publishing now —
  the script reports that case clearly.
- DRY_RUN=true builds everything but never touches the live Roblox universe.
"""
import asyncio
import os
import sys
import pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

# Force auto-approve so the build publishes immediately (force script intent).
os.environ["SUPERVISED_MODE"] = "false"

import json
import uuid
from datetime import datetime, timezone

from db import get_pool, close_pool, run_migrations
from build.pipeline import BuildPipeline
from monitor.discord_reporter import DiscordReporter
from publish.approval_gate import ApprovalGate
from publish.marketer import InRobloxMarketer
from publish.open_cloud_publisher import OpenCloudPublisher

# High quality pet collect concept for sim account
CONCEPT = {
    "game_title": "Pet Galaxy",
    "tagline": "Hatch the rarest pets in the universe",
    "mechanic_tag": "pet_collect",
    "core_loop": (
        "Players hatch eggs to collect pets with different rarities. "
        "Rarer pets earn more coins passively. "
        "Players trade pets with others to complete their collection. "
        "Coins are used to buy better eggs with higher rarity chances."
    ),
    "systems": [
        "egg hatching with rarity system",
        "pet collection and display",
        "passive coin generation from pets",
        "player trading system",
        "daily free egg",
        "collection milestones and rewards",
        "leaderboard by rarity score"
    ],
    "monetization": {
        "currency_name": "StarCoins",
        "game_passes": [
            {
                "name": "Lucky Hatcher",
                "price_robux": 299,
                "benefit": "2x legendary chance on all eggs"
            },
            {
                "name": "VIP Collector",
                "price_robux": 499,
                "benefit": "3x coins, exclusive VIP egg weekly, golden name tag"
            },
            {
                "name": "Coin Boost",
                "price_robux": 199,
                "benefit": "Permanent 2x coin earnings from all pets"
            }
        ],
        "shop_items": [
            {"name": "Common Egg", "price": 100, "type": "unlock"},
            {"name": "Rare Egg", "price": 500, "type": "unlock"},
            {"name": "Epic Egg", "price": 2000, "type": "unlock"},
            {"name": "Legendary Egg", "price": 8000, "type": "unlock"},
            {"name": "Galaxy Aura", "price": 5000, "type": "cosmetic"},
            {"name": "Star Trail", "price": 3000, "type": "cosmetic"},
            {"name": "Pet Size Upgrade", "price": 1000, "type": "boost"},
        ],
        "vip_server": True,
        "casual_tier": {
            "starter_pack_contents": "500 StarCoins and 3 Common Eggs",
            "daily_deal_pool": ["Galaxy Aura", "Star Trail", "Pet Size Upgrade"],
            "currency_bundles": [
                {"name": "Small", "price": 75, "amount": 500},
                {"name": "Medium", "price": 150, "amount": 1500, "badge": "BEST VALUE"},
                {"name": "Large", "price": 300, "amount": 3500}
            ]
        },
        "mid_tier": {
            "season_pass_price": 499,
            "season_pass_perks": [
                "2x StarCoins for 30 days",
                "Exclusive Season Pet",
                "Boosted daily login reward",
                "20-tier reward track"
            ],
            "season_pass_exclusive_cosmetic": "Galaxy Champion Aura",
            "vip_pass_price": 999,
            "vip_pass_perks": [
                "1.5x permanent coins",
                "VIP golden name tag",
                "Access to VIP egg room"
            ],
            "vip_exclusive_feature": "VIP Egg Room with guaranteed Rare+ eggs"
        },
        "whale_tier": {
            "limited_items": [
                {"name": "Cosmic Dragon Pet", "price": 2500, "stock": 100},
                {"name": "Void Phoenix Pet", "price": 2000, "stock": 150},
                {"name": "Galaxy Titan Pet", "price": 1500, "stock": 200}
            ],
            "founders_pack_price": 4999,
            "founders_pack_limit": 100,
            "custom_nametag_price": 2499
        },
        "fomo": {
            "flash_sale_frequency_days": 3,
            "seasonal_items": ["Halloween Ghost Pet", "Christmas Reindeer Pet", "Summer Dolphin Pet"]
        }
    },
    "toolbox_keywords": [
        "egg hatch roblox",
        "cute pet model",
        "galaxy space background",
        "sparkle particle effect",
        "treasure chest",
        "floating island",
        "rainbow bridge",
        "crystal pedestal"
    ],
    "target_genre_account": "sim",
    "balance": {
        "pet_starting_currency": 250,
        "base_income_per_second": 1,
        "base_drop_value": 1,
        "drop_interval_seconds": 2.0,
        "starting_currency": 250,
        "retention_reward_boost": 1.2
    },
    "cross_promo_siblings": [],
    "resolved_assets": []
}


async def main():
    print("Starting forced sim account build...")
    pool = await get_pool()

    try:
        # Ensure the schema is present (idempotent) so this works even if the
        # service hasn't been restarted since the latest migration.
        await run_migrations()

        # Write concept to concept_queue
        concept_id = str(uuid.uuid4())
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO concept_queue
                (id, created_at, status, concept_json, opportunity_score, genre, mechanic_tag)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid.UUID(concept_id),
                datetime.now(timezone.utc),
                "queued",
                json.dumps(CONCEPT),
                0.90,
                "pet_collect",
                "pet_collect",
            )
        print(f"Concept queued: {concept_id}")

        # Wire the pipeline + publish stack (reporter used for build/publish alerts)
        reporter = DiscordReporter(pool)

        # Run build pipeline
        print("Building game...")
        pipeline = BuildPipeline(pool, reporter)
        output = await pipeline.run(
            concept_id, meta_keywords=["pet", "collect", "hatch", "rare", "galaxy"]
        )

        if not output:
            print("Build failed — check build_failures table")
            return

        print(f"Build complete: {output.game_id}")
        print(f"Game title: {output.concept.get('game_title')}")
        if output.playtest:
            print(
                f"Playtest: {output.playtest.get('score')}/10 — "
                f"{output.playtest.get('verdict')}"
            )

        # Check DRY_RUN
        dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
        if dry_run:
            print("DRY_RUN=true — skipping publish")
            print(f"Build files at: {output.build_dir}")
            return

        # The publisher resolves ROBLOX_*_SIM creds from the genre account.
        genre = output.concept.get("target_genre_account") or "sim"
        publisher = OpenCloudPublisher(pool, reporter)
        marketer = InRobloxMarketer(pool)
        gate = ApprovalGate(pool, reporter)

        # Submit to approval gate (auto-approves because SUPERVISED_MODE=false)
        print(f"Submitting to approval gate (genre account: {genre})...")
        await gate.submit(output, genre)

        # Process immediately — publishes approved rows
        print("Processing approval...")
        await gate.process_decisions(publisher, marketer)

        # Report final state: published vs. parked by the rate limiter
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT processed_at, scheduled_publish_after, rate_limit_reason
                FROM pending_approvals WHERE game_id = $1
                """,
                uuid.UUID(output.game_id),
            )
        if row is None:
            print("Done! (approval row not found — check logs)")
        elif row["processed_at"] is not None:
            print("Done! Published — check your sim Roblox account for the new game.")
            print("Also check Discord for confirmation.")
        elif row["scheduled_publish_after"] is not None:
            print(
                "Build is approved but the publish rate limiter deferred it.\n"
                f"  Reason: {row['rate_limit_reason']}\n"
                f"  Next slot: {row['scheduled_publish_after']}\n"
                "It will publish automatically on the next publish_queue_processor "
                "run, or free a slot/raise PUBLISH_* limits to publish sooner."
            )
        else:
            print(
                "Build is approved but not yet published — check Discord/logs "
                "(e.g. the sim account's place pool may be exhausted)."
            )

    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
