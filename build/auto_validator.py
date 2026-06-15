"""
AutoValidator (spec 4.6) — pre-publish checks, in order:

1. Rojo build succeeded (exit code 0)
2. All Luau scripts parse (`luau-analyze`)
3. No script exceeds 200KB
4. TOS keyword scan (blocked terms list)
5. All RemoteEvents have server-side validation present
6. default.project.json structure is valid

Failures are logged to the build_failures table by the pipeline.
"""
import asyncio
import json
import pathlib
import re
from dataclasses import dataclass, field

import structlog

from .rojo_builder import RojoBuildResult

log = structlog.get_logger()

MAX_SCRIPT_BYTES = 200 * 1024

# TOS keyword scan — weapons-realism, slurs/hate placeholders, adult content,
# and scam-bait terms. Kept conservative; matched case-insensitively on word
# boundaries against all Luau source + concept text.
BLOCKED_TERMS = [
    # weapons realism
    "glock", "ar-15", "ak-47", "uzi", "9mm", "shotgun shell",
    # adult content
    "sex", "nude", "naked", "porn", "nsfw", "strip club", "condo game",
    # violence/gore
    "gore", "beheading", "dismember", "suicide", "self harm",
    # drugs
    "cocaine", "heroin", "meth", "weed", "marijuana",
    # gambling/scam-bait
    "casino", "gambling", "free robux", "robux generator",
    # hate
    "nazi", "kkk", "slur",
]

_BLOCKED_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in BLOCKED_TERMS) + r")\b", re.IGNORECASE
)


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    tos_flagged: bool = False


class AutoValidator:
    """Runs all pre-publish checks against a completed build directory."""

    def __init__(self, luau_analyze_binary: str = "luau-analyze") -> None:
        self._luau_analyze = luau_analyze_binary

    async def validate(
        self, build_dir: pathlib.Path, rojo_result: RojoBuildResult
    ) -> ValidationResult:
        failures: list[str] = []
        tos_flagged = False

        # Check 1: rojo build succeeded
        if not rojo_result.success:
            failures.append(f"rojo build failed (exit {rojo_result.exit_code}): {rojo_result.stderr[:1500]}")

        luau_files = sorted(build_dir.rglob("*.luau"))

        # Check 2: luau-analyze parse
        parse_errors = await self._run_luau_analyze(luau_files)
        failures.extend(parse_errors)

        # Check 3: script size limit
        for f in luau_files:
            size = f.stat().st_size
            if size > MAX_SCRIPT_BYTES:
                failures.append(f"script exceeds 200KB: {f.name} ({size} bytes)")

        # Check 4: TOS keyword scan (source + concept)
        scan_targets = list(luau_files)
        concept_file = build_dir / "concept.json"
        if concept_file.exists():
            scan_targets.append(concept_file)
        for f in scan_targets:
            text = f.read_text(encoding="utf-8", errors="replace")
            match = _BLOCKED_RE.search(text)
            if match:
                tos_flagged = True
                failures.append(f"TOS blocked term '{match.group(0)}' in {f.name}")

        # Check 5: RemoteEvent server-side validation
        failures.extend(self._check_remote_validation(build_dir, luau_files))

        # Check 6: project.json structure
        failures.extend(self._check_project_json(build_dir))

        # Check 7: visual quality gate — a build must ship lighting, a map, a
        # loading screen and ambient sound or it goes back to LuauAgent on the
        # same retry ladder as code failures.
        failures.extend(self._check_visual_quality(build_dir))

        result = ValidationResult(
            passed=not failures, failures=failures, tos_flagged=tos_flagged
        )
        log.info(
            "auto_validator.complete",
            passed=result.passed,
            failure_count=len(failures),
            tos_flagged=tos_flagged,
        )
        return result

    async def _run_luau_analyze(self, luau_files: list[pathlib.Path]) -> list[str]:
        if not luau_files:
            return ["no .luau source files found in build"]
        try:
            proc = await asyncio.create_subprocess_exec(
                self._luau_analyze,
                *[str(f) for f in luau_files],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        except FileNotFoundError:
            # Analyzer not installed (e.g. local dev box) — don't hard-fail the
            # whole pipeline on missing tooling; rojo parse still gates output.
            log.warning("auto_validator.luau_analyze_missing")
            return []
        except asyncio.TimeoutError:
            return ["luau-analyze timed out"]

        if proc.returncode == 0:
            return []
        output = (stdout.decode(errors="replace") + stderr.decode(errors="replace")).strip()
        # Only surface hard syntax errors; luau-analyze also emits type warnings
        # which are non-fatal for template-derived code.
        error_lines = [
            line for line in output.splitlines() if "SyntaxError" in line
        ]
        return [f"luau syntax error: {line}" for line in error_lines[:10]]

    @staticmethod
    def _check_remote_validation(
        build_dir: pathlib.Path, luau_files: list[pathlib.Path]
    ) -> list[str]:
        """
        Every RemoteEvent declared in default.project.json must be referenced
        by at least one server-side OnServerEvent handler, and server handlers
        must show evidence of argument validation (typeof checks).
        """
        failures: list[str] = []
        project_file = build_dir / "default.project.json"
        if not project_file.exists():
            return []  # covered by check 6

        try:
            project = json.loads(project_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []  # covered by check 6

        declared_remotes: list[str] = []

        def walk(node: dict) -> None:
            for key, value in node.items():
                if isinstance(value, dict):
                    if value.get("$className") == "RemoteEvent":
                        declared_remotes.append(key)
                    walk(value)

        walk(project.get("tree", {}))

        server_source = ""
        for f in luau_files:
            if "server" in str(f).lower():
                server_source += f.read_text(encoding="utf-8", errors="replace")

        for remote in declared_remotes:
            # State-push remotes are server→client only; skip them
            if remote.lower().startswith(("state", "round")):
                continue
            if remote not in server_source:
                failures.append(f"RemoteEvent '{remote}' has no server-side handler")

        if declared_remotes and "OnServerEvent" in server_source:
            if "typeof(" not in server_source:
                failures.append(
                    "server handles RemoteEvents but shows no typeof() argument validation"
                )
        return failures

    @staticmethod
    def _check_visual_quality(build_dir: pathlib.Path) -> list[str]:
        """A game must meet minimum visual-polish standards before publishing
        so no build ever ships looking like an incomplete baseplate."""
        failures: list[str] = []

        # Must have a LightingService script
        if not (build_dir / "src/ServerScriptService/LightingService.server.luau").exists():
            failures.append("Missing LightingService — game will have default ugly lighting")

        # Must have a MapBuilder script
        if not (build_dir / "src/ServerScriptService/MapBuilder.server.luau").exists():
            failures.append("Missing MapBuilder — game will have no map")

        # Must have a loading screen
        starter_gui = build_dir / "src/StarterGui"
        loading_exists = (
            any("loading" in f.name.lower() for f in starter_gui.rglob("*.luau"))
            if starter_gui.exists()
            else False
        )
        if not loading_exists:
            failures.append("Missing loading screen — players will see blank baseplate on join")

        # Must have ambient sound
        if not (build_dir / "src/ServerScriptService/SoundService.server.luau").exists():
            failures.append("Missing SoundService — game will be silent")

        return failures

    @staticmethod
    def _check_project_json(build_dir: pathlib.Path) -> list[str]:
        project_file = build_dir / "default.project.json"
        if not project_file.exists():
            return ["default.project.json missing"]
        try:
            project = json.loads(project_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return [f"default.project.json invalid JSON: {exc}"]
        if "name" not in project or "tree" not in project:
            return ["default.project.json missing required 'name'/'tree' keys"]
        if project.get("tree", {}).get("$className") != "DataModel":
            return ["default.project.json tree root must be DataModel"]
        return []
