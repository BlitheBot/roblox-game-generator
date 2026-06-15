"""
DecorationPass — runs after LuauAgent generates the source tree (and its
MapBuilder) and guarantees the build ships with a DecorationService that
scatters props through the map's tagged "DecorationZone" areas at runtime.

Every base template already includes a genre-tuned
src/ServerScriptService/DecorationService.server.luau. This pass is the
pipeline integration point: it confirms that script is present and, as a
safety net, synthesises a generic one (with genre-appropriate density) for
any template that is missing it — so no build is ever published with empty,
undecorated zones.
"""
import pathlib

import structlog

log = structlog.get_logger()

DECORATION_REL = "src/ServerScriptService/DecorationService.server.luau"

# Prop spacing (studs) per genre — smaller = denser
DENSITY_BY_TAG = {
    "idle_tycoon": 20,      # sparse industrial props
    "pet_collect": 8,       # dense, colourful nature
    "survival_horror": 15,  # medium atmospheric debris
    "incremental_sim": 28,  # minimal, clean
    "obby": 18,
    "rpg_dungeon": 15,
}
DEFAULT_SPACING = 16

# Minimal, self-contained procedural decorator used only when a template is
# missing its own DecorationService. Kept valid Luau; {spacing} is the only
# substitution and is always an int.
_GENERIC_TEMPLATE = """\
-- DecorationService (generic fallback) — scatters simple props through
-- every CollectionService "DecorationZone" so no zone ships empty.
local Workspace = game:GetService("Workspace")
local CollectionService = game:GetService("CollectionService")

local SPACING = {spacing}
local PALETTE = {{
\tColor3.fromRGB(150, 150, 155),
\tColor3.fromRGB(120, 160, 200),
\tColor3.fromRGB(200, 190, 170),
}}

local decorations = Instance.new("Folder")
decorations.Name = "Decorations"
decorations.Parent = Workspace

local placed = {{}}
local function tooClose(pos)
\tfor _, p in placed do
\t\tif (p - pos).Magnitude < SPACING * 0.6 then
\t\t\treturn true
\t\tend
\tend
\treturn false
end

for _, zone in CollectionService:GetTagged("DecorationZone") do
\tif zone:IsA("BasePart") then
\t\tlocal size, center = zone.Size, zone.Position
\t\tlocal hx, hz = size.X / 2, size.Z / 2
\t\tfor x = -hx, hx, SPACING do
\t\t\tfor z = -hz, hz, SPACING do
\t\t\t\tlocal pos = Vector3.new(center.X + x, 1, center.Z + z)
\t\t\t\tif not tooClose(pos) then
\t\t\t\t\tlocal p = Instance.new("Part")
\t\t\t\t\tp.Anchored = true
\t\t\t\t\tlocal h = 3 + math.random() * 4
\t\t\t\t\tp.Size = Vector3.new(2 + math.random() * 3, h, 2 + math.random() * 3)
\t\t\t\t\tp.Position = pos + Vector3.new(0, h / 2, 0)
\t\t\t\t\tp.Color = PALETTE[math.random(#PALETTE)]
\t\t\t\t\tp.Material = Enum.Material.SmoothPlastic
\t\t\t\t\tp.Parent = decorations
\t\t\t\t\ttable.insert(placed, pos)
\t\t\t\tend
\t\t\tend
\t\tend
\tend
end
"""


class DecorationPass:
    """Ensures a build has a runtime DecorationService."""

    async def apply(self, concept: dict, build_dir: pathlib.Path) -> bool:
        """Returns True if a DecorationService is present (or was created)."""
        target = build_dir / DECORATION_REL
        if target.exists():
            log.info("decoration_pass.present", build_dir=str(build_dir))
            return True

        tag = concept.get("mechanic_tag", "")
        spacing = DENSITY_BY_TAG.get(tag, DEFAULT_SPACING)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            _GENERIC_TEMPLATE.format(spacing=spacing), encoding="utf-8", newline="\n"
        )
        log.info(
            "decoration_pass.synthesized",
            build_dir=str(build_dir),
            mechanic_tag=tag,
            spacing=spacing,
        )
        return True
