--!strict
-- Incremental sim server: resource tick → sell → rebirth loop with
-- DataStore persistence and a global leaderboard. All mutation server-side.

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestAction = Remotes:WaitForChild("RequestAction") :: RemoteEvent
local StateChanged = Remotes:WaitForChild("StateChanged") :: RemoteEvent

local store = nil
pcall(function()
	store = DataStoreService:GetDataStore("PlayerData_v1")
end)
local leaderboardStore = nil
pcall(function()
	leaderboardStore = DataStoreService:GetOrderedDataStore("TotalEarned_v1")
end)

local sessionData: { [number]: any } = {}

local function defaultData()
	return { Currency = 0, Resource = 0, RebirthLevel = 0, Upgrades = {}, TotalEarned = 0 }
end

local function load(player: Player)
	local data = defaultData()
	if store then
		local ok, saved = pcall(function()
			return store:GetAsync(tostring(player.UserId))
		end)
		if ok and saved then
			for k, v in saved do
				data[k] = v
			end
		end
	end
	sessionData[player.UserId] = data
end

local function save(player: Player)
	local data = sessionData[player.UserId]
	if data and store then
		pcall(function()
			store:SetAsync(tostring(player.UserId), data)
		end)
	end
	if data and leaderboardStore then
		pcall(function()
			leaderboardStore:SetAsync(tostring(player.UserId), math.floor(data.TotalEarned))
		end)
	end
end

local function upgradeLevel(data: any, name: string): number
	local u = data.Upgrades[name]
	return u and u.Level or 0
end

local function computeRates(data: any): (number, number)
	local growth = Config.BaseGrowthPerTick
	local sell = Config.BaseSellValue
	for _, def in Config.Upgrades do
		local level = upgradeLevel(data, def.Name)
		if level > 0 then
			if def.Effect == "growth" then
				growth *= def.EffectValue ^ level
			elseif def.Effect == "sell" then
				sell *= def.EffectValue ^ level
			end
		end
	end
	local rebirthBoost = 1 + data.RebirthLevel * Config.RebirthMultiplierPerLevel
	return growth * rebirthBoost, sell * rebirthBoost
end

local function pushState(player: Player)
	local data = sessionData[player.UserId]
	if not data then
		return
	end
	StateChanged:FireClient(player, {
		Currency = data.Currency,
		Resource = data.Resource,
		RebirthLevel = data.RebirthLevel,
		Upgrades = data.Upgrades,
		CanRebirth = data.Currency >= Config.RebirthRequirement,
	})
end

-- Currency grant hook for drop-in systems (e.g. RetentionService daily
-- rewards). Optional contract: systems fire (player, amount) server-side.
local grantCurrency = Instance.new("BindableEvent")
grantCurrency.Name = "GrantCurrency"
grantCurrency.Parent = ServerStorage
grantCurrency.Event:Connect(function(player: Player, amount: number)
	local data = sessionData[player.UserId]
	if data and typeof(amount) == "number" and amount > 0 then
		data.Currency += amount
		data.TotalEarned += amount
		pushState(player)
	end
end)

-- Companion spend hook (e.g. MonetizationService shop purchases)
local trySpendCurrency = Instance.new("BindableFunction")
trySpendCurrency.Name = "TrySpendCurrency"
trySpendCurrency.Parent = ServerStorage
trySpendCurrency.OnInvoke = function(player: Player, amount: number): boolean
	local data = sessionData[player.UserId]
	if not data or typeof(amount) ~= "number" or amount <= 0 or data.Currency < amount then
		return false
	end
	data.Currency -= amount
	pushState(player)
	return true
end

Players.PlayerAdded:Connect(function(player)
	load(player)
	task.spawn(function()
		while player.Parent do
			local data = sessionData[player.UserId]
			if data then
				local growth = computeRates(data)
				-- Bonuses from drop-in systems (absent → 1): retention
				-- streaks and monetization multipliers
				local streakMult = player:GetAttribute("StreakMultiplier")
				if typeof(streakMult) == "number" then
					growth *= streakMult
				end
				local monetizationMult = player:GetAttribute("MonetizationMultiplier")
				if typeof(monetizationMult) == "number" then
					growth *= monetizationMult
				end
				data.Resource += growth
				pushState(player)
			end
			task.wait(Config.TickSeconds)
		end
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	save(player)
	sessionData[player.UserId] = nil
end)

game:BindToClose(function()
	for _, player in Players:GetPlayers() do
		save(player)
	end
end)

-- Single action remote with validated kinds: "sell" | "upgrade" | "rebirth"
RequestAction.OnServerEvent:Connect(function(player: Player, action: unknown, arg: unknown)
	local data = sessionData[player.UserId]
	if not data or typeof(action) ~= "string" then
		return
	end

	if action == "sell" then
		local _, sellValue = computeRates(data)
		local earned = data.Resource * sellValue
		data.Currency += earned
		data.TotalEarned += earned
		data.Resource = 0
	elseif action == "upgrade" and typeof(arg) == "string" then
		for _, def in Config.Upgrades do
			if def.Name == arg then
				local level = upgradeLevel(data, def.Name)
				if level >= def.MaxLevel then
					return
				end
				local cost = math.floor(def.BaseCost * def.CostMultiplier ^ level)
				if data.Currency >= cost then
					data.Currency -= cost
					data.Upgrades[def.Name] = { Level = level + 1 }
				end
				break
			end
		end
	elseif action == "rebirth" then
		if data.Currency >= Config.RebirthRequirement then
			data.Currency = 0
			data.Resource = 0
			data.Upgrades = {}
			data.RebirthLevel += 1
			save(player)
		end
	else
		return
	end
	pushState(player)
end)

print(("[%s] server initialized"):format(Config.GameTitle))
