"""Small shared utilities."""
import re

_KEY_PARAM_RE = re.compile(r"(key|api_key|apikey|access_token|token|refresh_token)=[^&\s]+", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Redact credential-bearing query params from a URL before logging.

    All API credentials in this codebase are sent via headers or POST
    bodies, so URLs are not expected to carry keys today — this is a
    defensive guard so a future URL-param credential never lands in logs.
    """
    if not url:
        return url
    return _KEY_PARAM_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", url)
