"""
Self-contained test for the publish-loss fix (no DB / no network).

Verifies the new ApprovalGate behavior when a queued game's .rbxl has been
pruned off disk before publish:

  1. rbxl present            -> active-build pruning never deletes it
  2. rbxl missing, concept   -> rebuild from concept is triggered and the row
     still in concept_queue      is repointed at fresh artifacts (NOT retried
                                 forever)
  3. rbxl missing, concept   -> row is marked 'failed' + processed (stops the
     gone                        forever-retry) and a clear alert is sent

Run:  python -m scripts.test_lost_build_rebuild
Exit: 0 on pass, 1 on failure.
"""
import asyncio
import os
import sys
import tempfile
import types
import uuid
from pathlib import Path

# Keep imports of approval_gate happy without a real environment.
os.environ.setdefault("DRY_RUN", "false")


# ── minimal asyncpg fakes ────────────────────────────────────────────────


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class FakeConn:
    def __init__(self, pool):
        self._pool = pool

    async def execute(self, sql, *args):
        self._pool.executes.append((" ".join(sql.split()), args))
        return "OK"

    async def fetch(self, sql, *args):
        return self._pool.responder("fetch", " ".join(sql.split()), args)

    async def fetchval(self, sql, *args):
        return self._pool.responder("fetchval", " ".join(sql.split()), args)

    async def fetchrow(self, sql, *args):
        return self._pool.responder("fetchrow", " ".join(sql.split()), args)


class FakePool:
    def __init__(self, responder):
        self.executes = []
        self.responder = responder

    def acquire(self):
        return _Acquire(FakeConn(self))


class FakeReporter:
    def __init__(self):
        self.alerts = []

    async def alert(self, msg):
        self.alerts.append(msg)


class FakePublisher:
    def __init__(self):
        self.publish_calls = 0

    async def publish(self, **kwargs):
        self.publish_calls += 1
        raise AssertionError("publisher.publish must not be called for a lost build")


def _make_gate(pool, reporter):
    from publish.approval_gate import ApprovalGate

    return ApprovalGate(pool, reporter)


def _row(rbxl_path):
    return {
        "game_id": uuid.uuid4(),
        "concept_id": uuid.uuid4(),
        "game_title": "Sunny Slide Odyssey",
        "genre": "sim",
        "build_dir": str(Path(rbxl_path).parent),
        "rbxl_path": rbxl_path,
        "thumbnail_path": "/builds/active/old/thumb.png",
        "description": "old desc",
        "status": "approved",
        "decided_at": None,
    }


# ── test 1: pruning protects builds still awaiting publish ────────────────


def test_prune_protects_pending() -> None:
    from publish import build_archive

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        active = root / "active"
        active.mkdir()
        names = ["aaa", "bbb", "ccc", "ddd"]
        for n in names:
            (active / n).mkdir()
            (active / n / "game.rbxl").write_text("x")
        os.environ["BUILDS_ROOT"] = str(root)

        # 'aaa' is the oldest -> normally first to be pruned with keep=2, but it
        # is protected (still awaiting publish) so it must survive.
        build_archive.prune_active_builds(keep=2, protected={"aaa"})

        survivors = {p.name for p in active.iterdir()}
    assert "aaa" in survivors, f"protected build was pruned: {survivors}"
    # keep=2 over the 3 unprotected -> exactly one unprotected pruned
    assert len(survivors) == 3, f"expected 3 survivors, got {survivors}"
    print("PASS test_prune_protects_pending")


# ── test 2: missing rbxl + concept present -> rebuild + re-queue ──────────


async def test_rebuild_triggers() -> None:
    reporter = FakeReporter()

    with tempfile.TemporaryDirectory() as tmp:
        new_build = Path(tmp) / "newbuild"
        new_build.mkdir()
        new_rbxl = new_build / "game.rbxl"
        new_rbxl.write_text("freshly built")
        new_thumb = new_build / "thumb.png"
        new_thumb.write_text("img")

        row = _row(str(Path(tmp) / "gone" / "game.rbxl"))  # does not exist

        def responder(kind, sql, args):
            if "SELECT 1 FROM concept_queue" in sql:
                return 1  # concept still available
            if "SELECT * FROM pending_approvals WHERE game_id" in sql:
                return dict(
                    row,
                    build_dir=str(new_build),
                    rbxl_path=str(new_rbxl),
                    thumbnail_path=str(new_thumb),
                    description="fresh desc",
                )
            return None

        pool = FakePool(responder)
        gate = _make_gate(pool, reporter)

        # Stub the build pipeline so no LLM / Rojo runs.
        out = types.SimpleNamespace(
            game_id=str(uuid.uuid4()),
            build_dir=new_build,
            rbxl_path=new_rbxl,
            thumbnail_path=new_thumb,
            description="fresh desc",
        )

        class FakePipeline:
            def __init__(self, *a, **k):
                pass

            async def run(self, concept_id, **k):
                return out

        fake_mod = types.ModuleType("build.pipeline")
        fake_mod.BuildPipeline = FakePipeline
        sys.modules["build.pipeline"] = fake_mod

        refreshed = await gate._rebuild_lost_build(row)

        assert refreshed is not None, "rebuild should return a refreshed row"
        assert refreshed["rbxl_path"] == str(new_rbxl), refreshed["rbxl_path"]
        assert Path(refreshed["rbxl_path"]).exists()
        # row repointed via UPDATE, not failed
        assert any(
            "UPDATE pending_approvals SET build_dir" in sql for sql, _ in pool.executes
        ), pool.executes
        assert not any(
            "status = 'failed'" in sql for sql, _ in pool.executes
        ), "lost build with a live concept must NOT be failed"
        assert any("Rebuilt lost build" in a for a in reporter.alerts), reporter.alerts
    print("PASS test_rebuild_triggers")


# ── test 3: missing rbxl + concept gone -> terminal fail, no forever-retry ─


async def test_unrecoverable_fails() -> None:
    reporter = FakeReporter()
    row = _row("/builds/active/lost/game.rbxl")

    def responder(kind, sql, args):
        if "SELECT 1 FROM concept_queue" in sql:
            return None  # concept gone too
        return None

    pool = FakePool(responder)
    gate = _make_gate(pool, reporter)

    result = await gate._rebuild_lost_build(row)

    assert result is None, "unrecoverable lost build must return None"
    failed = [sql for sql, _ in pool.executes if "status = 'failed'" in sql]
    assert failed, f"row must be marked failed: {pool.executes}"
    assert any("processed_at = NOW()" in sql for sql in failed), (
        "failed row must be marked processed so it stops retrying forever"
    )
    assert any(
        "regenerated from scratch" in a for a in reporter.alerts
    ), reporter.alerts
    print("PASS test_unrecoverable_fails")


# ── test 4: _publish_approved skips upload when rebuild can't recover ─────


async def test_publish_skips_upload_on_lost_build() -> None:
    reporter = FakeReporter()
    row = _row("/builds/active/lost/game.rbxl")  # missing
    pool = FakePool(lambda *a: None)
    gate = _make_gate(pool, reporter)

    # Get past the pre-publish gates so we reach the rbxl existence check.
    async def _no_state(_key):
        return None

    async def _score(_cid):
        return 0.0

    gate._state_get = _no_state  # type: ignore[assignment]
    gate._opportunity_score = _score  # type: ignore[assignment]

    class FakeLimiter:
        async def get_backlog_allowance(self, *a):
            return 0

        async def can_publish(self, *a):
            return True, "ok"

    gate._rate_limiter = FakeLimiter()  # type: ignore[assignment]

    # Rebuild can't recover -> returns None; publish must be skipped entirely.
    async def _rebuild_none(_row):
        return None

    gate._rebuild_lost_build = _rebuild_none  # type: ignore[assignment]

    publisher = FakePublisher()
    await gate._publish_approved(row, publisher, marketer=object())

    assert publisher.publish_calls == 0, "must not attempt upload for a lost build"
    print("PASS test_publish_skips_upload_on_lost_build")


async def amain() -> int:
    test_prune_protects_pending()
    await test_rebuild_triggers()
    await test_unrecoverable_fails()
    await test_publish_skips_upload_on_lost_build()
    print("\nALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(amain()))
    except AssertionError as exc:
        print(f"\nTEST FAILED: {exc}")
        sys.exit(1)
