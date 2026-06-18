"""
One-time recovery for the publish-loss bug.

Build directories were pruned off disk while games sat in pending_approvals
waiting to publish, so their .rbxl is gone and the upload fails forever with
"[Errno 2] No such file or directory: .../game.rbxl".

This script finds every unprocessed pending_approvals row whose .rbxl is
missing and triggers ApprovalGate's rebuild-from-concept logic
(ApprovalGate._rebuild_lost_build): the build is regenerated from the original
concept in concept_queue and the row repointed at the fresh artifacts, ready
to publish on the next cycle. Rows whose source concept is also gone are marked
'failed' with a clear Discord alert (handled inside the rebuild logic).

Specifically covers the originally-reported broken games — Sunny Slide
Odyssey, Tropical Pet Paradise, Sunshine Pet Paradise — and any other row in
the same state.

Usage:
    python -m scripts.rebuild_lost_games            # rebuild lost games
    python -m scripts.rebuild_lost_games --dry-run  # report only, no rebuild
"""
import asyncio
import pathlib
import sys

import dotenv


async def amain() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    dotenv.load_dotenv()
    report_only = "--dry-run" in sys.argv

    from orchestrator.scheduler import Orchestrator

    orch = Orchestrator()
    await orch.init()
    try:
        assert orch._pool is not None
        async with orch._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM pending_approvals
                WHERE processed_at IS NULL
                  AND status IN ('pending', 'approved')
                ORDER BY created_at
                """
            )

        lost = [r for r in rows if not pathlib.Path(r["rbxl_path"]).exists()]
        print(f"unprocessed rows:      {len(rows)}")
        print(f"rows with lost .rbxl:  {len(lost)}")
        for r in lost:
            print(f"   - {r['game_title']} [{r['genre']}] -> {r['rbxl_path']}")

        if report_only:
            print("RESULT: dry-run, no rebuilds triggered")
            return 0

        gate = orch._approval_gate
        assert gate is not None
        rebuilt = failed = 0
        for r in lost:
            print(f"\nRebuilding {r['game_title']} [{r['genre']}] ...")
            new_row = await gate._rebuild_lost_build(r)
            if new_row is None:
                failed += 1
                print(f"   FAILED (concept gone or rebuild error) — {r['game_title']}")
            else:
                rebuilt += 1
                print(f"   OK -> {new_row['rbxl_path']}")

        print("\n=== REBUILD LOST GAMES SUMMARY ===")
        print(f"rebuilt + re-queued:   {rebuilt}")
        print(f"terminally failed:     {failed}")
        print("RESULT: done")
        return 0
    finally:
        await orch.stop()


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
