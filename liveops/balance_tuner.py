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


async def tune_monetization(
    pool: asyncpg.Pool, game: dict, concept: dict
) -> list[str]:
    """Monetization balance rules (improvement 9 step 7). Applied changes
    land in balance_history with metric_trigger 'monetization_*'.

    Data reality: Roblox exposes no per-player purchase analytics via
    API, so two of the requested rules run on proxies and two are
    insufficient-data stubs until the Analytics API ships them:
      * first-session purchase rate → proxied by zero recorded revenue
        across 7+ days with real traffic → starter pack price drops to 79
      * limited-item sellout speed → read from the game's
        MonetizationGlobal_v1 DataStore via Open Cloud → next batch stock
        shrinks 25% when everything sold out within the first week
      * season-pass conversion and flash-sale conversion → no data
        source exists; logged and skipped (push notifications to
        non-buyers also have no Roblox API)
    """
    changes: list[str] = []
    monetization = concept.setdefault("monetization", {})
    game_id = game["game_id"]

    # Rule 1: zero revenue despite traffic → starter pack to 79 Robux
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT SUM(revenue_robux) AS revenue, AVG(ccu) AS avg_ccu,
                   COUNT(*) AS samples
            FROM game_metrics
            WHERE game_id = $1 AND timestamp > $2
            """,
            uuid.UUID(game_id),
            cutoff,
        )
    casual = monetization.setdefault("casual_tier", {})
    if (
        row
        and (row["samples"] or 0) >= 100
        and float(row["avg_ccu"] or 0) >= 3
        and int(row["revenue"] or 0) == 0
        and casual.get("starter_pack_price", 99) > 79
    ):
        casual["starter_pack_price"] = 79
        change = "starter pack price 99 → 79 Robux (traffic but zero recorded revenue)"
        changes.append(change)
        await _log_monetization_change(
            pool, game_id, "monetization_first_session_conversion", change, casual
        )

    # Rule 2: limited items all sold out quickly → tighter next batch
    try:
        sellout = await _limited_sellout_check(game, monetization)
    except Exception as exc:
        log.info("liveops.monetization.stock_check_unavailable", error=str(exc))
        sellout = False
    if sellout:
        whale = monetization.setdefault("whale_tier", {})
        for item in whale.get("limited_items", []):
            item["stock"] = max(25, int(int(item.get("stock", 100)) * 0.75))
        change = "limited items sold out within a week — next batch stock reduced 25%"
        changes.append(change)
        await _log_monetization_change(
            pool, game_id, "monetization_limited_scarcity", change, whale
        )

    # Rules 3 & 4: no data source yet (Analytics API gap)
    log.info(
        "liveops.monetization.conversion_rules_skipped",
        reason="season-pass / flash-sale conversion not exposed by any Roblox API",
    )
    return changes


async def _limited_sellout_check(game: dict, monetization: dict) -> bool:
    """True when every limited item's Open Cloud DataStore stock counter
    has reached its cap and the game is less than 7 days old."""
    import httpx

    from publish.open_cloud_publisher import APIS_BASE, dry_run_enabled, load_genre_account

    items = monetization.get("whale_tier", {}).get("limited_items", [])
    if not items or dry_run_enabled():
        return False
    account = load_genre_account(game["genre_account"])
    async with httpx.AsyncClient(timeout=30) as client:
        for item in items:
            resp = await client.get(
                f"{APIS_BASE}/datastores/v1/universes/{account.universe_id}"
                f"/standard-datastores/datastore/entries/entry",
                params={
                    "datastoreName": "MonetizationGlobal_v1",
                    "entryKey": f"stock_{item['name']}",
                },
                headers={"x-api-key": account.api_key},
            )
            if resp.status_code != 200:
                return False  # counter missing → nothing sold yet
            sold = int(resp.json() or 0)
            if sold < int(item.get("stock", 0)):
                return False
    return True


async def _log_monetization_change(
    pool: asyncpg.Pool, game_id: str, trigger: str, description: str, patch: dict
) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO balance_history
                (game_id, metric_trigger, change_description, patch_json)
            VALUES ($1, $2, $3, $4)
            """,
            uuid.UUID(game_id),
            trigger,
            description[:1000],
            json.dumps(patch),
        )


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
