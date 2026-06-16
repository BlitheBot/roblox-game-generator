"""
AssetVerifier (PART A FIX 5) — verifies Toolbox asset IDs are still free and
available before they are baked into a build, and keeps toolbox_fallbacks.json
fresh.

Two entry points:
- verify_concept_assets(concept): drops resolved_assets that are no longer
  free/visible, so LuauAgent never bakes a dead id into Config.
- refresh_fallbacks(): re-checks every id in toolbox_fallbacks.json and rewrites
  the file without the ones that have gone private/paid (run weekly).

Fails open: if the Toolbox API is unreachable, nothing is dropped (a transient
API outage must not strip a build of its decorations).
"""
import json
import pathlib

import httpx
import structlog

log = structlog.get_logger()

TOOLBOX_DETAILS_URL = "https://apis.roblox.com/toolbox-service/v1/items/details"
FALLBACKS_PATH = pathlib.Path(__file__).parent / "toolbox_fallbacks.json"


class AssetVerifier:
    """Validates Toolbox asset ids against the live details API."""

    async def verify_ids(self, ids: list[int]) -> dict[int, bool]:
        """Return {asset_id: is_valid}. is_valid means free + visible. On any
        API error, every queried id is reported valid (fail open)."""
        result: dict[int, bool] = {int(i): True for i in ids}
        if not ids:
            return result
        try:
            async with httpx.AsyncClient(
                timeout=30, headers={"User-Agent": "RobloxStudioBot/1.0"}
            ) as client:
                resp = await client.get(
                    TOOLBOX_DETAILS_URL,
                    params={"assetIds": ",".join(str(int(i)) for i in ids)},
                )
                resp.raise_for_status()
                data = resp.json().get("data", [])
        except Exception as exc:
            log.warning("asset_verifier.api_failed", error=str(exc))
            return result  # fail open

        seen: set[int] = set()
        for item in data:
            asset = item.get("asset") or {}
            fiat = item.get("fiatProduct") or {}
            asset_id = asset.get("id")
            if asset_id is None:
                continue
            asset_id = int(asset_id)
            seen.add(asset_id)
            free = bool(fiat.get("isFree", False))
            visible = asset.get("visibilityStatus") in (None, 1)
            result[asset_id] = free and visible
        # Ids the details call omitted entirely are treated as unavailable
        for i in result:
            if i not in seen and data:
                result[i] = False
        return result

    async def verify_concept_assets(self, concept: dict) -> dict:
        """Drop resolved_assets whose ids are no longer free/visible."""
        resolved = concept.get("resolved_assets") or []
        ids = [int(a["asset_id"]) for a in resolved if str(a.get("asset_id", "")).isdigit()]
        if not ids:
            return concept
        validity = await self.verify_ids(ids)
        kept = [a for a in resolved if validity.get(int(a.get("asset_id", -1)), True)]
        dropped = len(resolved) - len(kept)
        if dropped:
            log.info("asset_verifier.dropped_invalid", dropped=dropped, kept=len(kept))
        concept["resolved_assets"] = kept
        return concept

    async def refresh_fallbacks(self, path: pathlib.Path | None = None) -> int:
        """Re-validate every fallback id; rewrite the file without dead ones.
        Returns the number removed."""
        path = path or FALLBACKS_PATH
        try:
            fallbacks = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return 0
        ids = [int(v["asset_id"]) for v in fallbacks.values() if str(v.get("asset_id", "")).isdigit()]
        validity = await self.verify_ids(ids)
        kept = {
            kw: v
            for kw, v in fallbacks.items()
            if validity.get(int(v.get("asset_id", -1)), True)
        }
        removed = len(fallbacks) - len(kept)
        if removed:
            path.write_text(json.dumps(kept, indent=2), encoding="utf-8")
            log.info("asset_verifier.fallbacks_refreshed", removed=removed, kept=len(kept))
        return removed
