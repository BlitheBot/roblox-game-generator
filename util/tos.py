"""
Shared TOS content screening (Bug 1).

Single source of truth for the blocked-terms list and the scanning helper.
Kept dependency-free (stdlib only) so it can be imported from the
intelligence, build, and publish layers without creating import cycles.

A TOS hit is a *content* issue, not a code-quality issue: callers discard
the offending concept immediately (no retry, no model escalation).
"""
import re

# TOS blocked terms — weapons realism, adult content, violence/gore, drugs,
# gambling, scam-bait, and hate. Matched case-insensitively on word
# boundaries against concept JSON and all generated Luau source. Keep this
# list as the canonical definition; build.auto_validator re-imports it.
BLOCKED_TERMS = [
    # Weapons realism
    "glock", "ar-15", "ak-47", "uzi", "9mm", "shotgun shell", "hollow point",
    "armor piercing", "magazine clip", "suppressor", "silencer", "pistol grip",
    # Adult content
    "sex", "nude", "naked", "porn", "nsfw", "strip club", "condo game",
    "explicit", "adult only",
    # Violence/gore
    "gore", "beheading", "dismember", "suicide", "self harm", "decapitate",
    "torture", "mutilate",
    # Drugs
    "cocaine", "heroin", "meth", "weed", "marijuana", "cannabis", "drug deal",
    "narcotics",
    # Gambling
    "casino", "gambling", "poker chips", "slot machine", "betting",
    # Scam bait
    "free robux", "robux generator", "robux hack", "account giveaway",
    # Hate
    "nazi", "kkk", "white power", "hate speech",
]

_BLOCKED_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in BLOCKED_TERMS) + r")\b", re.IGNORECASE
)


def scan_for_blocked_term(text: str) -> str | None:
    """Return the first blocked term found in `text` (the matched substring),
    or None when the text is clean."""
    if not text:
        return None
    match = _BLOCKED_RE.search(text)
    return match.group(0) if match else None


class TOSViolation(Exception):
    """Raised when a concept (or its generated build) contains TOS-blocked
    content. Signals the build pipeline to discard the concept permanently —
    it is never retried and never escalated to a stronger model."""

    def __init__(self, term: str, game_title: str) -> None:
        self.term = term
        self.game_title = game_title or "Untitled"
        super().__init__(f"TOS blocked term '{term}' in '{self.game_title}'")
