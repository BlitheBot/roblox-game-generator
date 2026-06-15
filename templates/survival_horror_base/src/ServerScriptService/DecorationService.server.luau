-- DecorationService — scatters props through tagged "DecorationZone" areas
-- on server start so every game feels furnished, not empty. Uses the
-- resolved Toolbox assets from Config when they load, with a procedural
-- fallback so zones are never bare. survival_horror: medium, atmospheric debris.
local Workspace = game:GetService("Workspace")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local CollectionService = game:GetService("CollectionService")
local InsertService = game:GetService("InsertService")

-- Genre tuning
local SPACING = 15 -- medium: debris roughly every 15 studs
local PROP_HEIGHT = 4
local PALETTE = {
	Color3.fromRGB(55, 52, 48),
	Color3.fromRGB(40, 40, 42),
	Color3.fromRGB(70, 62, 52),
	Color3.fromRGB(48, 50, 52),
}
local SHAPES = { Enum.PartType.Block, Enum.PartType.Cylinder }

local Config
local okCfg, mod = pcall(function()
	return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
end)
if okCfg then
	Config = mod
end
local assetIds = (Config and Config.ToolboxAssetIds) or {}

local models = {}
for _, id in assetIds do
	if #models >= 8 then
		break
	end
	local okLoad, container = pcall(function()
		return InsertService:LoadAsset(id)
	end)
	if okLoad and container then
		table.insert(models, container:FindFirstChildWhichIsA("Model") or container)
	end
end

local decorations = Instance.new("Folder")
decorations.Name = "Decorations"
decorations.Parent = Workspace

local placed = {}
local function tooClose(pos: Vector3): boolean
	for _, p in placed do
		if (p - pos).Magnitude < SPACING * 0.6 then
			return true
		end
	end
	return false
end

local function proceduralProp(pos: Vector3)
	local p = Instance.new("Part")
	p.Anchored = true
	p.Shape = SHAPES[math.random(#SHAPES)]
	local h = PROP_HEIGHT * (0.6 + math.random() * 0.8)
	p.Size = Vector3.new(2 + math.random() * 3, h, 2 + math.random() * 3)
	p.Position = pos + Vector3.new(0, h / 2, 0)
	p.Color = PALETTE[math.random(#PALETTE)]
	p.Material = Enum.Material.Slate
	p.CFrame = CFrame.new(p.Position) * CFrame.Angles(math.rad(math.random(-20, 20)), math.rad(math.random(0, 360)), 0)
	p.Parent = decorations
end

local function toolboxProp(pos: Vector3)
	local clone = models[math.random(#models)]:Clone()
	if clone:IsA("Model") then
		pcall(function()
			local _, size = clone:GetBoundingBox()
			local tall = math.max(size.Y, 0.1)
			local target = PROP_HEIGHT * (0.8 + math.random() * 0.6)
			clone:ScaleTo(math.clamp(target / tall, 0.1, 8))
		end)
		clone.Parent = decorations
		pcall(function()
			clone:PivotTo(CFrame.new(pos) * CFrame.Angles(0, math.random() * math.pi * 2, 0))
		end)
	else
		clone.Parent = decorations
	end
end

local function placeProp(pos: Vector3)
	if #models > 0 and not pcall(toolboxProp, pos) then
		proceduralProp(pos)
	elseif #models == 0 then
		proceduralProp(pos)
	end
	table.insert(placed, pos)
end

for _, zone in CollectionService:GetTagged("DecorationZone") do
	if zone:IsA("BasePart") then
		local size, center = zone.Size, zone.Position
		local hx, hz = size.X / 2, size.Z / 2
		local jitter = SPACING * 0.3
		for x = -hx, hx, SPACING do
			for z = -hz, hz, SPACING do
				local pos = Vector3.new(
					center.X + x + (math.random() * 2 - 1) * jitter,
					1,
					center.Z + z + (math.random() * 2 - 1) * jitter
				)
				if not tooClose(pos) then
					placeProp(pos)
				end
			end
		end
	end
end

for _, obj in Workspace:GetDescendants() do
	if obj:IsA("BasePart") and obj.Material == Enum.Material.Neon then
		if math.random() < 0.12 and not obj:FindFirstChildWhichIsA("PointLight") then
			local l = Instance.new("PointLight")
			l.Range = 16
			l.Brightness = 1
			l.Color = obj.Color
			l.Parent = obj
		end
	end
end

for _, obj in Workspace:GetDescendants() do
	if obj:IsA("BasePart") then
		local n = string.lower(obj.Name)
		if (string.find(n, "spawn") or string.find(n, "shop") or string.find(n, "exit"))
			and not obj:FindFirstChildWhichIsA("ParticleEmitter") then
			local pe = Instance.new("ParticleEmitter")
			pe.Texture = "rbxassetid://6101304403"
			pe.Rate = 5
			pe.Lifetime = NumberRange.new(2, 4)
			pe.Speed = NumberRange.new(0, 1)
			pe.Color = ColorSequence.new(Color3.fromRGB(120, 130, 130))
			pe.LightEmission = 0.2
			pe.Parent = obj
		end
	end
end
