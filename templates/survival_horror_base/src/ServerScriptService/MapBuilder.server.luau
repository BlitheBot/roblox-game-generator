-- MapBuilder — builds a dark, fully enclosed abandoned facility on server
-- start so no generated game ships as an open baseplate. 400 x 300 x 35
-- studs split into Main Hall, Corridors, Safe Room, Monster Spawn Room and
-- Exit Room, with flickering lights, emergency lighting, broken walls,
-- blood splatter, debris and a locked door that opens during gameplay.
local Workspace = game:GetService("Workspace")
local CollectionService = game:GetService("CollectionService")
local TweenService = game:GetService("TweenService")
local RunService = game:GetService("RunService")

local FLOOR_X, FLOOR_Z = 400, 300
local WALL_HEIGHT = 35
local WALL_THICK = 2
local CONCRETE = Color3.fromRGB(60, 62, 64)
local DAMAGED = Color3.fromRGB(48, 46, 44)

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

local halfX, halfZ, midY = FLOOR_X / 2, FLOOR_Z / 2, WALL_HEIGHT / 2

-- Floor, ceiling, perimeter walls
block(Vector3.new(FLOOR_X, WALL_THICK, FLOOR_Z), Vector3.new(0, 0, 0), CONCRETE, Enum.Material.Concrete)
block(Vector3.new(FLOOR_X, WALL_THICK, FLOOR_Z), Vector3.new(0, WALL_HEIGHT, 0), Color3.fromRGB(40, 40, 42), Enum.Material.Concrete)
block(Vector3.new(FLOOR_X, WALL_HEIGHT, WALL_THICK), Vector3.new(0, midY, -halfZ), CONCRETE, Enum.Material.Concrete)
block(Vector3.new(FLOOR_X, WALL_HEIGHT, WALL_THICK), Vector3.new(0, midY, halfZ), CONCRETE, Enum.Material.Concrete)
block(Vector3.new(WALL_THICK, WALL_HEIGHT, FLOOR_Z), Vector3.new(-halfX, midY, 0), CONCRETE, Enum.Material.Concrete)
block(Vector3.new(WALL_THICK, WALL_HEIGHT, FLOOR_Z), Vector3.new(halfX, midY, 0), CONCRETE, Enum.Material.Concrete)

-- Interior partitions create five rooms (segments leave doorway gaps)
local function partitionZ(x: number)
	local segLen = (FLOOR_Z - 16) / 2
	block(Vector3.new(WALL_THICK, WALL_HEIGHT, segLen), Vector3.new(x, midY, -halfZ + segLen / 2), DAMAGED, Enum.Material.Concrete)
	block(Vector3.new(WALL_THICK, WALL_HEIGHT, segLen), Vector3.new(x, midY, halfZ - segLen / 2), DAMAGED, Enum.Material.Concrete)
end
partitionZ(-120) -- Safe Room | Main Hall
partitionZ(60)   -- Main Hall | Corridors
partitionZ(150)  -- Corridors | Monster Spawn / Exit

-- Flickering ceiling lights spread across the ceiling
local flickerLights = {}
for x = -halfX + 40, halfX - 40, 70 do
	for z = -halfZ + 40, halfZ - 40, 70 do
		local fixture = block(Vector3.new(6, 1, 6), Vector3.new(x, WALL_HEIGHT - 2, z), Color3.fromRGB(180, 180, 170), Enum.Material.Neon)
		local light = Instance.new("PointLight")
		light.Brightness = 1.5
		light.Range = 30
		light.Color = Color3.fromRGB(200, 205, 190)
		light.Parent = fixture
		table.insert(flickerLights, { fixture = fixture, light = light })
	end
end

-- Flicker: randomly toggle a subset of lights every 2-8s. Driven by a
-- Heartbeat accumulator (no while-true loop) so it stays frame-budget cheap.
local nextFlicker = 0
RunService.Heartbeat:Connect(function()
	local now = os.clock()
	if now < nextFlicker then
		return
	end
	nextFlicker = now + math.random(2, 8)
	local entry = flickerLights[math.random(#flickerLights)]
	if entry then
		local on = math.random() > 0.4
		entry.light.Enabled = on
		entry.fixture.Material = on and Enum.Material.Neon or Enum.Material.Slate
	end
end)

-- Emergency red lighting in the monster spawn / exit wing
for _, z in { -80, 0, 80 } do
	local lamp = block(Vector3.new(2, 4, 4), Vector3.new(halfX - 6, 10, z), Color3.fromRGB(120, 20, 20), Enum.Material.Neon)
	local red = Instance.new("PointLight")
	red.Brightness = 4
	red.Range = 28
	red.Color = Color3.fromRGB(255, 40, 40)
	red.Parent = lamp
end

-- Broken / damaged wall chunks at angles, and broken windows
for _ = 1, 16 do
	local pos = Vector3.new(math.random(-halfX + 20, halfX - 20), math.random(3, 14), math.random(-halfZ + 20, halfZ - 20))
	local chunk = block(Vector3.new(math.random(3, 8), math.random(3, 8), math.random(2, 5)), pos, DAMAGED, Enum.Material.Concrete)
	chunk.CFrame = CFrame.new(pos) * CFrame.Angles(math.rad(math.random(-40, 40)), math.rad(math.random(0, 360)), math.rad(math.random(-40, 40)))
end
for x = -halfX + 60, halfX - 60, 90 do
	local win = block(Vector3.new(16, 10, 0.5), Vector3.new(x, WALL_HEIGHT - 11, -halfZ + 1), Color3.fromRGB(30, 40, 45), Enum.Material.Glass)
	win.Transparency = 0.6
end

-- Blood splatter on the floors (semi-transparent red discs)
for _ = 1, 12 do
	local pos = Vector3.new(math.random(-halfX + 20, halfX - 20), 1.1, math.random(-halfZ + 20, halfZ - 20))
	local splat = Instance.new("Part")
	splat.Shape = Enum.PartType.Cylinder
	splat.Anchored = true
	splat.CanCollide = false
	splat.Size = Vector3.new(0.2, math.random(4, 10), math.random(4, 10))
	splat.CFrame = CFrame.new(pos) * CFrame.Angles(0, 0, math.rad(90))
	splat.Color = Color3.fromRGB(90, 10, 10)
	splat.Material = Enum.Material.SmoothPlastic
	splat.Transparency = 0.35
	splat.Parent = map
end

-- Debris / rubble piles
for _ = 1, 24 do
	local pos = Vector3.new(math.random(-halfX + 15, halfX - 15), math.random(1, 4), math.random(-halfZ + 15, halfZ - 15))
	local d = block(Vector3.new(math.random(1, 4), math.random(1, 4), math.random(1, 4)), pos, Color3.fromRGB(55, 52, 48), Enum.Material.Slate)
	d.CFrame = CFrame.new(pos) * CFrame.Angles(math.rad(math.random(0, 360)), math.rad(math.random(0, 360)), 0)
end

-- Locked door between Corridors and the Monster Spawn Room; opens during play
local door = block(Vector3.new(WALL_THICK, 16, 16), Vector3.new(150, 8, 0), Color3.fromRGB(90, 70, 40), Enum.Material.DiamondPlate)
task.spawn(function()
	task.wait(20) -- "opens during gameplay"
	local goalCF = door.CFrame * CFrame.new(0, 16, 0)
	TweenService:Create(door, TweenInfo.new(1.5, Enum.EasingStyle.Quad), { CFrame = goalCF }):Play()
end)

-- Horror ambient sound placeholder (id configured post-publish; see SoundService)
local ambient = Instance.new("Sound")
ambient.Name = "HorrorAmbience"
ambient.Looped = true
ambient.Volume = 0.3
ambient.Parent = Workspace

-- Decoration zones for the DecorationService pass
local function decoZone(pos: Vector3, size: Vector3)
	local zone = block(size, pos, Color3.fromRGB(0, 0, 0), Enum.Material.SmoothPlastic)
	zone.Transparency = 1
	zone.CanCollide = false
	CollectionService:AddTag(zone, "DecorationZone")
end
decoZone(Vector3.new(-30, 1, 0), Vector3.new(160, 1, 200)) -- main hall
decoZone(Vector3.new(250, 1, 0), Vector3.new(120, 1, 200)) -- monster wing

-- Spawn in the Safe Room (far left)
local spawn = Instance.new("SpawnLocation")
spawn.Anchored = true
spawn.Size = Vector3.new(12, 1, 12)
spawn.Position = Vector3.new(-170, 1, 0)
spawn.Color = Color3.fromRGB(60, 120, 90)
spawn.Material = Enum.Material.Neon
spawn.Parent = map

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

	placePath(Vector3.new(-160, 1, 0), Vector3.new(170, 1, 0), Color3.fromRGB(120, 0, 0))
	placeBeacon(Vector3.new(-170, 2, 0), CYAN, "SPAWN")
	placeBeacon(Vector3.new(-150, 2, 0), GREEN, "SAFE ROOM")
	placeBeacon(Vector3.new(180, 2, 0), GOLD, "EXIT")

	-- Invisible tagged anchors so the onboarding arrow can point at key zones.
	local function tagPoint(pos: Vector3, tag: string)
		local marker = Instance.new("Part")
		marker.Anchored = true
		marker.CanCollide = false
		marker.Transparency = 1
		marker.Size = Vector3.new(2, 2, 2)
		marker.Position = pos
		marker.Parent = map
		game:GetService("CollectionService"):AddTag(marker, tag)
	end
	tagPoint(Vector3.new(-150, 2, 0), "SafeRoom")
	tagPoint(Vector3.new(180, 2, 0), "ShopArea")
end
