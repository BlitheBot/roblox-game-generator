-- MapBuilder — builds a fully enclosed industrial facility on server start.
-- No generated game ever ships as an open baseplate; this constructs a
-- complete warehouse (300 x 200 x 40 studs) with rooms, columns, conveyor
-- tracks, windows, ceiling lighting and an entrance lobby with a sign.
local Workspace = game:GetService("Workspace")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")

local FLOOR_X, FLOOR_Z = 300, 200
local WALL_HEIGHT = 40
local WALL_THICK = 2

local CONCRETE = Color3.fromRGB(150, 150, 155)
local METAL = Color3.fromRGB(70, 74, 80)
local ACCENT = Color3.fromRGB(255, 200, 60)
local WINDOW = Color3.fromRGB(90, 170, 255)

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

-- Floor (concrete) and ceiling
block(Vector3.new(FLOOR_X, WALL_THICK, FLOOR_Z), Vector3.new(0, 0, 0), CONCRETE, Enum.Material.Concrete)
local ceiling = block(Vector3.new(FLOOR_X, WALL_THICK, FLOOR_Z), Vector3.new(0, WALL_HEIGHT, 0), METAL, Enum.Material.Metal)
ceiling.Color = Color3.fromRGB(55, 58, 62)

-- Perimeter walls (metal, industrial)
local halfX, halfZ = FLOOR_X / 2, FLOOR_Z / 2
local midY = WALL_HEIGHT / 2
block(Vector3.new(FLOOR_X, WALL_HEIGHT, WALL_THICK), Vector3.new(0, midY, -halfZ), METAL, Enum.Material.Metal)
block(Vector3.new(FLOOR_X, WALL_HEIGHT, WALL_THICK), Vector3.new(0, midY, halfZ), METAL, Enum.Material.Metal)
block(Vector3.new(WALL_THICK, WALL_HEIGHT, FLOOR_Z), Vector3.new(-halfX, midY, 0), METAL, Enum.Material.Metal)
block(Vector3.new(WALL_THICK, WALL_HEIGHT, FLOOR_Z), Vector3.new(halfX, midY, 0), METAL, Enum.Material.Metal)

-- Upper windows (thin neon strips letting light in) along the long walls
for x = -halfX + 30, halfX - 30, 40 do
	for _, z in { -halfZ + 1, halfZ - 1 } do
		local w = block(Vector3.new(20, 8, 0.5), Vector3.new(x, WALL_HEIGHT - 9, z), WINDOW, Enum.Material.Neon)
		w.Transparency = 0.35
	end
end

-- Support columns every 50 studs + ceiling light strips
for x = -halfX + 50, halfX - 50, 50 do
	for z = -halfZ + 50, halfZ - 50, 50 do
		block(Vector3.new(5, WALL_HEIGHT, 5), Vector3.new(x, midY, z), Color3.fromRGB(60, 62, 66), Enum.Material.Metal)
	end
	-- light strip running the length of the building above this column row
	local strip = block(Vector3.new(8, 1, FLOOR_Z - 20), Vector3.new(x, WALL_HEIGHT - 2, 0), Color3.fromRGB(255, 245, 220), Enum.Material.Neon)
	for z = -halfZ + 25, halfZ - 25, 50 do
		local light = Instance.new("PointLight")
		light.Brightness = 2
		light.Range = 45
		light.Color = Color3.fromRGB(255, 240, 210)
		local anchor = block(Vector3.new(1, 1, 1), Vector3.new(x, WALL_HEIGHT - 3, z), Color3.fromRGB(255, 245, 220), Enum.Material.Neon)
		anchor.Transparency = 1
		light.Parent = anchor
	end
	local _ = strip
end

-- Interior partition walls dividing rooms (with doorway gaps)
local function partition(x: number, doorZ: number)
	-- two segments leaving a 14-stud doorway centered on doorZ
	local segLen = (FLOOR_Z - 14) / 2
	block(Vector3.new(WALL_THICK, WALL_HEIGHT, segLen), Vector3.new(x, midY, -halfZ + segLen / 2), Color3.fromRGB(90, 94, 100), Enum.Material.Metal)
	block(Vector3.new(WALL_THICK, WALL_HEIGHT, segLen), Vector3.new(x, midY, halfZ - segLen / 2), Color3.fromRGB(90, 94, 100), Enum.Material.Metal)
	local _ = doorZ
end
partition(-75, 0) -- Lobby | Main Production Floor
partition(75, 0)  -- Main Production Floor | Shops/Prestige/VIP wing

-- Room name signs hovering near each zone
local Config
local ok, mod = pcall(function()
	return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
end)
if ok then
	Config = mod
end
local gameTitle = (Config and Config.GameTitle) or "Welcome"

local function sign(text: string, pos: Vector3, color: Color3)
	local post = block(Vector3.new(6, 3, 1), pos, color, Enum.Material.SmoothPlastic)
	local gui = Instance.new("SurfaceGui")
	gui.Face = Enum.NormalId.Front
	gui.CanvasSize = Vector2.new(400, 200)
	gui.Parent = post
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.TextColor3 = Color3.fromRGB(20, 20, 25)
	label.Font = Enum.Font.GothamBold
	label.TextScaled = true
	label.Text = text
	label.Parent = gui
	return post
end

sign(gameTitle, Vector3.new(-130, 8, 0), ACCENT)            -- Entrance lobby welcome sign
sign("Production Floor", Vector3.new(0, WALL_HEIGHT - 6, -halfZ + 3), Color3.fromRGB(220, 220, 225))
sign("Upgrade Shop", Vector3.new(110, 8, -40), Color3.fromRGB(220, 220, 225))
sign("Prestige Room", Vector3.new(110, 8, 40), Color3.fromRGB(220, 220, 225))
sign("VIP Lounge", Vector3.new(130, 8, 0), Color3.fromRGB(255, 215, 120))

-- Decorative conveyor belt tracks (yellow/black striped) on the production floor
for i = 0, 5 do
	local z = -60 + i * 24
	local belt = block(Vector3.new(120, 1, 8), Vector3.new(0, 1, z), Color3.fromRGB(40, 40, 40), Enum.Material.DiamondPlate)
	for x = -55, 55, 14 do
		block(Vector3.new(6, 1.1, 8), Vector3.new(x, 1.1, z), ACCENT, Enum.Material.SmoothPlastic)
	end
	CollectionService:AddTag(belt, "DecorationZone")
end

-- Decorative machinery props scattered through the floor
for i = 1, 14 do
	local x = (math.random(-130, 130))
	local z = (math.random(-90, 90))
	local box = block(Vector3.new(math.random(4, 9), math.random(4, 10), math.random(4, 9)), Vector3.new(x, 5, z), Color3.fromRGB(80, 84, 92), Enum.Material.Metal)
	local cyl = Instance.new("Part")
	cyl.Shape = Enum.PartType.Cylinder
	cyl.Anchored = true
	cyl.Size = Vector3.new(6, 4, 4)
	cyl.CFrame = CFrame.new(box.Position + Vector3.new(0, 5, 0)) * CFrame.Angles(0, 0, math.rad(90))
	cyl.Color = ACCENT
	cyl.Material = Enum.Material.Metal
	cyl.Parent = map
end

-- Designated decoration zones for the DecorationService pass
local function decoZone(pos: Vector3, size: Vector3)
	local zone = block(size, pos, Color3.fromRGB(0, 0, 0), Enum.Material.SmoothPlastic)
	zone.Transparency = 1
	zone.CanCollide = false
	CollectionService:AddTag(zone, "DecorationZone")
end
decoZone(Vector3.new(-110, 1, -60), Vector3.new(40, 1, 60)) -- lobby
decoZone(Vector3.new(110, 1, 0), Vector3.new(60, 1, 120))   -- shop/prestige wing

-- Clean entrance lobby + spawn
local spawn = Instance.new("SpawnLocation")
spawn.Anchored = true
spawn.Size = Vector3.new(12, 1, 12)
spawn.Position = Vector3.new(-130, 1, 0)
spawn.Color = ACCENT
spawn.Material = Enum.Material.Neon
spawn.Parent = map

-- Simple exterior shell so the building reads as professional from spawn
local exterior = block(Vector3.new(FLOOR_X + 16, 4, FLOOR_Z + 16), Vector3.new(0, -2, 0), Color3.fromRGB(120, 122, 128), Enum.Material.Concrete)
local _ = exterior
