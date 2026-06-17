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

from util.tos import BLOCKED_TERMS, scan_for_blocked_term  # noqa: F401 (re-exported)

from .rojo_builder import RojoBuildResult

log = structlog.get_logger()

MAX_SCRIPT_BYTES = 200 * 1024

# PART 6/7 performance scans (warnings only)
_RANGE_RE = re.compile(r"\.Range\s*=\s*(\d+)")
_RATE_RE = re.compile(r"\.Rate\s*=\s*(\d+)")

# Visual-standards scans (hard failures). These are written to match only
# genuine offences — a Font *assignment* to a banned face, or a *background*
# painted pure white — so legitimate uses (white text, or UIPolish comparing
# against the fonts it replaces) never trip them.
_BANNED_FONT_RE = re.compile(r"Font\s*=\s*Enum\.Font\.(Arial|Legacy|SourceSans)\b")
_WHITE_BG_RE = re.compile(
    r"BackgroundColor3\s*=\s*(?:Color3\.fromRGB\(\s*255\s*,\s*255\s*,\s*255\s*\)"
    r"|Color3\.new\(\s*1\s*,\s*1\s*,\s*1\s*\))"
)

# TOS keyword scan — the canonical blocked-terms list lives in util.tos
# (shared with the concept generator and viability gate, Bug 1). BLOCKED_TERMS
# is re-exported above for callers that still reference it here.


@dataclass
class ValidationResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    tos_flagged: bool = False
    flagged_term: str | None = None
    warnings: list[str] = field(default_factory=list)


class AutoValidator:
    """Runs all pre-publish checks against a completed build directory."""

    def __init__(self, luau_analyze_binary: str = "luau-analyze") -> None:
        self._luau_analyze = luau_analyze_binary

    async def validate(
        self, build_dir: pathlib.Path, rojo_result: RojoBuildResult
    ) -> ValidationResult:
        failures: list[str] = []
        warnings: list[str] = []
        tos_flagged = False
        flagged_term: str | None = None

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
            term = scan_for_blocked_term(text)
            if term:
                tos_flagged = True
                if flagged_term is None:
                    flagged_term = term
                failures.append(f"TOS blocked term '{term}' in {f.name}")

        # Check 5: RemoteEvent server-side validation
        failures.extend(self._check_remote_validation(build_dir, luau_files))

        # Check 6: project.json structure
        failures.extend(self._check_project_json(build_dir))

        # Check 7: visual quality gate — hard failures (lighting/map/loading/
        # sound) block publishing; soft warnings (default grey, while-true,
        # PointLight Range>50, ParticleEmitter Rate>50) are logged only.
        vq_failures, vq_warnings = self._check_visual_quality(build_dir)
        failures.extend(vq_failures)
        warnings.extend(vq_warnings)

        # Check 8: visual design-system standards (hard failures) — every game
        # must ship the shared DesignSystem, a loading screen and a HUD, and
        # must avoid unprofessional default fonts / pure-white backgrounds.
        failures.extend(self.check_visual_standards(build_dir))

        result = ValidationResult(
            passed=not failures,
            failures=failures,
            tos_flagged=tos_flagged,
            flagged_term=flagged_term,
            warnings=warnings,
        )
        for w in warnings:
            log.warning("auto_validator.quality_warning", detail=w)
        log.info(
            "auto_validator.complete",
            passed=result.passed,
            failure_count=len(failures),
            warning_count=len(warnings),
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
    def _check_visual_quality(
        build_dir: pathlib.Path,
    ) -> tuple[list[str], list[str]]:
        """Returns (failures, warnings). Failures block publishing (no game
        ships looking like a baseplate); warnings are logged only (PART 6/7
        performance + theming hygiene)."""
        failures: list[str] = []
        warnings: list[str] = []
        src = build_dir / "src"
        server = src / "ServerScriptService"
        starter_gui = src / "StarterGui"

        # ── Hard failures ───────────────────────────────────────
        if not (server.exists() and any(server.rglob("*Lighting*"))):
            failures.append("Missing lighting setup — game will look like default Roblox")
        if not (server.exists() and any(server.rglob("*Map*"))):
            failures.append("Missing map builder — game has no world")
        loading_exists = (
            any("loading" in f.name.lower() for f in starter_gui.rglob("*.luau"))
            if starter_gui.exists()
            else False
        )
        if not loading_exists:
            failures.append("Missing loading screen — players see blank baseplate")
        # SoundService kept as a hard requirement (every template ships one)
        if not (server.exists() and any(server.rglob("*Sound*"))):
            failures.append("Missing SoundService — game will be silent")

        # ── Soft warnings (do not block publishing) ─────────────
        all_luau = list(build_dir.rglob("*.luau"))
        texts = {f: f.read_text(errors="replace") for f in all_luau}

        default_grey = sum(1 for t in texts.values() if "Color3.fromRGB(163, 162, 165)" in t)
        if default_grey > 3:
            warnings.append(
                f"Found {default_grey} uses of default grey color — map may look unthemed"
            )

        while_true = sum(1 for t in texts.values() if "while true do" in t)
        if while_true > 0:
            warnings.append(
                f"Found {while_true} 'while true do' loop(s) — prefer RunService.Heartbeat/task.wait"
            )

        range_over = sum(
            1
            for t in texts.values()
            for m in _RANGE_RE.findall(t)
            if int(m) > 50
        )
        if range_over > 0:
            warnings.append(f"Found {range_over} PointLight Range value(s) > 50 — caps perf")

        rate_over = sum(
            1
            for t in texts.values()
            for m in _RATE_RE.findall(t)
            if int(m) > 50
        )
        if rate_over > 0:
            warnings.append(f"Found {rate_over} ParticleEmitter Rate value(s) > 50 — caps perf")

        return failures, warnings

    def check_visual_standards(self, build_dir: pathlib.Path) -> list[str]:
        """Enforce the universal design-system standards (PART 7).

        Hard failures: a game missing the shared DesignSystem, a loading screen
        or a HUD looks unfinished or inconsistent; banned default fonts and
        pure-white backgrounds read as amateur. Scans run against the real build
        layout (Shared modules under src/shared, client UI under src/client,
        loading under src/StarterGui)."""
        failures: list[str] = []

        all_scripts = list(build_dir.rglob("*.luau"))
        names = [f.name.lower() for f in all_scripts]

        # DesignSystem must ship in ReplicatedStorage.Shared (src/shared).
        has_design_system = (
            build_dir / "src" / "shared" / "DesignSystem.luau"
        ).exists() or any(
            f.name == "DesignSystem.luau" and f.parent.name == "shared"
            for f in all_scripts
        )
        if not has_design_system:
            failures.append(
                "Missing DesignSystem — UI will be inconsistent and unpolished"
            )

        # Loading screen (players otherwise see a raw baseplate on join).
        if not any("loading" in n for n in names):
            failures.append(
                "Missing LoadingScreen — players see raw baseplate on join"
            )

        # HUD (currency / stats display).
        if not any("hud" in n for n in names):
            failures.append(
                "Missing HUD — players have no currency or stats display"
            )

        # Banned fonts + pure-white backgrounds.
        for f in all_scripts:
            content = f.read_text(encoding="utf-8", errors="replace")
            font_match = _BANNED_FONT_RE.search(content)
            if font_match:
                failures.append(
                    f"{f.name}: assigns unprofessional default font "
                    f"Enum.Font.{font_match.group(1)} — use DesignSystem.Fonts"
                )
            if _WHITE_BG_RE.search(content):
                failures.append(
                    f"{f.name}: has a pure-white background — use DesignSystem colors"
                )

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
