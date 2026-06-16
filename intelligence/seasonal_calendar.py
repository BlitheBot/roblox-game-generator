"""
SeasonalCalendar — predicts and prepares for seasonal meta shifts.

The Roblox meta shifts predictably around holidays and cultural events. This
module maintains a 12-month forward calendar and lets the system prepare games
weeks before a seasonal peak instead of reacting once it arrives.

This is additive to intelligence.seasonal_context (which LiveOps still uses for
reskins): the calendar provides forward-looking mechanic boosts, concept theme
injection, and preparation alerts.

Historical pattern analysis:
- Halloween: traffic +40-60% in last 2 weeks of October
- Christmas: traffic +50-80% December 20-26
- Summer: sustained +20% June 15 - August 31
- Back to School: +15% first 2 weeks of September
- Valentine's: +25% February 10-14
- Spring Break: +30% mid-March to mid-April (US)
- New Year: +45% December 31 - January 2
"""
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import structlog

log = structlog.get_logger()


@dataclass
class SeasonalEvent:
    name: str
    start_date: date
    end_date: date
    traffic_multiplier: float      # expected CCU boost
    prep_days_before: int          # how many days before to start building
    mechanic_boost: dict           # which mechanics benefit most
    concept_themes: list[str]      # themes to inject into concept generation
    thumbnail_style: str           # special thumbnail guidance
    priority: int                  # 1=highest priority, 3=lowest


# Full 12-month calendar (rolls forward each year — see _calendar_for_year)
def _build_calendar(year: int) -> list[SeasonalEvent]:
    return [
        SeasonalEvent(
            name="Valentine's Day",
            start_date=date(year, 2, 10),
            end_date=date(year, 2, 14),
            traffic_multiplier=1.25,
            prep_days_before=21,
            mechanic_boost={"pet_collect": 1.3, "idle_tycoon": 1.1},
            concept_themes=["love", "hearts", "pink", "flowers", "romance", "cupid"],
            thumbnail_style="hearts and pink/red color scheme, cute and warm",
            priority=2,
        ),
        SeasonalEvent(
            name="Spring Break",
            start_date=date(year, 3, 14),
            end_date=date(year, 4, 4),
            traffic_multiplier=1.30,
            prep_days_before=21,
            mechanic_boost={"survival_horror": 1.2, "idle_tycoon": 1.2, "pet_collect": 1.2},
            concept_themes=["spring", "adventure", "outdoors", "freedom", "vacation"],
            thumbnail_style="bright spring colors, outdoor adventure feel",
            priority=2,
        ),
        SeasonalEvent(
            name="Summer",
            start_date=date(year, 6, 15),
            end_date=date(year, 8, 31),
            traffic_multiplier=1.20,
            prep_days_before=28,
            mechanic_boost={"idle_tycoon": 1.2, "pet_collect": 1.3, "incremental_sim": 1.2},
            concept_themes=["beach", "tropical", "island", "ocean", "summer", "sunshine"],
            thumbnail_style="bright sunny tropical colors, beach vibes",
            priority=1,
        ),
        SeasonalEvent(
            name="Back to School",
            start_date=date(year, 8, 25),
            end_date=date(year, 9, 10),
            traffic_multiplier=1.15,
            prep_days_before=21,
            mechanic_boost={"idle_tycoon": 1.1, "incremental_sim": 1.2},
            concept_themes=["school", "learning", "books", "campus", "study"],
            thumbnail_style="school colors, academic feel",
            priority=3,
        ),
        SeasonalEvent(
            name="Halloween",
            start_date=date(year, 10, 15),
            end_date=date(year, 10, 31),
            traffic_multiplier=1.50,
            prep_days_before=28,
            mechanic_boost={"survival_horror": 1.8, "pet_collect": 1.3, "idle_tycoon": 1.2},
            concept_themes=["spooky", "halloween", "ghost", "pumpkin", "horror", "candy", "witch"],
            thumbnail_style="dark orange and black, spooky atmosphere, jack-o-lanterns",
            priority=1,
        ),
        SeasonalEvent(
            name="Thanksgiving",
            start_date=date(year, 11, 23),
            end_date=date(year, 11, 27),
            traffic_multiplier=1.35,
            prep_days_before=21,
            mechanic_boost={"idle_tycoon": 1.3, "incremental_sim": 1.2},
            concept_themes=["harvest", "farm", "turkey", "feast", "autumn", "grateful"],
            thumbnail_style="warm autumn colors, harvest feel",
            priority=2,
        ),
        SeasonalEvent(
            name="Christmas",
            start_date=date(year, 12, 18),
            end_date=date(year, 12, 26),
            traffic_multiplier=1.75,
            prep_days_before=35,
            mechanic_boost={"idle_tycoon": 1.5, "pet_collect": 1.6, "incremental_sim": 1.4},
            concept_themes=["christmas", "snow", "santa", "presents", "winter", "holiday", "elf"],
            thumbnail_style="red and green Christmas colors, snow, festive and cheerful",
            priority=1,
        ),
        SeasonalEvent(
            name="New Year",
            start_date=date(year, 12, 30),
            end_date=date(year + 1, 1, 2),
            traffic_multiplier=1.45,
            prep_days_before=14,
            mechanic_boost={"idle_tycoon": 1.3, "incremental_sim": 1.4},
            concept_themes=["new year", "fireworks", "countdown", "celebration", str(year + 1)],
            thumbnail_style="gold and sparkles, fireworks, celebratory",
            priority=1,
        ),
    ]


def _relevant_calendar(today: date) -> list[SeasonalEvent]:
    """This year's events plus next year's early-Q1 events, so prep windows
    that straddle the New Year are always visible."""
    return _build_calendar(today.year) + _build_calendar(today.year + 1)


def get_upcoming_events(days_ahead: int = 35, today: Optional[date] = None) -> list[SeasonalEvent]:
    """Seasonal events currently inside their prep window (prep_start ≤ today ≤
    end). `days_ahead` bounds how far out the prep window may reach."""
    today = today or date.today()
    upcoming = []
    for event in _relevant_calendar(today):
        prep_start = event.start_date - timedelta(days=min(event.prep_days_before, days_ahead))
        if prep_start <= today <= event.end_date:
            upcoming.append(event)
    return sorted(upcoming, key=lambda e: e.priority)


def get_active_event(today: Optional[date] = None) -> Optional[SeasonalEvent]:
    """The currently active seasonal event, if any."""
    today = today or date.today()
    for event in _relevant_calendar(today):
        if event.start_date <= today <= event.end_date:
            return event
    return None


def get_seasonal_boost_for_mechanic(mechanic_tag: str, today: Optional[date] = None) -> float:
    """Current seasonal multiplier for a mechanic tag (1.0 off-season). Used by
    ScoringEngine to boost seasonal opportunities; upcoming events get half the
    boost so the system leans into a season before it fully arrives."""
    today = today or date.today()
    active = get_active_event(today)
    if not active:
        upcoming = get_upcoming_events(days_ahead=14, today=today)
        if upcoming:
            event = upcoming[0]
            return 1.0 + (event.mechanic_boost.get(mechanic_tag, 1.0) - 1.0) * 0.5
        return 1.0
    return active.mechanic_boost.get(mechanic_tag, 1.0)


def get_seasonal_concept_context(today: Optional[date] = None) -> dict:
    """Seasonal context to inject into ConceptGenerator."""
    today = today or date.today()
    active = get_active_event(today)
    upcoming = get_upcoming_events(days_ahead=21, today=today)

    if active:
        return {
            "is_seasonal": True,
            "event_name": active.name,
            "themes": active.concept_themes,
            "thumbnail_style": active.thumbnail_style,
            "traffic_multiplier": active.traffic_multiplier,
            "urgency": "high",  # active event — build now
        }
    if upcoming:
        event = upcoming[0]
        days_until = (event.start_date - today).days
        return {
            "is_seasonal": True,
            "event_name": event.name,
            "themes": event.concept_themes,
            "thumbnail_style": event.thumbnail_style,
            "traffic_multiplier": event.traffic_multiplier,
            "urgency": "prepare",  # upcoming — build in advance
            "days_until_start": days_until,
        }
    return {
        "is_seasonal": False,
        "event_name": None,
        "themes": [],
        "thumbnail_style": "vibrant and eye-catching",
        "traffic_multiplier": 1.0,
        "urgency": "standard",
    }


class SeasonalPreparationAlert:
    """Sends Discord alerts when seasonal opportunities are approaching. Runs
    daily as part of the orchestrator (07:00 UTC)."""

    ALERT_DAYS_BEFORE = [35, 21, 14, 7]  # alert at these many days before an event

    async def check_and_alert(self, pool, reporter, today: Optional[date] = None) -> None:
        """Check whether any seasonal event needs a preparation alert today."""
        today = today or date.today()

        for event in _relevant_calendar(today):
            for alert_days in self.ALERT_DAYS_BEFORE:
                if today != event.start_date - timedelta(days=alert_days):
                    continue
                key = f"seasonal_alert:{event.name}:{event.start_date.year}:{alert_days}"
                async with pool.acquire() as conn:
                    already = await conn.fetchval(
                        "SELECT 1 FROM orchestrator_state WHERE key = $1", key
                    )
                if already:
                    continue
                await self._send_alert(reporter, event, alert_days)
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO orchestrator_state (key, value, updated_at)
                        VALUES ($1, 'sent', NOW())
                        ON CONFLICT (key) DO UPDATE SET value='sent', updated_at=NOW()
                        """,
                        key,
                    )

    async def _send_alert(self, reporter, event: SeasonalEvent, days_before: int) -> None:
        urgency_emoji = "🚨" if days_before <= 7 else "📅" if days_before <= 14 else "ℹ️"
        top_mechanics = sorted(
            event.mechanic_boost.items(), key=lambda x: x[1], reverse=True
        )[:2]
        mechanic_text = " | ".join(
            f"{m} (+{int((b - 1) * 100)}%)" for m, b in top_mechanics
        )
        await reporter.alert(
            f"{urgency_emoji} Seasonal Opportunity: **{event.name}** in {days_before} days\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 Active: {event.start_date.strftime('%b %d')} → {event.end_date.strftime('%b %d')}\n"
            f"📈 Expected traffic boost: +{int((event.traffic_multiplier - 1) * 100)}%\n"
            f"🎮 Best mechanics: {mechanic_text}\n"
            f"🎨 Theme: {', '.join(event.concept_themes[:4])}\n"
            f"🖼️ Thumbnail style: {event.thumbnail_style}\n"
            + (
                "⚡ BUILD NOW — event starts soon!"
                if days_before <= 7
                else "💡 Recommended: start building seasonal games now"
            )
        )
