"""
One-shot end-to-end dry run (spec Section 10, Phase 4 step 2).

Runs a single intelligence → build → approval → (skipped) publish →
monitor cycle and exits. DRY_RUN is forced on, so no Roblox universe is
ever touched; exit code is 0 only if at least one build made it all the
way through the approval gate.

With real API keys (.env on the VPS) this exercises real LLMs. Without
keys, start the mock first and point the pipeline at it:

    python scripts/mock_openrouter.py &
    OPENROUTER_BASE_URL=http://127.0.0.1:8901/api/v1 \
    OPENROUTER_API_KEY=mock \
    python -m scripts.dry_run
"""
import asyncio
import os
import sys
from datetime import datetime, timezone

import dotenv


async def amain() -> int:
    # Windows consoles default to cp1252, which can't print the emoji in
    # alert/log text — force UTF-8 so logging never crashes the cycle
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    dotenv.load_dotenv()
    os.environ["DRY_RUN"] = "true"
    # Autonomous gate path so builds flow through without a Discord DM
    os.environ.setdefault("SUPERVISED_MODE", "false")

    from orchestrator.scheduler import Orchestrator

    started_at = datetime.now(timezone.utc)
    orch = Orchestrator()
    await orch.init()
    try:
        await orch.run_one_cycle()
        assert orch._pool is not None
        return await _report(orch._pool, started_at)
    finally:
        await orch.stop()


async def _report(pool, started_at) -> int:
    async with pool.acquire() as conn:
        concepts = await conn.fetchval(
            "SELECT COUNT(*) FROM concept_queue WHERE created_at >= $1", started_at
        )
        built = await conn.fetch(
            """
            SELECT game_title, genre, rbxl_path FROM pending_approvals
            WHERE created_at >= $1 AND processed_at IS NOT NULL
            """,
            started_at,
        )
        failures = await conn.fetch(
            """
            SELECT stage, error_message FROM build_failures
            WHERE timestamp >= $1 ORDER BY timestamp DESC
            """,
            started_at,
        )
        spend = await conn.fetchval(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_spend WHERE timestamp >= $1",
            started_at,
        )

    print("\n=== DRY RUN SUMMARY ===")
    print(f"concepts queued:       {concepts}")
    print(f"builds through gate:   {len(built)}")
    for b in built:
        print(f"   - {b['game_title']} [{b['genre']}] -> {b['rbxl_path']}")
    print(f"LLM spend recorded:    ${spend:.4f}")
    print(f"build failures logged: {len(failures)}")
    for f in failures[:5]:
        print(f"   - [{f['stage']}] {f['error_message'][:140]}")

    ok = len(built) > 0
    print("RESULT: " + ("PASS" if ok else "FAIL — no build completed end-to-end"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
