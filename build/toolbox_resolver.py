"""
ToolboxAssetResolver (spec 4.3) — resolves toolbox_keywords from the
concept JSON to real free Roblox Toolbox/Catalog asset IDs.

Strategy: for each keyword, fetch the top results from the Toolbox
marketplace API, pull their details (voting + free status), score each
result by rating x popularity, drop anything below a minimum quality bar,
and keep the highest scoring free models. Keywords that return nothing of
quality fall back to a curated, hand-verified list (toolbox_fallbacks.json)
so a build never ends up with zero or junk decoration assets.
"""
import asyncio
import json
import pathlib

import httpx
import structlog

log = structlog.get_logger()

# Toolbox service category 10 = free Models
TOOLBOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/10"
TOOLBOX_DETAILS_URL = "https://apis.roblox.com/toolbox-service/v1/items/details"
# Fallback: legacy catalog search
CATALOG_SEARCH_URL = "https://catalog.roblox.com/v1/search/items"

RESULTS_PER_KEYWORD = 3
# Pull a wider candidate pool than we keep so scoring has something to rank
CANDIDATE_POOL = 10
# Minimum quality bar: skip assets with fewer than this many votes
MIN_VOTES = 10

FALLBACKS_PATH = pathlib.Path(__file__).parent / "toolbox_fallbacks.json"


def _load_fallbacks() -> dict:
    try:
        return json.loads(FALLBACKS_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _score(voting: dict) -> float:
    """rating x (1 + popularity). upVotePercent is 0..100, voteCount is the
    favourite/popularity proxy the toolbox exposes per asset."""
    rating = (voting.get("upVotePercent") or 0) / 100.0
    votes = voting.get("voteCount") or 0
    return rating * (1 + votes / 1000.0)


class ToolboxAssetResolver:
    """Resolves concept toolbox_keywords to real asset ids."""

    def __init__(self) -> None:
        self._fallbacks = _load_fallbacks()

    async def resolve(self, concept: dict) -> dict:
        """Appends resolved_assets to the concept dict and returns it."""
        keywords = concept.get("toolbox_keywords", [])
        if not keywords:
            concept["resolved_assets"] = []
            return concept

        async with httpx.AsyncClient(
            timeout=30, headers={"User-Agent": "RobloxStudioBot/1.0"}
        ) as client:
            results = await asyncio.gather(
                *(self._search_keyword(client, kw) for kw in keywords),
                return_exceptions=True,
            )

        resolved: list[dict] = []
        for keyword, result in zip(keywords, results):
            if isinstance(result, Exception):
                log.warning("toolbox.keyword_failed", keyword=keyword, error=str(result))
                continue
            resolved.extend(result)

        concept["resolved_assets"] = resolved
        log.info("toolbox.resolved", keywords=len(keywords), assets=len(resolved))
        return concept

    def _fallback_for(self, keyword: str) -> dict | None:
        """Look up a hand-verified asset for this keyword (exact, then word
        overlap with a curated entry)."""
        kw = keyword.lower().strip()
        entry = self._fallbacks.get(kw)
        if not entry:
            for key, value in self._fallbacks.items():
                if key in kw or kw in key:
                    entry = value
                    break
        if not entry:
            return None
        return {
            "keyword": keyword,
            "asset_id": int(entry["asset_id"]),
            "name": entry.get("name", keyword),
            "source": "fallback",
        }

    async def _search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        # 1. Scored toolbox search (highest quality)
        try:
            results = await self._search_toolbox(client, keyword)
            if results:
                return results
        except Exception as exc:
            log.debug("toolbox.primary_failed", keyword=keyword, error=str(exc))
        # 2. Curated, hand-verified fallback — preferred over the noisy
        #    legacy catalog so a low-quality search never wins
        fb = self._fallback_for(keyword)
        if fb:
            log.info("toolbox.fallback_used", keyword=keyword, asset_id=fb["asset_id"])
            return [fb]
        # 3. Legacy catalog search as a last resort
        try:
            return await self._search_catalog(client, keyword)
        except Exception as exc:
            log.debug("toolbox.catalog_failed", keyword=keyword, error=str(exc))
            return []

    async def _search_toolbox(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        resp = await client.get(
            TOOLBOX_SEARCH_URL,
            params={"keyword": keyword, "limit": CANDIDATE_POOL},
        )
        resp.raise_for_status()
        data = resp.json()
        ids = [str(item["id"]) for item in data.get("data", []) if item.get("id")]
        if not ids:
            return []

        details_resp = await client.get(
            TOOLBOX_DETAILS_URL, params={"assetIds": ",".join(ids[:CANDIDATE_POOL])}
        )
        details_resp.raise_for_status()
        details = details_resp.json().get("data", [])

        scored: list[tuple[float, dict]] = []
        for item in details:
            asset = item.get("asset") or {}
            fiat = item.get("fiatProduct") or {}
            voting = item.get("voting") or {}
            asset_id = asset.get("id")
            if not asset_id:
                continue
            if not fiat.get("isFree", False):
                continue
            if asset.get("visibilityStatus") not in (None, 1):
                continue
            if (voting.get("voteCount") or 0) < MIN_VOTES:
                continue
            scored.append(
                (
                    _score(voting),
                    {
                        "keyword": keyword,
                        "asset_id": int(asset_id),
                        "name": asset.get("name", keyword),
                        "score": round(_score(voting), 4),
                    },
                )
            )

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [entry for _, entry in scored[:RESULTS_PER_KEYWORD]]

    async def _search_catalog(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        # TODO: catalog API covers marketplace items, not all toolbox models.
        # If both endpoints drift, swap to the develop API asset search.
        resp = await client.get(
            CATALOG_SEARCH_URL,
            params={
                "category": "Models",
                "keyword": keyword,
                "limit": 10,
                "salesTypeFilter": 1,  # free
                "sortType": 2,         # by rating
            },
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        out = []
        for item in items[:RESULTS_PER_KEYWORD]:
            asset_id = item.get("id")
            price = item.get("price") or 0
            if asset_id and price == 0:
                out.append(
                    {
                        "keyword": keyword,
                        "asset_id": int(asset_id),
                        "name": item.get("name", keyword),
                    }
                )
        return out
