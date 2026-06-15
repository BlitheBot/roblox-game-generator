-- MapBuilder — builds a clean, fully enclosed modern facility on server
-- start so no generated game ships as an open baseplate. 250 x 250 floor
-- with alternating polished tiles, a grid of upgrade stations, wall progress
-- boards, a glowing prestige portal, a glass-walled shop and a leaderboard.
local Workspace = game:GetService("Workspace")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local FLOOR = 250
local WALL_HEIGHT = 36
local WALL_THICK = 2
local WHITE = Color3.fromRGB(244, 244, 248)
local CREAM = Color3.fromRGB(232, 228, 218)
local LIGHTGREY = Color3.fromRGB(205, 208, 214)
local BLUE = Color3.fromRGB(80, 170, 255)

local map = Instance.new("Model")
map.Name = "GeneratedMap"
map.Parent = Workspace

local function block(size: Vector3, pos: Vector3, color: Color3, material: Enum.Material)
	local p = Instance.new("Part")
	p.Anchored = true
	p.Size = size
	p.Position = pos
	p.Color = color
	p.Material = material
	p.TopSurface = Enum.SurfaceType.Smooth
	p.BottomSurface = Enum.SurfaceType.Smooth
	p.Parent = map
	return p
end

local half, midY = FLOOR / 2, WALL_HEIGHT / 2

-- Polished floor as an alternating tile checkerboard
local tile = 25
for x = -half + tile / 2, half, tile do
	for z = -half + tile / 2, half, tile do
		local even = (math.floor(x / tile) + math.floor(z / tile)) % 2 == 0
		block(Vector3.new(tile, 1, tile), Vector3.new(x - 0.5, 0, z - 0.5), even and WHITE or LIGHTGREY, Enum.Material.SmoothPlastic)
	end
end

-- Ceiling + cream perimeter walls with large windows
block(Vector3.new(FLOOR, WALL_THICK, FLOOR), Vector3.new(0, WALL_HEIGHT, 0), WHITE, Enum.Material.SmoothPlastic)
block(Vector3.new(FLOOR, WALL_HEIGHT, WALL_THICK), Vector3.new(0, midY, -half), CREAM, Enum.Material.SmoothPlastic)
block(Vector3.new(FLOOR, WALL_HEIGHT, WALL_THICK), Vector3.new(0, midY, half), CREAM, Enum.Material.SmoothPlastic)
block(Vector3.new(WALL_THICK, WALL_HEIGHT, FLOOR), Vector3.new(-half, midY, 0), CREAM, Enum.Material.SmoothPlastic)
block(Vector3.new(WALL_THICK, WALL_HEIGHT, FLOOR), Vector3.new(half, midY, 0), CREAM, Enum.Material.SmoothPlastic)
for z = -half + 40, half - 40, 50 do
	local win = block(Vector3.new(0.5, 18, 30), Vector3.new(half - 1, WALL_HEIGHT - 14, z), Color3.fromRGB(170, 215, 255), Enum.Material.Glass)
	win.Transparency = 0.5
end

-- Grid of upgrade stations across the floor
for gx = -2, 2 do
	for gz = -1, 1 do
		local pos = Vector3.new(gx * 45, 3, gz * 55)
		block(Vector3.new(10, 6, 10), pos, Color3.fromRGB(225, 228, 234), Enum.Material.SmoothPlastic)
		local panel = block(Vector3.new(10, 5, 0.5), pos + Vector3.new(0, 7, 5), BLUE, Enum.Material.Neon)
		panel.Transparency = 0.1
	end
end

-- Glowing prestige portal in the centre
local portalBase = Instance.new("Part")
portalBase.Shape = Enum.PartType.Cylinder
portalBase.Anchored = true
portalBase.Size = Vector3.new(2, 36, 36)
portalBase.CFrame = CFrame.new(0, 1, 0) * CFrame.Angles(0, 0, math.rad(90))
portalBase.Color = BLUE
portalBase.Material = Enum.Material.Neon
portalBase.Transparency = 0.2
portalBase.Parent = map
local portalLight = Instance.new("PointLight")
portalLight.Brightness = 5
portalLight.Range = 40
portalLight.Color = BLUE
portalLight.Parent = portalBase
local portalRing = Instance.new("ParticleEmitter")
portalRing.Texture = "rbxassetid://6101304403"
portalRing.Rate = 30
portalRing.Lifetime = NumberRange.new(1, 2)
portalRing.Speed = NumberRange.new(2, 5)
portalRing.Color = ColorSequence.new(BLUE)
portalRing.LightEmission = 1
portalRing.Parent = portalBase

-- Wall-mounted boards: progress displays + leaderboard
local Config
local ok, mod = pcall(function()
	return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
end)
if ok then
	Config = mod
end

local function board(text: string, pos: Vector3, face: Enum.NormalId)
	local b = block(Vector3.new(0.5, 16, 28), pos, Color3.fromRGB(40, 44, 52), Enum.Material.SmoothPlastic)
	local gui = Instance.new("SurfaceGui")
	gui.Face = face
	gui.CanvasSize = Vector2.new(560, 320)
	gui.Parent = b
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.TextColor3 = BLUE
	label.Font = Enum.Font.GothamBold
	label.TextScaled = true
	label.Text = text
	label.Parent = gui
	return b
end
board("TOP EARNERS", Vector3.new(-half + 1, 20, -60), Enum.NormalId.Right)
board("PROGRESS", Vector3.new(-half + 1, 20, 0), Enum.NormalId.Right)
board((Config and Config.GameTitle) or "LEADERBOARD", Vector3.new(0, 22, -half + 1), Enum.NormalId.Back)

-- Glass-walled shop building in a corner
local shopCorner = Vector3.new(-90, 0, 90)
for _, off in { Vector3.new(0, 0, -16), Vector3.new(0, 0, 16), Vector3.new(-16, 0, 0) } do
	local sx = if off.X ~= 0 then 0.5 else 32
	local sz = if off.X ~= 0 then 32 else 0.5
	local wall = block(Vector3.new(sx, 16, sz), shopCorner + off + Vector3.new(0, 8, 0), Color3.fromRGB(190, 225, 255), Enum.Material.Glass)
	wall.Transparency = 0.55
end
block(Vector3.new(34, 1, 34), shopCorner + Vector3.new(-8, 16, 0), WHITE, Enum.Material.SmoothPlastic)
board("SHOP", shopCorner + Vector3.new(-8, 10, -16.3), Enum.NormalId.Back)

-- Decoration zones for the DecorationService pass (kept minimal / clean)
local function decoZone(pos: Vector3, size: Vector3)
	local zone = block(size, pos, Color3.fromRGB(0, 0, 0), Enum.Material.SmoothPlastic)
	zone.Transparency = 1
	zone.CanCollide = false
	CollectionService:AddTag(zone, "DecorationZone")
end
decoZone(Vector3.new(0, 1, 90), Vector3.new(180, 1, 40))

-- Spawn near the entrance
local spawn = Instance.new("SpawnLocation")
spawn.Anchored = true
spawn.Size = Vector3.new(12, 1, 12)
spawn.Position = Vector3.new(0, 2, half - 20)
spawn.Color = BLUE
spawn.Material = Enum.Material.Neon
spawn.Parent = map
