-- MapBuilder — builds a magical floating-island paradise on server start.
-- A complete, colorful world so no generated game ships as a bare baseplate:
-- a 250-stud main island, three smaller floating islands joined by rainbow
-- bridges, a waterfall, egg-hatching pedestals, a trading gazebo and a shop.
local Workspace = game:GetService("Workspace")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local GRASS = Color3.fromRGB(120, 220, 120)
local DIRT = Color3.fromRGB(150, 110, 80)
local PASTELS = {
	Color3.fromRGB(255, 190, 215),
	Color3.fromRGB(190, 225, 255),
	Color3.fromRGB(255, 240, 180),
	Color3.fromRGB(205, 190, 255),
	Color3.fromRGB(190, 255, 215),
}
local RAINBOW = {
	Color3.fromRGB(255, 105, 97), Color3.fromRGB(255, 180, 95),
	Color3.fromRGB(255, 240, 120), Color3.fromRGB(140, 230, 140),
	Color3.fromRGB(120, 190, 255), Color3.fromRGB(190, 150, 255),
}

local map = Instance.new("Model")
map.Name = "GeneratedMap"
map.Parent = Workspace

local function part(shape, size, pos, color, material)
	local p = Instance.new("Part")
	p.Shape = shape
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

-- An "island": grass disc on a dirt underside
local function island(center: Vector3, radius: number)
	part(Enum.PartType.Cylinder, Vector3.new(4, radius * 2, radius * 2), center, GRASS, Enum.Material.Grass).CFrame =
		CFrame.new(center) * CFrame.Angles(0, 0, math.rad(90))
	part(Enum.PartType.Cylinder, Vector3.new(18, radius * 1.7, radius * 1.7), center - Vector3.new(0, 11, 0), DIRT, Enum.Material.Ground).CFrame =
		CFrame.new(center - Vector3.new(0, 11, 0)) * CFrame.Angles(0, 0, math.rad(90))
end

-- Main island (250 studs across) plus three smaller satellites
island(Vector3.new(0, 0, 0), 125)
local satellites = {
	Vector3.new(220, -6, 0),
	Vector3.new(-150, -4, 160),
	Vector3.new(120, 4, -200),
}
for _, c in satellites do
	island(c, 45)
end

-- Rainbow bridges from the main island out to each satellite
for _, target in satellites do
	local from = Vector3.new(0, 2, 0)
	local steps = 14
	for i = 1, steps do
		local t = i / steps
		local pos = from:Lerp(target + Vector3.new(0, 2, 0), t)
		pos = pos + Vector3.new(0, math.sin(t * math.pi) * 10, 0) -- arc
		local plank = part(Enum.PartType.Block, Vector3.new(10, 1, 6), pos, RAINBOW[(i % #RAINBOW) + 1], Enum.Material.Neon)
		plank.Transparency = 0.1
	end
end

-- Waterfall flowing off the main island edge
for i = 0, 12 do
	local w = part(Enum.PartType.Block, Vector3.new(20, 8, 2), Vector3.new(0, -i * 7, 124), Color3.fromRGB(120, 200, 255), Enum.Material.Glass)
	w.Transparency = 0.45
end
local fallAnchor = part(Enum.PartType.Block, Vector3.new(1, 1, 1), Vector3.new(0, -2, 124), Color3.fromRGB(255, 255, 255), Enum.Material.Neon)
fallAnchor.Transparency = 1
local spray = Instance.new("ParticleEmitter")
spray.Texture = "rbxassetid://241594419"
spray.Rate = 40
spray.Lifetime = NumberRange.new(1, 2)
spray.Speed = NumberRange.new(6, 12)
spray.Color = ColorSequence.new(Color3.fromRGB(200, 235, 255))
spray.Parent = fallAnchor

-- Egg hatching area: circular platform with glowing pedestals + eggs
local hatchCenter = Vector3.new(0, 3, -55)
part(Enum.PartType.Cylinder, Vector3.new(2, 70, 70), hatchCenter, Color3.fromRGB(245, 235, 255), Enum.Material.SmoothPlastic).CFrame =
	CFrame.new(hatchCenter) * CFrame.Angles(0, 0, math.rad(90))
for i = 0, 5 do
	local ang = math.rad(i * 60)
	local pos = hatchCenter + Vector3.new(math.cos(ang) * 24, 4, math.sin(ang) * 24)
	part(Enum.PartType.Cylinder, Vector3.new(8, 6, 6), pos, Color3.fromRGB(235, 220, 255), Enum.Material.SmoothPlastic).CFrame =
		CFrame.new(pos) * CFrame.Angles(0, 0, math.rad(90))
	local egg = part(Enum.PartType.Ball, Vector3.new(7, 9, 7), pos + Vector3.new(0, 8, 0), PASTELS[(i % #PASTELS) + 1], Enum.Material.Neon)
	local glow = Instance.new("PointLight")
	glow.Brightness = 3
	glow.Range = 16
	glow.Color = egg.Color
	glow.Parent = egg
end

-- Trading gazebo in the centre
local gazeboTop = part(Enum.PartType.Cylinder, Vector3.new(2, 36, 36), Vector3.new(0, 22, 0), Color3.fromRGB(255, 150, 200), Enum.Material.SmoothPlastic)
gazeboTop.CFrame = CFrame.new(0, 22, 0) * CFrame.Angles(0, 0, math.rad(90))
for i = 0, 5 do
	local ang = math.rad(i * 60)
	part(Enum.PartType.Cylinder, Vector3.new(20, 1.5, 1.5), Vector3.new(math.cos(ang) * 14, 11, math.sin(ang) * 14), Color3.fromRGB(255, 245, 250), Enum.Material.Marble).CFrame =
		CFrame.new(math.cos(ang) * 14, 11, math.sin(ang) * 14) * CFrame.Angles(0, 0, math.rad(90))
end

-- A simple pastel building (the shop) with a bright roof
local function building(center: Vector3, color: Color3, roof: Color3)
	part(Enum.PartType.Block, Vector3.new(28, 18, 28), center + Vector3.new(0, 9, 0), color, Enum.Material.SmoothPlastic)
	part(Enum.PartType.Block, Vector3.new(34, 6, 34), center + Vector3.new(0, 21, 0), roof, Enum.Material.SmoothPlastic).CFrame =
		CFrame.new(center + Vector3.new(0, 21, 0)) * CFrame.Angles(0, math.rad(45), 0)
end
building(Vector3.new(70, 2, 40), Color3.fromRGB(255, 220, 235), Color3.fromRGB(120, 200, 255))   -- Shop
building(Vector3.new(-70, 2, 40), Color3.fromRGB(220, 235, 255), Color3.fromRGB(255, 180, 120))  -- Pet display

-- Procedural trees, bushes and flowers scattered everywhere
local function tree(pos: Vector3)
	part(Enum.PartType.Cylinder, Vector3.new(10, 3, 3), pos + Vector3.new(0, 5, 0), DIRT, Enum.Material.Wood).CFrame =
		CFrame.new(pos + Vector3.new(0, 5, 0)) * CFrame.Angles(0, 0, math.rad(90))
	part(Enum.PartType.Ball, Vector3.new(14, 14, 14), pos + Vector3.new(0, 13, 0), Color3.fromRGB(110, 210, 130), Enum.Material.Grass)
end
for _ = 1, 40 do
	local ang = math.rad(math.random(0, 360))
	local r = math.random(20, 115)
	local pos = Vector3.new(math.cos(ang) * r, 2, math.sin(ang) * r)
	local roll = math.random(1, 3)
	if roll == 1 then
		tree(pos)
	elseif roll == 2 then
		part(Enum.PartType.Ball, Vector3.new(6, 5, 6), pos + Vector3.new(0, 2, 0), Color3.fromRGB(130, 215, 140), Enum.Material.Grass)
	else
		part(Enum.PartType.Cylinder, Vector3.new(2, 1.5, 1.5), pos + Vector3.new(0, 2, 0), PASTELS[math.random(#PASTELS)], Enum.Material.Neon).CFrame =
			CFrame.new(pos + Vector3.new(0, 2, 0)) * CFrame.Angles(0, 0, math.rad(90))
	end
end

-- Sparkle particles drifting across the whole map
local sparkleAnchor = part(Enum.PartType.Block, Vector3.new(200, 1, 200), Vector3.new(0, 30, 0), Color3.fromRGB(255, 255, 255), Enum.Material.Neon)
sparkleAnchor.Transparency = 1
sparkleAnchor.CanCollide = false
local sparkles = Instance.new("ParticleEmitter")
sparkles.Texture = "rbxassetid://6101304403"
sparkles.Rate = 25
sparkles.Lifetime = NumberRange.new(3, 6)
sparkles.Speed = NumberRange.new(0, 2)
sparkles.Color = ColorSequence.new(Color3.fromRGB(255, 250, 200))
sparkles.LightEmission = 1
sparkles.Parent = sparkleAnchor

-- Ambient happy music placeholder (id configured post-publish; see SoundService)
local music = Instance.new("Sound")
music.Name = "AmbientMusic"
music.Looped = true
music.Volume = 0.3
music.Parent = Workspace

-- Decoration zones for the DecorationService pass
local function decoZone(pos: Vector3, size: Vector3)
	local zone = part(Enum.PartType.Block, size, pos, Color3.fromRGB(0, 0, 0), Enum.Material.SmoothPlastic)
	zone.Transparency = 1
	zone.CanCollide = false
	CollectionService:AddTag(zone, "DecorationZone")
end
decoZone(Vector3.new(0, 2, 60), Vector3.new(120, 1, 60))
for _, c in satellites do
	decoZone(c + Vector3.new(0, 4, 0), Vector3.new(60, 1, 60))
end

-- Spawn on the main island
local spawn = Instance.new("SpawnLocation")
spawn.Anchored = true
spawn.Size = Vector3.new(12, 1, 12)
spawn.Position = Vector3.new(0, 4, 30)
spawn.Color = Color3.fromRGB(255, 220, 235)
spawn.Material = Enum.Material.Neon
spawn.Parent = map

local _ = ReplicatedStorage

-- ── Navigation landmarks: glowing beacons + pathways (wayfinding) ─────────
-- Wrapped in a do-block so its locals never collide with the map code above.
do
	local CYAN = Color3.fromRGB(0, 255, 255)
	local GOLD = Color3.fromRGB(255, 215, 0)
	local GREEN = Color3.fromRGB(60, 220, 90)
	local PURPLE = Color3.fromRGB(180, 80, 255)

	local function placeBeacon(pos: Vector3, color: Color3, labelText: string)
		local pillar = Instance.new("Part")
		pillar.Anchored = true
		pillar.CanCollide = false
		pillar.Size = Vector3.new(2, 18, 2)
		pillar.Position = pos + Vector3.new(0, 9, 0)
		pillar.Color = color
		pillar.Material = Enum.Material.Neon
		pillar.Transparency = 0.1
		pillar.Parent = map

		local orb = Instance.new("Part")
		orb.Anchored = true
		orb.CanCollide = false
		orb.Shape = Enum.PartType.Ball
		orb.Size = Vector3.new(4, 4, 4)
		orb.Position = pos + Vector3.new(0, 19, 0)
		orb.Color = color
		orb.Material = Enum.Material.Neon
		orb.Parent = map

		local light = Instance.new("PointLight")
		light.Color = color
		light.Brightness = 3
		light.Range = 30
		light.Parent = orb

		local emitter = Instance.new("ParticleEmitter")
		emitter.Color = ColorSequence.new(color)
		emitter.Rate = 10
		emitter.Lifetime = NumberRange.new(1, 2)
		emitter.Speed = NumberRange.new(2, 5)
		emitter.Size = NumberSequence.new(0.8)
		emitter.Transparency = NumberSequence.new(0.3, 1)
		emitter.Parent = orb

		local billboard = Instance.new("BillboardGui")
		billboard.Size = UDim2.fromOffset(120, 34)
		billboard.StudsOffset = Vector3.new(0, 3, 0)
		billboard.MaxDistance = 320
		billboard.Adornee = orb
		billboard.Parent = orb

		local label = Instance.new("TextLabel")
		label.Size = UDim2.fromScale(1, 1)
		label.BackgroundTransparency = 1
		label.Text = labelText
		label.TextColor3 = color
		label.TextStrokeTransparency = 0.3
		label.Font = Enum.Font.GothamBold
		label.TextScaled = true
		label.Parent = billboard
	end

	local function placePath(fromPos: Vector3, toPos: Vector3, color: Color3)
		local delta = toPos - fromPos
		local length = delta.Magnitude
		if length < 1 then
			return
		end
		local center = fromPos + delta / 2
		local path = Instance.new("Part")
		path.Anchored = true
		path.CanCollide = false
		path.Size = Vector3.new(6, 0.2, length)
		path.CFrame = CFrame.lookAt(center, toPos)
		path.Color = color
		path.Material = Enum.Material.Neon
		path.Transparency = 0.4
		path.Parent = map
	end

	placePath(Vector3.new(0, 4, 25), Vector3.new(0, 4, -50), Color3.fromRGB(255, 220, 120))
	placeBeacon(Vector3.new(0, 5, 30), CYAN, "SPAWN")
	placeBeacon(Vector3.new(0, 5, -55), GREEN, "HATCH")
	placeBeacon(Vector3.new(70, 5, 40), GOLD, "SHOP")
	placeBeacon(Vector3.new(-70, 5, 40), PURPLE, "PETS")
end
