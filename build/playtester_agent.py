"""
PlaytesterAgent (Improvement 1) — simulates gameplay before publishing.

Runs after AutoValidator passes and before the ApprovalGate. Simulates ~10
minutes of new-player progression *mathematically* from the concept JSON and
its balance knobs — it never runs Roblox code — to catch economies that are
too tight or too loose, weak new-player experiences, and pushy monetization.

Score bands (see PlaytesterAgent.run):
  8.0-10.0  publish immediately
  6.0-7.9   publish, with a note in the Discord approval message
  4.0-5.9   regenerate the concept once and rebuild (handled by the pipeline)
  0.0-3.9   discard the concept entirely
"""
import pathlib
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger()


class PlaytestRejected(Exception):
    """Raised when a playtest scores below the discard threshold (<4.0). The
    pipeline discards the concept entirely — no retry, no model escalation."""

    def __init__(self, result: "PlaytestResult") -> None:
        self.result = result
        super().__init__(f"playtest score {result.score:.1f}: {result.verdict}")


@dataclass
class PlaytestResult:
    passed: bool
    score: float  # 0.0 to 10.0
    flags: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    economy_balance: str = "balanced"          # too_tight | balanced | too_loose
    new_player_experience: str = "good"        # frustrating | good | too_easy
    estimated_session_length_minutes: float = 0.0
    time_to_first_upgrade_minutes: float = 0.0
    monetization_pressure: str = "fair"        # none | fair | pushy
    verdict: str = ""

    def to_json(self) -> dict:
        return {
            "passed": self.passed,
            "score": round(self.score, 1),
            "flags": self.flags,
            "recommendations": self.recommendations,
            "economy_balance": self.economy_balance,
            "new_player_experience": self.new_player_experience,
            "estimated_session_length_minutes": round(self.estimated_session_length_minutes, 1),
            "time_to_first_upgrade_minutes": round(self.time_to_first_upgrade_minutes, 1),
            "monetization_pressure": self.monetization_pressure,
            "verdict": self.verdict,
        }


def _num(balance: dict, key: str, default: float) -> float:
    try:
        return float(balance.get(key, default))
    except (TypeError, ValueError):
        return default


def _cheapest_shop_price(concept: dict, default: int) -> int:
    prices = [
        int(i["price"])
        for i in concept.get("monetization", {}).get("shop_items", [])
        if str(i.get("price", "")).lstrip("-").isdigit()
    ]
    return min(prices) if prices else default


def _has_coin_doubler(concept: dict) -> bool:
    passes = concept.get("monetization", {}).get("game_passes", [])
    for gp in passes:
        text = f"{gp.get('name', '')} {gp.get('benefit', '')} {gp.get('effect', '')}".lower()
        if "2x" in text or "double" in text or "income_x2" in text:
            return True
    return False


def _verdict(score: float, mechanic: str, economy: str, npe: str) -> str:
    quality = (
        "Excellent" if score >= 8 else
        "Solid" if score >= 6 else
        "Needs work" if score >= 4 else
        "Poor"
    )
    return f"{quality} {mechanic} — {economy} economy, {npe} new player experience"


class PlaytesterAgent:
    async def run(self, concept: dict, build_dir: pathlib.Path | None = None) -> PlaytestResult:
        mechanic = concept.get("mechanic_tag", "")
        if mechanic == "idle_tycoon":
            result = self.simulate_idle_tycoon(concept)
        elif mechanic == "pet_collect":
            result = self.simulate_pet_collect(concept)
        elif mechanic == "survival_horror":
            result = self.simulate_survival_horror(concept)
        elif mechanic == "incremental_sim":
            result = self.simulate_incremental_sim(concept)
        else:
            # No dedicated simulation (obby/rpg fall back to a base template) —
            # do a generic completeness pass rather than block the build.
            result = self._simulate_generic(concept)
        log.info(
            "playtester.complete",
            mechanic=mechanic,
            score=round(result.score, 1),
            economy=result.economy_balance,
            npe=result.new_player_experience,
        )
        return result

    # ── idle_tycoon ─────────────────────────────────────────
    def simulate_idle_tycoon(self, concept: dict) -> PlaytestResult:
        balance = concept.get("balance", {}) or {}
        income = max(0.01, _num(balance, "base_income_per_second", 1))
        starting = _num(balance, "starting_currency", 0)
        first_cost = _cheapest_shop_price(concept, 100)

        ttf_min = max(0.0, (first_cost - starting) / income) / 60.0
        systems = concept.get("systems", [])
        shop_items = concept.get("monetization", {}).get("shop_items", [])
        decisions = len(systems) + len(shop_items)

        flags: list[str] = []
        recs: list[str] = []
        score = 10.0
        economy = "balanced"

        if ttf_min > 5:
            flags.append(f"economy too tight — first upgrade takes {ttf_min:.1f} min")
            recs.append("Raise base_income_per_second or lower the cheapest shop item price")
            score -= 2.0
            economy = "too_tight"
        elif ttf_min < 0.5:
            flags.append(f"economy too loose — first upgrade in {ttf_min:.1f} min")
            recs.append("Lower base_income_per_second so early upgrades feel earned")
            score -= 1.5
            economy = "too_loose"

        # Prestige pacing: approximate a prestige milestone at ~40x first cost.
        prestige_min = (first_cost * 40 - starting) / income / 60.0
        if prestige_min < 10:
            flags.append("prestige reachable too fast (<10 min) — feels unearned")
            recs.append("Increase the prestige requirement")
            score -= 1.0
            if economy == "balanced":
                economy = "too_loose"

        # Decision density
        if decisions < 3:
            flags.append(f"only {decisions} meaningful early decisions — feels passive")
            recs.append("Add more upgrades/plots/systems for the first 10 minutes")
            score -= 2.0

        # Monetization fairness (2x coins pass should matter but not be required)
        monetization_pressure = "fair"
        if not _has_coin_doubler(concept):
            recs.append("Add a 2x coins game pass — the genre's core conversion driver")
            monetization_pressure = "none"
            score -= 0.5
        elif ttf_min > 8:
            monetization_pressure = "pushy"
            flags.append("grind is long enough that the 2x pass feels necessary, not optional")
            score -= 0.5

        npe = "frustrating" if economy == "too_tight" else "too_easy" if economy == "too_loose" else "good"
        session = min(20.0, max(4.0, 6 + decisions))
        score = max(0.0, min(10.0, score))
        return PlaytestResult(
            passed=score >= 4.0,
            score=score,
            flags=flags,
            recommendations=recs,
            economy_balance=economy,
            new_player_experience=npe,
            estimated_session_length_minutes=session,
            time_to_first_upgrade_minutes=ttf_min,
            monetization_pressure=monetization_pressure,
            verdict=_verdict(score, "idle tycoon", economy, npe),
        )

    # ── pet_collect ─────────────────────────────────────────
    def simulate_pet_collect(self, concept: dict) -> PlaytestResult:
        balance = concept.get("balance", {}) or {}
        starting = _num(balance, "pet_starting_currency", 250)
        first_egg_cost = _num(balance, "first_egg_cost", _cheapest_shop_price(concept, 100))
        income = max(0.01, _num(balance, "base_income_per_second", 1))

        time_to_first_egg_min = max(0.0, (first_egg_cost - starting) / income) / 60.0

        flags: list[str] = []
        recs: list[str] = []
        score = 10.0
        economy = "balanced"

        if time_to_first_egg_min > 4:
            flags.append(f"first egg barrier too high — {time_to_first_egg_min:.1f} min")
            recs.append("Lower the first egg cost or raise pet starting currency")
            score -= 2.0
            economy = "too_tight"
        elif time_to_first_egg_min < 0.25:
            economy = "too_loose"
            score -= 1.0

        # First-session reward: chance of a non-Common in first 5 opens.
        # Assume a typical 70% Common base rate unless concept overrides.
        common_rate = _num(balance, "common_drop_rate", 0.70)
        p_noncommon_in_5 = 1 - common_rate ** 5
        if p_noncommon_in_5 < 0.40:
            flags.append(f"first session too disappointing — {p_noncommon_in_5:.0%} chance of a non-Common in 5 opens")
            recs.append("Lower the Common drop rate or boost early-open luck for new players")
            score -= 1.5

        # Aspiration: a Legendary (or better) must exist to create a chase goal.
        pools = concept.get("pet_name_pools") or {}
        has_chase = any(r in pools for r in ("Legendary", "Mythic", "Epic")) or _mentions(concept, "legendary")
        if not has_chase:
            flags.append("no visible top-tier (Legendary/Mythic) chase pet")
            recs.append("Add a Legendary/Mythic tier so new players have an 'I want THAT' moment")
            score -= 1.5

        # Trading accessibility
        min_trade_value = _num(balance, "min_tradeable_value", 0)
        if min_trade_value > 500:
            flags.append("trading locked out too long (min tradeable value > 500)")
            recs.append("Lower the minimum tradeable value")
            score -= 1.0

        monetization_pressure = "fair" if _mentions(concept, "luck") or concept.get("monetization", {}).get("game_passes") else "none"
        npe = "frustrating" if economy == "too_tight" else "good"
        score = max(0.0, min(10.0, score))
        return PlaytestResult(
            passed=score >= 4.0,
            score=score,
            flags=flags,
            recommendations=recs,
            economy_balance=economy,
            new_player_experience=npe,
            estimated_session_length_minutes=min(20.0, max(4.0, 8 + len(concept.get("systems", [])))),
            time_to_first_upgrade_minutes=time_to_first_egg_min,
            monetization_pressure=monetization_pressure,
            verdict=_verdict(score, "pet collector", economy, npe),
        )

    # ── survival_horror ─────────────────────────────────────
    def simulate_survival_horror(self, concept: dict) -> PlaytestResult:
        balance = concept.get("balance", {}) or {}
        round_seconds = _num(balance, "round_seconds", 120)
        survival_reward = _num(balance, "survival_reward", 50)
        kill_reward = _num(balance, "kill_reward", 10)
        first_cost = _cheapest_shop_price(concept, 100)

        coins_per_min_survivor = (survival_reward / (round_seconds / 60.0)) if round_seconds else 0

        flags: list[str] = []
        recs: list[str] = []
        score = 10.0
        economy = "balanced"

        if coins_per_min_survivor < 5:
            flags.append(f"survival reward too low — {coins_per_min_survivor:.1f} coins/min")
            recs.append("Raise survival_reward or shorten the round")
            score -= 2.0
            economy = "too_tight"

        if kill_reward <= 0:
            flags.append("zero kill reward — low-skill players who die earn nothing")
            recs.append("Give a small kill/participation reward so losing still progresses")
            score -= 1.5
            economy = "too_tight"

        if not (90 <= round_seconds <= 180):
            flags.append(f"round length {round_seconds:.0f}s outside the compelling 90-180s window")
            recs.append("Tune round length into the 90-180 second range for replayability")
            score -= 1.0

        if survival_reward < 3 * kill_reward:
            flags.append("winning barely beats losing — survival should reward ≥3x a kill")
            recs.append("Increase the survival reward relative to the kill reward")
            score -= 1.0

        time_to_first = (first_cost / max(1.0, coins_per_min_survivor)) if coins_per_min_survivor else 99
        npe = "frustrating" if economy == "too_tight" else "good"
        monetization_pressure = "fair" if concept.get("monetization", {}).get("game_passes") else "none"
        score = max(0.0, min(10.0, score))
        return PlaytestResult(
            passed=score >= 4.0,
            score=score,
            flags=flags,
            recommendations=recs,
            economy_balance=economy,
            new_player_experience=npe,
            estimated_session_length_minutes=min(20.0, max(4.0, round_seconds / 60.0 * 4)),
            time_to_first_upgrade_minutes=time_to_first,
            monetization_pressure=monetization_pressure,
            verdict=_verdict(score, "survival horror", economy, npe),
        )

    # ── incremental_sim ─────────────────────────────────────
    def simulate_incremental_sim(self, concept: dict) -> PlaytestResult:
        balance = concept.get("balance", {}) or {}
        growth = max(0.01, _num(balance, "base_growth_per_tick", 1))
        sell_value = max(0.01, _num(balance, "base_sell_value", 1))
        first_cost = _cheapest_shop_price(concept, 100)
        rate_per_sec = growth * sell_value

        flags: list[str] = []
        recs: list[str] = []
        score = 10.0
        economy = "balanced"

        # Wins per 10 minutes: how many affordable upgrades at a doubling curve.
        wins = 0
        cost = first_cost
        budget = rate_per_sec * 600
        spent = 0.0
        while spent + cost <= budget and wins < 30:
            spent += cost
            wins += 1
            cost *= 1.5
        if wins < 5:
            flags.append(f"only ~{wins} upgrades in 10 min — not enough small wins")
            recs.append("Lower early upgrade costs or raise base growth for a win every ~90s")
            score -= 2.0
            economy = "too_tight"
        elif wins > 12:
            flags.append(f"~{wins} upgrades in 10 min — progression too loose")
            recs.append("Steepen the upgrade cost curve")
            score -= 1.0
            economy = "too_loose"

        # Rebirth pacing (target 20-40 min)
        rebirth_min = (first_cost * 60) / max(1.0, rate_per_sec) / 60.0
        if rebirth_min < 10:
            flags.append("rebirth too easy (<10 min)")
            recs.append("Raise the rebirth requirement")
            score -= 1.0
        elif rebirth_min > 60:
            flags.append("rebirth too slow (>60 min)")
            recs.append("Lower the rebirth requirement")
            score -= 1.0

        rebirth_mult = _num(balance, "rebirth_multiplier", 2.0)
        if rebirth_mult < 1.5:
            flags.append("rebirth multiplier <1.5x — rebirth doesn't feel impactful")
            recs.append("Set the post-rebirth multiplier to at least 1.5x")
            score -= 1.0

        npe = "frustrating" if economy == "too_tight" else "too_easy" if economy == "too_loose" else "good"
        score = max(0.0, min(10.0, score))
        return PlaytestResult(
            passed=score >= 4.0,
            score=score,
            flags=flags,
            recommendations=recs,
            economy_balance=economy,
            new_player_experience=npe,
            estimated_session_length_minutes=min(20.0, max(4.0, wins * 1.2)),
            time_to_first_upgrade_minutes=(first_cost / rate_per_sec / 60.0) if rate_per_sec else 99,
            monetization_pressure="fair" if concept.get("monetization", {}).get("game_passes") else "none",
            verdict=_verdict(score, "incremental sim", economy, npe),
        )

    def _simulate_generic(self, concept: dict) -> PlaytestResult:
        systems = concept.get("systems", [])
        has_money = bool(concept.get("monetization", {}).get("game_passes"))
        score = 6.0 + (1.0 if len(systems) >= 3 else -1.0) + (1.0 if has_money else -1.0)
        score = max(0.0, min(10.0, score))
        return PlaytestResult(
            passed=score >= 4.0,
            score=score,
            economy_balance="balanced",
            new_player_experience="good",
            estimated_session_length_minutes=8.0,
            verdict=_verdict(score, "game", "balanced", "good"),
        )


def _mentions(concept: dict, term: str) -> bool:
    import json

    return term.lower() in json.dumps(concept).lower()
