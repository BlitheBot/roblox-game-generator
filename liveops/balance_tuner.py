"""
BalanceTuner (LiveOps step 3) — evaluates the last 7 days of metrics
against fixed thresholds, then has DeepSeek V3 produce a numeric patch
(within whitelisted knobs and clamped ranges) with its reasoning.

Thresholds:
  avg session < 8 min     → progression too slow: drop rates +15-25%
  avg session > 45 min    → too grindy for new players: early-game boost
                            (higher starting currency)
  CCU down 3 days in a row → cheapest game pass price -20%
  D7 retention < 20%      → day-3/7 milestone rewards +30%
                            (retention_reward_boost = 1.3)

Session length and D7 retention are currently NULL stubs (the Open
Cloud Analytics API rollout, see PerformanceMonitor) — those rules
log "insufficient data" and skip until real samples arrive. The CCU
trend rule runs on live data today.

All applied changes are appended to balance_history.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog

from intelligence.llm_client import DEEPSEEK_V3, chat_json

log = structlog.get_logger()

SESSION_SLOW_MINUTES = 8
SESSION_GRINDY_MINUTES = 45
D7_LOW = 0.20
CCU_TREND_DAYS = 3

# knob → (min, max) clamp so a bad model reply can't wreck an economy
KNOB_RANGES = {
    "base_drop_value":        (0.5, 20),
    "drop_interval_seconds":  (0.5, 5),
    "starting_currency":      (0, 5000),
    "pet_starting_currency":  (50, 10000),
    "base_income_per_second": (0.5, 20),
    "base_growth_per_tick":   (0.5, 20),
    "base_sell_value":        (0.5, 20),
    "survival_reward":        (10, 1000),
    "retention_reward_boost": (1, 2),
}

PATCH_SCHEMA_HINT = """{
  "changes": {"knob_name": 0.0},
  "cheapest_pass_price": 0,
  "reasoning": "string (why each change, tied to the triggered metrics)"
}"""


async def _collect_metrics(pool: asyncpg.Pool, game_id: str) -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with pool.acquire() as conn:
        agg = await conn.fetchrow(
            """
            SELECT AVG(session_length_avg) AS avg_session,
                   AVG(d7_retention)       AS avg_d7
            FROM game_metrics
            WHERE game_id = $1 AND timestamp > $2
            """,
            uuid.UUID(game_id),
            cutoff,
        )
        daily_ccu = await conn.fetch(
            """
            SELECT date_trunc('day', timestamp) AS day, AVG(ccu) AS ccu
            FROM game_metrics
            WHERE game_id = $1 AND timestamp > $2
            GROUP BY 1 ORDER BY 1
            """,
            uuid.UUID(game_id),
            cutoff,
        )
    return {
        "avg_session_minutes": (
            float(agg["avg_session"]) / 60 if agg and agg["avg_session"] is not None else None
        ),
        "avg_d7": float(agg["avg_d7"]) if agg and agg["avg_d7"] is not None else None,
        "daily_ccu": [float(r["ccu"]) for r in daily_ccu],
    }


def _evaluate_triggers(metrics: dict) -> list[str]:
    triggers: list[str] = []

    session = metrics["avg_session_minutes"]
    if session is None:
        log.info("liveops.balance.session_data_missing")
    elif session < SESSION_SLOW_MINUTES:
        triggers.append(
            f"avg session {session:.1f}min < {SESSION_SLOW_MINUTES}min: progression "
            f"too slow — increase resource/drop rates by 15-25%"
        )
    elif session > SESSION_GRINDY_MINUTES:
        triggers.append(
            f"avg session {session:.1f}min > {SESSION_GRINDY_MINUTES}min: may be too "
            f"grindy for new players — add an early-game boost (raise starting currency)"
        )

    daily = metrics["daily_ccu"]
    if len(daily) >= CCU_TREND_DAYS + 1:
        recent = daily[-(CCU_TREND_DAYS + 1):]
        if all(recent[i] > recent[i + 1] for i in range(len(recent) - 1)):
            triggers.append(
                "CCU declined 3 days in a row: cheapest game pass may be "
                "overpriced — reduce its price by 20%"
            )

    d7 = metrics["avg_d7"]
    if d7 is None:
        log.info("liveops.balance.d7_data_missing")
    elif d7 < D7_LOW:
        triggers.append(
            f"D7 retention {d7:.0%} < {D7_LOW:.0%}: daily login rewards too weak — "
            f"set retention_reward_boost to 1.3 (+30% day 3/7 milestone rewards)"
        )

    return triggers


async def generate_balance_patch(
    pool: asyncpg.Pool, game_id: str, concept: dict
) -> tuple[dict, list[str]] | None:
    """Returns (patch, change_lines) when thresholds triggered, else None.
    The patch is already clamped and applied to the concept in place."""
    metrics = await _collect_metrics(pool, game_id)
    triggers = _evaluate_triggers(metrics)
    if not triggers:
        log.info("liveops.balance.no_triggers", game_id=game_id)
        return None

    mechanic = concept.get("mechanic_tag", "")
    current_balance = concept.get("balance", {})
    passes = concept.get("monetization", {}).get("game_passes", [])

    messages = [
        {
            "role": "system",
            "content": (
                "You tune the economy of a live Roblox game. Apply ONLY the "
                "requested adjustments from the triggered rules, changing the "
                "minimum set of knobs. Available knobs and their meaning: "
                "base_drop_value/base_income_per_second/base_growth_per_tick/"
                "base_sell_value (resource rates), drop_interval_seconds "
                "(lower = faster), starting_currency/pet_starting_currency "
                "(early-game boost), survival_reward (round payout), "
                "retention_reward_boost (login reward multiplier). Defaults "
                "are 1 (rates), 2.0 (interval), 0/250 (starting), 50 (survival), "
                "1 (retention boost). cheapest_pass_price: only set when the "
                "CCU-decline rule triggered, as the new Robux price (current "
                "price minus 20%, min 49). "
                f"Return JSON exactly matching this schema:\n{PATCH_SCHEMA_HINT}"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Game mechanic: {mechanic}\n"
                f"Current balance overrides: {json.dumps(current_balance)}\n"
                f"Game passes: {json.dumps(passes)}\n"
                f"Metrics: {json.dumps(metrics)}\n"
                f"Triggered rules:\n- " + "\n- ".join(triggers)
            ),
        },
    ]
    raw = await chat_json(DEEPSEEK_V3, messages, temperature=0.2)
    reasoning = str(raw.get("reasoning", ""))[:1000]

    # Clamp + apply numeric knob changes
    balance = concept.setdefault("balance", {})
    change_lines: list[str] = []
    applied: dict[str, float] = {}
    for knob, value in (raw.get("changes") or {}).items():
        if knob not in KNOB_RANGES:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        low, high = KNOB_RANGES[knob]
        value = max(low, min(high, value))
        old = balance.get(knob)
        balance[knob] = value
        applied[knob] = value
        change_lines.append(f"{knob}: {old if old is not None else 'default'} → {value}")

    # Cheapest game pass price cut
    new_price = raw.get("cheapest_pass_price")
    if new_price and passes:
        try:
            new_price = max(49, int(new_price))
            cheapest = min(passes, key=lambda p: int(p.get("price_robux", 10**9)))
            old_price = cheapest.get("price_robux")
            if new_price < int(old_price or 10**9):
                cheapest["price_robux"] = new_price
                applied["cheapest_pass_price"] = new_price
                change_lines.append(
                    f"game pass '{cheapest.get('name')}': {old_price} → {new_price} Robux"
                )
        except (TypeError, ValueError):
            pass

    if not applied:
        log.info("liveops.balance.model_returned_no_changes", game_id=game_id)
        return None

    patch = {"changes": applied, "reasoning": reasoning, "triggers": triggers}
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO balance_history
                (game_id, metric_trigger, change_description, patch_json)
            VALUES ($1, $2, $3, $4)
            """,
            uuid.UUID(game_id),
            "; ".join(t.split(":")[0] for t in triggers)[:500],
            ("; ".join(change_lines) + f" — {reasoning}")[:1000],
            json.dumps(patch),
        )
    log.info("liveops.balance_patch_applied", game_id=game_id, changes=len(change_lines))
    return patch, change_lines
