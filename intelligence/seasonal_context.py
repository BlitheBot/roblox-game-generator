"""
SeasonalContext — date-based seasonal awareness for the pipeline.

Windows (checked in order; first match wins, so the more specific
Back to School window takes priority over the overlapping Summer one):

    Halloween       Oct 1  – Oct 31
    Christmas       Dec 1  – Dec 26
    Back to School  Aug 15 – Sep 15
    Summer          Jun 15 – Aug 31
    standard        everything else

ScoringEngine boosts season-matching concepts by 15%; ConceptGenerator
feeds the active season into its prompt so titles/items/descriptions
get themed accordingly.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

# 15% opportunity-score boost for season-matching concepts
SEASONAL_BOOST = 1.15


@dataclass(frozen=True)
class SeasonalContext:
    name: str                       # 'halloween' | 'christmas' | 'summer' | 'back_to_school' | 'standard'
    display_name: str
    # Substrings matched (case-insensitive) against a concept's genre /
    # trend text to decide whether it fits the season
    keywords: list[str] = field(default_factory=list)
    # Mechanic tags that inherently fit the season (e.g. horror at Halloween)
    matching_mechanics: list[str] = field(default_factory=list)
    # Free-text guidance handed to the ConceptGenerator prompt
    theming_hint: str = ""

    @property
    def is_seasonal(self) -> bool:
        return self.name != "standard"

    def matches_concept(self, mechanic_tag: str, *texts: str) -> bool:
        """True when a concept fits this season by mechanic or keyword."""
        if not self.is_seasonal:
            return False
        if mechanic_tag in self.matching_mechanics:
            return True
        blob = " ".join(t for t in texts if t).lower()
        return any(kw in blob for kw in self.keywords)


_SEASONS = [
    SeasonalContext(
        name="halloween",
        display_name="Halloween",
        keywords=["halloween", "spooky", "horror", "ghost", "zombie", "pumpkin",
                  "haunted", "witch", "skeleton", "monster"],
        matching_mechanics=["survival_horror"],
        theming_hint=(
            "It is Halloween season — favor spooky-but-family-friendly theming: "
            "haunted settings, ghosts, pumpkins, candy, costumes. Theme the title, "
            "items, and description around Halloween where it fits the mechanic."
        ),
    ),
    SeasonalContext(
        name="christmas",
        display_name="Christmas",
        keywords=["christmas", "winter", "santa", "snow", "holiday", "festive",
                  "elf", "reindeer", "gift", "present"],
        matching_mechanics=[],
        theming_hint=(
            "It is the Christmas/winter holiday season — favor festive theming: "
            "snow, gifts, elves, workshops, cozy winter settings. Theme the title, "
            "items, and description around the holidays where it fits the mechanic."
        ),
    ),
    SeasonalContext(
        name="back_to_school",
        display_name="Back to School",
        keywords=["school", "classroom", "teacher", "student", "campus", "college"],
        matching_mechanics=[],
        theming_hint=(
            "It is back-to-school season — school, campus, and classroom themes "
            "resonate right now. Theme the title, items, and description around "
            "school life where it fits the mechanic."
        ),
    ),
    SeasonalContext(
        name="summer",
        display_name="Summer",
        keywords=["summer", "beach", "island", "tropical", "vacation", "pool",
                  "surf", "ocean", "sun"],
        matching_mechanics=[],
        theming_hint=(
            "It is summer — beach, island, tropical, and vacation themes resonate "
            "right now. Theme the title, items, and description around summer "
            "where it fits the mechanic."
        ),
    ),
]

_STANDARD = SeasonalContext(name="standard", display_name="Standard")

# (start_month, start_day, end_month, end_day) inclusive, per season name —
# ordered so overlapping windows resolve to the more specific season first
_WINDOWS = [
    ("halloween",      (10, 1),  (10, 31)),
    ("christmas",      (12, 1),  (12, 26)),
    ("back_to_school", (8, 15),  (9, 15)),
    ("summer",         (6, 15),  (8, 31)),
]

_BY_NAME = {s.name: s for s in _SEASONS}


def _in_window(d: date, start: tuple[int, int], end: tuple[int, int]) -> bool:
    return (start <= (d.month, d.day) <= end)


def get_seasonal_context(today: date | None = None) -> SeasonalContext:
    """The active seasonal context for `today` (defaults to current UTC date)."""
    d = today or datetime.now(timezone.utc).date()
    for name, start, end in _WINDOWS:
        if _in_window(d, start, end):
            return _BY_NAME[name]
    return _STANDARD


def season_window_end(season_name: str, today: date | None = None) -> date:
    """The end date of the named season's current/next window."""
    d = today or datetime.now(timezone.utc).date()
    for name, start, end in _WINDOWS:
        if name != season_name:
            continue
        year = d.year
        if (d.month, d.day) > end:
            year += 1
        return date(year, end[0], end[1])
    raise ValueError(f"unknown season '{season_name}'")


def upcoming_season(within_days: int, today: date | None = None) -> SeasonalContext | None:
    """The active season, or one whose window opens within `within_days`;
    None when nothing is near. Used by LiveOps to pre-stage reskins."""
    d = today or datetime.now(timezone.utc).date()
    active = get_seasonal_context(d)
    if active.is_seasonal:
        return active
    best: tuple[int, str] | None = None
    for name, _, _ in _WINDOWS:
        days = days_until_season(name, d)
        if 0 < days <= within_days and (best is None or days < best[0]):
            best = (days, name)
    return _BY_NAME[best[1]] if best else None


def days_until_season(season_name: str, today: date | None = None) -> int:
    """Days until the named season's window opens next (0 when active).
    Used by LiveOps to pre-stage reskins shortly before a window opens."""
    d = today or datetime.now(timezone.utc).date()
    for name, start, end in _WINDOWS:
        if name != season_name:
            continue
        if _in_window(d, start, end):
            return 0
        opens = date(d.year, start[0], start[1])
        if opens < d:
            opens = date(d.year + 1, start[0], start[1])
        return (opens - d).days
    raise ValueError(f"unknown season '{season_name}'")
