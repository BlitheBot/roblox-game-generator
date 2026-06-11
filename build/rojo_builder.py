"""
RojoBuilder (spec 4.4) — headless .rbxl compilation via the rojo CLI.

    rojo build {build_dir}/default.project.json --output {build_dir}/game.rbxl

On failure, stderr is captured and returned so the pipeline can feed it
back to LuauAgent for a targeted fix (max 3 retries before escalation).
"""
import asyncio
import pathlib
from dataclasses import dataclass

import structlog

log = structlog.get_logger()

ROJO_TIMEOUT_SECONDS = 120


@dataclass
class RojoBuildResult:
    success: bool
    rbxl_path: pathlib.Path | None
    stderr: str
    exit_code: int


class RojoBuilder:
    """Subprocess wrapper around the rojo CLI with error capture."""

    def __init__(self, rojo_binary: str = "rojo") -> None:
        self._rojo = rojo_binary

    async def build(self, build_dir: pathlib.Path) -> RojoBuildResult:
        project_file = build_dir / "default.project.json"
        output_file = build_dir / "game.rbxl"

        if not project_file.exists():
            return RojoBuildResult(
                success=False,
                rbxl_path=None,
                stderr=f"project file missing: {project_file}",
                exit_code=-1,
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                self._rojo,
                "build",
                str(project_file),
                "--output",
                str(output_file),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=ROJO_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            return RojoBuildResult(
                success=False,
                rbxl_path=None,
                stderr=f"rojo build timed out after {ROJO_TIMEOUT_SECONDS}s",
                exit_code=-1,
            )
        except FileNotFoundError:
            return RojoBuildResult(
                success=False,
                rbxl_path=None,
                stderr=(
                    "rojo binary not found — install via Rokit on the VPS "
                    "(spec Section 11 step 4)"
                ),
                exit_code=-1,
            )

        success = proc.returncode == 0 and output_file.exists()
        result = RojoBuildResult(
            success=success,
            rbxl_path=output_file if success else None,
            stderr=stderr.decode(errors="replace"),
            exit_code=proc.returncode or 0,
        )
        log.info(
            "rojo.build",
            success=success,
            exit_code=result.exit_code,
            build_dir=str(build_dir),
        )
        if not success:
            log.warning("rojo.build_failed", stderr=result.stderr[:2000])
        return result
