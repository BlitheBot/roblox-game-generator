"""
BuildPipeline — sequential L2 coordinator (spec Section 4):

ConceptGenerator → LuauAgent → ToolboxAssetResolver → RojoBuilder
→ AssetGenerator → AutoValidator

Retry policy (spec 4.6): up to 3 attempts with Claude Sonnet (error
context appended each retry), then escalate to Claude Opus and restart
from LuauAgent. All failures logged to build_failures.
"""
import asyncio
import pathlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import asyncpg
import structlog

from intelligence.llm_client import CLAUDE_OPUS, CLAUDE_SONNET
from util.tos import TOSViolation

from .asset_generator import AssetGenerator
from .asset_verifier import AssetVerifier
from .auto_validator import AutoValidator
from .concept_generator import ConceptGenerator
from .decoration_pass import DecorationPass
from .luau_agent import LuauAgent
from .rojo_builder import RojoBuilder
from .toolbox_resolver import ToolboxAssetResolver

if TYPE_CHECKING:
    from monitor.discord_reporter import DiscordReporter

log = structlog.get_logger()

RETRIES_PER_MODEL = 3
MODEL_LADDER = [CLAUDE_SONNET, CLAUDE_OPUS]

# FIX 7: only one full build pipeline may run at a time (memory + OpenRouter
# rate-limit safety). Concurrent run() calls queue on this process-wide lock.
_BUILD_LOCK = asyncio.Lock()


@dataclass
class BuildOutput:
    game_id: str
    concept_id: str
    build_dir: pathlib.Path
    rbxl_path: pathlib.Path
    thumbnail_path: pathlib.Path
    icon_path: pathlib.Path
    description: str
    concept: dict
    tos_flagged: bool = False


class BuildPipeline:
    def __init__(
        self, pool: asyncpg.Pool, reporter: "DiscordReporter | None" = None
    ) -> None:
        self._pool = pool
        self._reporter = reporter
        # Set when run() discards a concept for TOS content so the caller can
        # skip its generic "build failed" alert (the TOS alert already fired).
        self.last_tos_discard: tuple[str, str] | None = None
        self._concept_gen = ConceptGenerator()
        self._luau_agent = LuauAgent()
        self._resolver = ToolboxAssetResolver()
        self._verifier = AssetVerifier()
        self._rojo = RojoBuilder()
        self._decoration = DecorationPass()
        self._assets = AssetGenerator()
        self._validator = AutoValidator()

    async def run(
        self, concept_id: str, meta_keywords: list[str] | None = None
    ) -> BuildOutput | None:
        """Runs the full L2 pipeline for a queued concept, serialized so only
        one build executes at a time. Returns BuildOutput on success, None
        after exhausting all retries."""
        async with _BUILD_LOCK:
            return await self._run_locked(concept_id, meta_keywords)

    async def _run_locked(
        self, concept_id: str, meta_keywords: list[str] | None = None
    ) -> BuildOutput | None:
        await self._set_status(concept_id, "building")
        self.last_tos_discard = None
        game_id = str(uuid.uuid4())

        try:
            concept = await self._concept_gen.generate(self._pool, concept_id)
            concept = await self._resolver.resolve(concept)
            # FIX 5: drop any resolved asset that is no longer free/available
            # before it gets baked into Config (fails open on API errors)
            concept = await self._verifier.verify_concept_assets(concept)
            # Cross-promotion: bake the account's current live games into
            # the build so CrossPromoManager can raise billboards for them
            from .cross_promotion import get_siblings

            concept["cross_promo_siblings"] = await get_siblings(
                self._pool, concept.get("target_genre_account") or "sim"
            )
        except TOSViolation as exc:
            # Bug 1: the concept generator pre-screen caught blocked content.
            # Discard permanently — never retried, never escalated.
            await self._discard_tos(concept_id, exc)
            return None
        except Exception as exc:
            await self._log_failure(concept_id, "concept_generation", str(exc), "deepseek", 0)
            await self._set_status(concept_id, "failed")
            return None

        error_context: str | None = None
        for model in MODEL_LADDER:
            for attempt in range(1, RETRIES_PER_MODEL + 1):
                try:
                    output = await self._attempt_build(
                        concept, concept_id, game_id, model, error_context, meta_keywords
                    )
                except TOSViolation as exc:
                    # Bug 1: a TOS hit in the generated build is a content
                    # issue, not a code-quality one. Discard immediately —
                    # do NOT add to the retry ladder, do NOT escalate models.
                    await self._discard_tos(concept_id, exc)
                    return None
                except Exception as exc:
                    error_context = str(exc)[:2000]
                    await self._log_failure(concept_id, "build_attempt", error_context, model, attempt)
                    continue

                if output is not None:
                    return output
                # validation failed — error context already recorded by _attempt_build
                error_context = self._last_validation_error

            log.warning(
                "pipeline.escalating_model",
                concept_id=concept_id,
                from_model=model,
            )

        await self._set_status(concept_id, "failed")
        log.error("pipeline.exhausted_retries", concept_id=concept_id)
        return None

    async def _discard_tos(self, concept_id: str, exc: TOSViolation) -> None:
        """Bug 1: permanently discard a TOS-flagged concept. Marks it failed,
        fires exactly one Discord alert, and records the discard so the caller
        skips its generic build-failure alert."""
        await self._set_status(concept_id, "failed")
        self.last_tos_discard = (exc.game_title, exc.term)
        log.error(
            "pipeline.tos_discarded",
            concept_id=concept_id,
            term=exc.term,
            title=exc.game_title,
        )
        if self._reporter is not None:
            await self._reporter.alert(
                f"TOS concept discarded — {exc.game_title}: {exc.term}. "
                f"This concept will not be retried."
            )

    _last_validation_error: str | None = None

    async def _attempt_build(
        self,
        concept: dict,
        concept_id: str,
        game_id: str,
        model: str,
        error_context: str | None,
        meta_keywords: list[str] | None,
    ) -> BuildOutput | None:
        build_dir = await self._luau_agent.generate(
            concept, game_id, model=model, error_context=error_context
        )
        # Decoration pass runs after the map is generated, before the build,
        # so scattered props ship inside the compiled .rbxl
        await self._decoration.apply(concept, build_dir)
        rojo_result = await self._rojo.build(build_dir)
        validation = await self._validator.validate(build_dir, rojo_result)

        if not validation.passed:
            self._last_validation_error = "; ".join(validation.failures)[:2000]
            if validation.tos_flagged:
                # Bug 1: log once under the 'tos_flag' stage, then raise so the
                # pipeline discards the concept immediately — no retry ladder,
                # no model escalation (TOS content can't be fixed by retrying).
                await self._log_failure(
                    concept_id, "tos_flag", self._last_validation_error, model, 1
                )
                log.error("pipeline.tos_flagged", concept_id=concept_id)
                raise TOSViolation(
                    validation.flagged_term or "blocked term",
                    concept.get("game_title", "Untitled"),
                )
            await self._log_failure(
                concept_id, "auto_validator", self._last_validation_error, model, 1
            )
            return None

        assets = await self._assets.generate_all(concept, build_dir, meta_keywords)

        assert rojo_result.rbxl_path is not None
        return BuildOutput(
            game_id=game_id,
            concept_id=concept_id,
            build_dir=build_dir,
            rbxl_path=rojo_result.rbxl_path,
            thumbnail_path=assets["thumbnail"],
            icon_path=assets["icon"],
            description=assets["description"],
            concept=concept,
        )

    async def _set_status(self, concept_id: str, status: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE concept_queue SET status = $1 WHERE id = $2",
                status,
                uuid.UUID(concept_id),
            )

    async def _log_failure(
        self, concept_id: str, stage: str, error: str, model: str, retry_count: int
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO build_failures
                    (id, concept_id, timestamp, stage, error_message, model_used, retry_count)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                uuid.uuid4(),
                uuid.UUID(concept_id),
                datetime.now(timezone.utc),
                stage,
                error[:4000],
                model,
                retry_count,
            )
