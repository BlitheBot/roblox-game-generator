"""
Build disk management (spec 18).

After a successful publish the build directory moves from
{BUILDS_ROOT}/active/ to {BUILDS_ROOT}/archive/{genre}/, keeping only
the newest MAX_BUILDS_PER_GENRE archives. Skipped builds are deleted so
/builds/active only holds in-progress work.

CRITICAL (publish-loss bug): cleanup must NEVER delete a build directory
for a game that is still waiting to publish. A row in pending_approvals
with status 'pending'/'approved' and processed_at IS NULL still needs its
.rbxl on disk — deleting it caused "[Errno 2] No such file or directory:
.../game.rbxl" at publish time. `active_build_protected_names()` returns
the set of such builds so pruning can exclude them regardless of age/count.
"""
import os
import pathlib
import shutil
import time

import asyncpg
import structlog

log = structlog.get_logger()


def _builds_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("BUILDS_ROOT", "/builds"))


def _age_hours(p: pathlib.Path) -> float:
    try:
        return round((time.time() - p.stat().st_mtime) / 3600, 1)
    except OSError:
        return -1.0


async def active_build_protected_names(pool: asyncpg.Pool) -> set[str]:
    """Names of active build directories that must NOT be pruned because the
    game is still queued to publish: any pending_approvals row that is not yet
    processed (status 'pending' or 'approved', processed_at IS NULL).

    Build directories are named by game_id (see LuauAgent), so both the
    game_id and the directory's basename are returned to cover rebuilt rows
    whose build_dir was repointed to a fresh game_id.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT game_id, build_dir FROM pending_approvals
            WHERE processed_at IS NULL
              AND status IN ('pending', 'approved')
            """
        )
    protected: set[str] = set()
    for r in rows:
        protected.add(str(r["game_id"]))
        build_dir = r["build_dir"]
        if build_dir:
            protected.add(pathlib.Path(build_dir).name)
    return protected


def archive_build(
    build_dir: pathlib.Path, genre: str, protected: set[str] | None = None
) -> pathlib.Path | None:
    """Move a published build into the genre archive and prune old ones.
    Returns the archived path, or None if the move failed (non-fatal).

    `protected` lists build directory names that must never be pruned (games
    still awaiting publish). Archived builds are post-publish so they are
    normally absent from that set, but it is honored defensively.
    """
    if not build_dir.exists():
        return None
    protected = protected or set()
    archive_dir = _builds_root() / "archive" / genre
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / build_dir.name
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(build_dir), str(target))
    except Exception as exc:
        log.warning("build_archive.move_failed", build=str(build_dir), error=str(exc))
        return None

    keep = int(os.environ.get("MAX_BUILDS_PER_GENRE", "10"))
    try:
        # Only builds NOT referenced by an unprocessed pending_approvals row
        # are eligible for pruning, and only those count toward `keep`.
        entries = sorted(
            (
                p
                for p in archive_dir.iterdir()
                if p.is_dir() and p.name not in protected
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in entries[keep:]:
            log.info(
                "build_cleanup.deleting",
                game_id=old.name,
                reason="archive_prune_over_max_builds_per_genre",
                age_hours=_age_hours(old),
            )
            shutil.rmtree(old, ignore_errors=True)
            log.info("build_archive.pruned", build=old.name, genre=genre)
    except Exception as exc:
        log.warning("build_archive.prune_failed", genre=genre, error=str(exc))

    log.info("build_archive.archived", build=build_dir.name, genre=genre)
    return target


def prune_active_builds(keep: int = 2, protected: set[str] | None = None) -> None:
    """FIX 6: keep at most `keep` directories in builds/active so abandoned/
    failed builds don't accumulate on the low-RAM/disk VPS.

    Publish-loss fix: `protected` build directories (games still awaiting
    publish — see active_build_protected_names) are excluded entirely. They
    are never deleted and never counted toward `keep`, so an old-but-pending
    build can't be pushed out of the keep window by newer throwaway builds.
    """
    protected = protected or set()
    active = _builds_root() / "active"
    if not active.exists():
        return
    try:
        entries = sorted(
            (p for p in active.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        prunable = [p for p in entries if p.name not in protected]
        for old in prunable[keep:]:
            log.info(
                "build_cleanup.deleting",
                game_id=old.name,
                reason="active_prune_over_keep",
                age_hours=_age_hours(old),
            )
            shutil.rmtree(old, ignore_errors=True)
            log.info("build_archive.active_pruned", build=old.name)
    except Exception as exc:
        log.warning("build_archive.active_prune_failed", error=str(exc))


def discard_build(build_dir: pathlib.Path) -> None:
    """Delete a skipped/rejected build directory."""
    try:
        if build_dir.exists():
            log.info(
                "build_cleanup.deleting",
                game_id=build_dir.name,
                reason="skip_discard",
                age_hours=_age_hours(build_dir),
            )
            shutil.rmtree(build_dir)
            log.info("build_archive.discarded", build=build_dir.name)
    except Exception as exc:
        log.warning("build_archive.discard_failed", build=str(build_dir), error=str(exc))
