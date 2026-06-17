--!strict
-- Main server entry: wires services, player lifecycle, and RemoteEvents.
-- Every RemoteEvent handler validates its arguments before acting (never
-- trust the client for currency or stats).

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local DataService = require(script.Parent.DataService)
local PlotService = require(script.Parent.PlotService)
local ProductionService = require(script.Parent.ProductionService)
local PrestigeService = require(script.Parent.PrestigeService)
local ShopService = require(script.Parent.ShopService)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestPurchase = Remotes:WaitForChild("RequestPurchase") :: RemoteEvent
local RequestUpgrade = Remotes:WaitForChild("RequestUpgrade") :: RemoteEvent
local RequestPrestige = Remotes:WaitForChild("RequestPrestige") :: RemoteEvent
local StateChanged = Remotes:WaitForChild("StateChanged") :: RemoteEvent
local PlaySound = Remotes:WaitForChild("PlaySound") :: RemoteEvent
local OnboardingStepComplete = Remotes:WaitForChild("OnboardingStepComplete") :: RemoteEvent
local ServerError = Remotes:WaitForChild("ServerError") :: RemoteEvent

DataService.Init()
PlotService.Init()
ProductionService.Init()
ShopService.Init()

local function pushState(player: Player)
	local data = DataService.Get(player)
	if not data then
		return
	end
	StateChanged:FireClient(player, {
		Currency = data.Currency,
		PrestigeLevel = data.PrestigeLevel,
		Upgrades = data.Upgrades,
		CanPrestige = PrestigeService.CanPrestige(player),
	})
end

-- Currency grant hook for drop-in systems (e.g. RetentionService daily
-- rewards). Optional contract: systems fire (player, amount) server-side.
local grantCurrency = Instance.new("BindableEvent")
grantCurrency.Name = "GrantCurrency"
grantCurrency.Parent = ServerStorage
grantCurrency.Event:Connect(function(player: Player, amount: number)
	if typeof(amount) == "number" and amount > 0 then
		DataService.AddCurrency(player, amount)
		pushState(player)
	end
end)

-- Companion spend hook (e.g. MonetizationService shop purchases)
local trySpendCurrency = Instance.new("BindableFunction")
trySpendCurrency.Name = "TrySpendCurrency"
trySpendCurrency.Parent = ServerStorage
trySpendCurrency.OnInvoke = function(player: Player, amount: number): boolean
	if typeof(amount) ~= "number" or amount <= 0 then
		return false
	end
	local ok = DataService.TrySpend(player, amount)
	if ok then
		pushState(player)
	end
	return ok
end

local function onPlayerAdded(player: Player)
	DataService.Load(player)
	PlotService.Assign(player)
	OnboardingStepComplete:FireClient(player, "PlotClaimed")
	ShopService.RefreshOwnedPasses(player)
	ProductionService.StartLoop(player)

	-- Periodic state replication (currency ticks up server-side). A throttled
	-- coin sound (max once / 2s) gives the passive income an audible heartbeat.
	task.spawn(function()
		local lastCoin = 0
		local lastCurrency = -1
		while player.Parent do
			pushState(player)
			local data = DataService.Get(player)
			local now = os.clock()
			if data and data.Currency > lastCurrency and now - lastCoin >= 2 then
				lastCoin = now
				lastCurrency = data.Currency
				PlaySound:FireClient(player, "coin_earn")
			end
			task.wait(1)
		end
	end)
end

Players.PlayerAdded:Connect(onPlayerAdded)
Players.PlayerRemoving:Connect(function(player)
	DataService.Release(player)
end)

-- RemoteEvent handlers — all arguments validated server-side
RequestUpgrade.OnServerEvent:Connect(function(player: Player, upgradeName: unknown)
	if ShopService.TryBuyUpgrade(player, upgradeName) then
		pushState(player)
		PlaySound:FireClient(player, "idle_tycoon.upgrade_buy")
		OnboardingStepComplete:FireClient(player, "UpgradePurchased")
	else
		ServerError:FireClient(player, "purchase_failed")
	end
end)

RequestPurchase.OnServerEvent:Connect(function(player: Player, kind: unknown, identifier: unknown)
	if kind == "shop_item" then
		if ShopService.TryBuyShopItem(player, identifier) then
			pushState(player)
			PlaySound:FireClient(player, "purchase_success")
		else
			ServerError:FireClient(player, "insufficient_funds")
		end
	elseif kind == "game_pass" then
		ShopService.PromptGamePass(player, identifier)
	end
end)

RequestPrestige.OnServerEvent:Connect(function(player: Player)
	if PrestigeService.TryPrestige(player) then
		pushState(player)
		PlaySound:FireClient(player, "prestige")
	end
end)

print(("[%s] server initialized"):format(Config.GameTitle))
