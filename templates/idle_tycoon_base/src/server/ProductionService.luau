--!strict
-- ProductionService: per-player dropper loop. Drops {{PRODUCT_NAME}} parts
-- that award currency when they reach the collector. Income is computed
-- entirely on the server from the player's upgrade levels.

local Players = game:GetService("Players")
local Debris = game:GetService("Debris")
local ServerStorage = game:GetService("ServerStorage")

-- Live event multiplier (EventsService contract; absent → 1).
local function eventMult(effectType: string): number
	local fn = ServerStorage:FindFirstChild("GetEventMultiplier")
	if fn and fn:IsA("BindableFunction") then
		local ok, m = pcall(function()
			return fn:Invoke(effectType)
		end)
		if ok and typeof(m) == "number" then
			return m
		end
	end
	return 1
end

local Config = require(game.ReplicatedStorage.Shared.Config)
local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)

local ProductionService = {}

local activeLoops: { [number]: boolean } = {}

local function getUpgradeLevel(data: any, upgradeName: string): number
	local upgrade = data.Upgrades[upgradeName]
	return upgrade and upgrade.Level or 0
end

function ProductionService.ComputeStats(player: Player): (number, number, number)
	-- Returns: dropValue, dropInterval, dropperCount
	local data = DataService.Get(player)
	if not data then
		return Config.BaseDropValue, Config.DropIntervalSeconds, 1
	end

	local value = Config.BaseDropValue
	local interval = Config.DropIntervalSeconds
	local droppers = 1

	for _, upgradeDef in Config.Upgrades do
		local level = getUpgradeLevel(data, upgradeDef.Name)
		if level > 0 then
			if upgradeDef.Effect == "value" then
				value *= upgradeDef.EffectValue ^ level
			elseif upgradeDef.Effect == "interval" then
				interval *= upgradeDef.EffectValue ^ level
			elseif upgradeDef.Effect == "dropper" then
				droppers += upgradeDef.EffectValue * level
			end
		end
	end

	-- Prestige multiplier
	value *= 1 + data.PrestigeLevel * Config.PrestigeMultiplierPerLevel

	-- VIP-style game pass multipliers applied via ShopService pass effects
	for passId, owned in data.OwnedPasses do
		if owned then
			for _, passDef in Config.GamePasses do
				if passDef.id == passId and passDef.effect == "income_x2" then
					value *= 2
				end
			end
		end
	end

	-- Bonuses from drop-in systems (absent → no-op): RetentionService
	-- streaks and MonetizationService VIP/season/founders multipliers
	local streakMult = player:GetAttribute("StreakMultiplier")
	if typeof(streakMult) == "number" then
		value *= streakMult
	end
	local monetizationMult = player:GetAttribute("MonetizationMultiplier")
	if typeof(monetizationMult) == "number" then
		value *= monetizationMult
	end

	-- Live events: 2x coins (happy_hour), faster drops (speed_round)
	value *= eventMult("coin_multiplier")
	interval *= eventMult("cooldown_multiplier")

	return value, math.max(0.25, interval), math.floor(droppers)
end

local function dropOne(player: Player, plot: Model, value: number)
	local anchors = plot:FindFirstChild("DropperAnchors")
	local collector = plot:FindFirstChild("Collector")
	if not anchors or not collector then
		return
	end
	local anchorList = anchors:GetChildren()
	local anchor = anchorList[math.random(1, #anchorList)] :: Part

	local product = Instance.new("Part")
	product.Name = "{{PRODUCT_NAME}}"
	product.Size = Vector3.new(1.5, 1.5, 1.5)
	product.Position = anchor.Position
	product.Color = Color3.fromRGB(200, 150, 60)
	product.Parent = workspace
	Debris:AddItem(product, 15)

	local touched: boolean = false
	product.Touched:Connect(function(hit: BasePart)
		if touched then
			return
		end
		if hit == collector then
			touched = true
			DataService.AddCurrency(player, value)
			product:Destroy()
		end
	end)
end

function ProductionService.StartLoop(player: Player)
	if activeLoops[player.UserId] then
		return
	end
	activeLoops[player.UserId] = true

	task.spawn(function()
		while activeLoops[player.UserId] and player.Parent do
			local plot = PlotService.GetPlot(player)
			if plot then
				local value, interval, droppers = ProductionService.ComputeStats(player)
				for _ = 1, droppers do
					dropOne(player, plot, value)
				end
				task.wait(interval)
			else
				task.wait(1)
			end
		end
	end)
end

function ProductionService.StopLoop(player: Player)
	activeLoops[player.UserId] = nil
end

function ProductionService.Init()
	Players.PlayerRemoving:Connect(ProductionService.StopLoop)
end

return ProductionService
