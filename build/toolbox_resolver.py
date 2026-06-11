"""
ToolboxAssetResolver (spec 4.3) — resolves toolbox_keywords from the
concept JSON to real free Roblox Toolbox/Catalog asset IDs.

Strategy: search each keyword via the Toolbox marketplace API, filter for
free models, take top-3 by relevance/rating, append resolved_assets to
the concept JSON.
"""
import asyncio

import httpx
import structlog

log = structlog.get_logger()

# Toolbox service category 10 = free Models
TOOLBOX_SEARCH_URL = "https://apis.roblox.com/toolbox-service/v1/marketplace/10"
# Fallback: legacy catalog search
CATALOG_SEARCH_URL = "https://catalog.roblox.com/v1/search/items"

RESULTS_PER_KEYWORD = 3


class ToolboxAssetResolver:
    """Resolves concept toolbox_keywords to real asset ids."""

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

    async def _search_keyword(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        try:
            return await self._search_toolbox(client, keyword)
        except Exception as exc:
            log.debug("toolbox.primary_failed", keyword=keyword, error=str(exc))
            return await self._search_catalog(client, keyword)

    async def _search_toolbox(self, client: httpx.AsyncClient, keyword: str) -> list[dict]:
        resp = await client.get(
            TOOLBOX_SEARCH_URL,
            params={"keyword": keyword, "limit": 10},
        )
        resp.raise_for_status()
        data = resp.json()
        items = data.get("data", [])
        out = []
        for item in items[:RESULTS_PER_KEYWORD]:
            asset_id = item.get("id")
            if asset_id:
                out.append(
                    {
                        "keyword": keyword,
                        "asset_id": int(asset_id),
                        "name": item.get("name", keyword),
                    }
                )
        return out

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
