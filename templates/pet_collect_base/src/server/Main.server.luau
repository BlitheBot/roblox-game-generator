--!strict
-- Pet collect server: hatch eggs with weighted rarity rolls, manage
-- inventory/equip slots, passive income from equipped pet power, and
-- player-to-player trade requests. All rolls and validation server-side.

local DataStoreService = game:GetService("DataStoreService")
local HttpService = game:GetService("HttpService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestHatch = Remotes:WaitForChild("RequestHatch") :: RemoteEvent
local RequestEquip = Remotes:WaitForChild("RequestEquip") :: RemoteEvent
local RequestTrade = Remotes:WaitForChild("RequestTrade") :: RemoteEvent
local StateChanged = Remotes:WaitForChild("StateChanged") :: RemoteEvent
local PlaySound = Remotes:WaitForChild("PlaySound") :: RemoteEvent
local OnboardingStepComplete = Remotes:WaitForChild("OnboardingStepComplete") :: RemoteEvent

local store = nil
pcall(function()
	store = DataStoreService:GetDataStore("PlayerData_v1")
end)

local sessionData: { [number]: any } = {}
-- Pending trades: requesterUserId -> { target: number, petId: string }
local pendingTrades: { [number]: { target: number, petId: string } } = {}

local function defaultData()
	return { Currency = Config.StartingCurrency, Pets = {}, Equipped = {} }
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
end

local function rollRarity(weightBonus: number): any
	-- weightBonus shifts odds toward rarer tiers by dividing common weights
	local total = 0
	local weights: { number } = {}
	for i, rarity in Config.Rarities do
		local w = rarity.Weight
		if i <= 2 and weightBonus > 1 then
			w /= weightBonus
		end
		weights[i] = w
		total += w
	end
	local roll = math.random() * total
	for i, rarity in Config.Rarities do
		roll -= weights[i]
		if roll <= 0 then
			return rarity
		end
	end
	return Config.Rarities[1]
end

local function pickPetName(rarityName: string): string
	local pool = Config.PetNames[rarityName]
	if pool and #pool > 0 then
		return pool[math.random(1, #pool)]
	end
	return rarityName .. " " .. Config.PetNoun
end

local function equippedPower(data: any): number
	local power = 0
	for _, petId in data.Equipped do
		local pet = data.Pets[petId]
		if pet then
			power += pet.Power
		end
	end
	return math.max(1, power)
end

local function pushState(player: Player)
	local data = sessionData[player.UserId]
	if not data then
		return
	end
	StateChanged:FireClient(player, {
		Currency = data.Currency,
		Pets = data.Pets,
		Equipped = data.Equipped,
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
	pushState(player)
	task.spawn(function()
		while player.Parent do
			local data = sessionData[player.UserId]
			if data then
				-- Bonuses from drop-in systems (absent → 1): retention
				-- streaks and monetization multipliers
				local streakMult = player:GetAttribute("StreakMultiplier")
				local monetizationMult = player:GetAttribute("MonetizationMultiplier")
				local mult = (if typeof(streakMult) == "number" then streakMult else 1)
					* (if typeof(monetizationMult) == "number" then monetizationMult else 1)
				data.Currency += Config.BaseIncomePerSecond * equippedPower(data) * mult
				pushState(player)
			end
			task.wait(1)
		end
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	save(player)
	sessionData[player.UserId] = nil
	pendingTrades[player.UserId] = nil
end)

game:BindToClose(function()
	for _, player in Players:GetPlayers() do
		save(player)
	end
end)

RequestHatch.OnServerEvent:Connect(function(player: Player, eggName: unknown)
	local data = sessionData[player.UserId]
	if not data or typeof(eggName) ~= "string" then
		return
	end
	for _, egg in Config.Eggs do
		if egg.Name == eggName then
			if data.Currency < egg.Cost then
				return
			end
			data.Currency -= egg.Cost
			local rarity = rollRarity(egg.WeightBonus or 1)
			local petId = HttpService:GenerateGUID(false)
			data.Pets[petId] = {
				Name = pickPetName(rarity.Name),
				Rarity = rarity.Name,
				Power = rarity.Power,
			}
			pushState(player)
			PlaySound:FireClient(player, "pet_collect.egg_crack")
			PlaySound:FireClient(player, "rarity_" .. string.lower(rarity.Name))
			OnboardingStepComplete:FireClient(player, "EggOpened")
			return
		end
	end
end)

RequestEquip.OnServerEvent:Connect(function(player: Player, petId: unknown)
	local data = sessionData[player.UserId]
	if not data or typeof(petId) ~= "string" or not data.Pets[petId] then
		return
	end
	-- Toggle: unequip if already equipped
	for i, equippedId in data.Equipped do
		if equippedId == petId then
			table.remove(data.Equipped, i)
			pushState(player)
			return
		end
	end
	if #data.Equipped < Config.MaxEquipped then
		table.insert(data.Equipped, petId)
		pushState(player)
		PlaySound:FireClient(player, "pet_collect.pet_equip")
		OnboardingStepComplete:FireClient(player, "PetEquipped")
	end
end)

-- Simple trade: offer a pet to another player; they accept by offering back.
-- Both sides validated server-side; pets swap atomically.
RequestTrade.OnServerEvent:Connect(function(player: Player, targetUserId: unknown, petId: unknown)
	local data = sessionData[player.UserId]
	if not data or typeof(targetUserId) ~= "number" or typeof(petId) ~= "string" then
		return
	end
	if not data.Pets[petId] then
		return
	end
	local target = Players:GetPlayerByUserId(targetUserId)
	if not target then
		return
	end

	local existing = pendingTrades[targetUserId]
	if existing and existing.target == player.UserId then
		-- Counter-offer exists: execute the swap
		local targetData = sessionData[targetUserId]
		if targetData and targetData.Pets[existing.petId] then
			local myPet = data.Pets[petId]
			local theirPet = targetData.Pets[existing.petId]
			data.Pets[petId] = nil
			targetData.Pets[existing.petId] = nil
			data.Pets[existing.petId] = theirPet
			targetData.Pets[petId] = myPet
			pendingTrades[targetUserId] = nil
			pushState(player)
			pushState(target)
			PlaySound:FireClient(player, "pet_collect.trade_success")
			PlaySound:FireClient(target, "pet_collect.trade_success")
		end
	else
		pendingTrades[player.UserId] = { target = targetUserId, petId = petId }
	end
end)

print(("[%s] server initialized"):format(Config.GameTitle))
