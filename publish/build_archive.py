"""
Build disk management (spec 18).

After a successful publish the build directory moves from
{BUILDS_ROOT}/active/ to {BUILDS_ROOT}/archive/{genre}/, keeping only
the newest MAX_BUILDS_PER_GENRE archives. Skipped builds are deleted so
/builds/active only holds in-progress work.
"""
import os
import pathlib
import shutil

import structlog

log = structlog.get_logger()


def _builds_root() -> pathlib.Path:
    return pathlib.Path(os.environ.get("BUILDS_ROOT", "/builds"))


def archive_build(build_dir: pathlib.Path, genre: str) -> pathlib.Path | None:
    """Move a published build into the genre archive and prune old ones.
    Returns the archived path, or None if the move failed (non-fatal)."""
    if not build_dir.exists():
        return None
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
        entries = sorted(
            (p for p in archive_dir.iterdir() if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in entries[keep:]:
            shutil.rmtree(old, ignore_errors=True)
            log.info("build_archive.pruned", build=old.name, genre=genre)
    except Exception as exc:
        log.warning("build_archive.prune_failed", genre=genre, error=str(exc))

    log.info("build_archive.archived", build=build_dir.name, genre=genre)
    return target


def prune_active_builds(keep: int = 2, protect: set[str] | None = None) -> None:
    """FIX 6: keep at most `keep` of the most-recent *unprotected* directories
    in builds/active so abandoned/failed builds don't accumulate on the
    low-RAM/disk VPS.

    `protect` is the set of dir names (game ids) that are still awaiting
    publish — they are NEVER pruned regardless of count or age. The publish
    rate limiter can hold an approved build for days; deleting it early makes
    the publisher fail with 'No such file or directory'. A build leaves
    builds/active only via archive_build (after a successful publish) or
    discard_build (skip)."""
    protect = protect or set()
    active = _builds_root() / "active"
    if not active.exists():
        return
    try:
        unprotected = sorted(
            (p for p in active.iterdir() if p.is_dir() and p.name not in protect),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old in unprotected[keep:]:
            shutil.rmtree(old, ignore_errors=True)
            log.info("build_archive.active_pruned", build=old.name)
    except Exception as exc:
        log.warning("build_archive.active_prune_failed", error=str(exc))


def discard_build(build_dir: pathlib.Path) -> None:
    """Delete a skipped/rejected build directory."""
    try:
        if build_dir.exists():
            shutil.rmtree(build_dir)
            log.info("build_archive.discarded", build=build_dir.name)
    except Exception as exc:
        log.warning("build_archive.discard_failed", build=str(build_dir), error=str(exc))
