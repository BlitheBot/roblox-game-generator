--!strict
-- ShopService: handles upgrades (soft currency), shop items, and Robux
-- game passes via MarketplaceService. All purchase validation is server-side;
-- the client only ever sends a request.

local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")

local Config = require(game.ReplicatedStorage.Shared.Config)
local DataService = require(script.Parent.DataService)

local ShopService = {}

local function findUpgradeDef(name: string)
	for _, def in Config.Upgrades do
		if def.Name == name then
			return def
		end
	end
	return nil
end

function ShopService.GetUpgradeCost(player: Player, upgradeName: string): number?
	local def = findUpgradeDef(upgradeName)
	local data = DataService.Get(player)
	if not def or not data then
		return nil
	end
	local upgrade = data.Upgrades[upgradeName]
	local level = upgrade and upgrade.Level or 0
	if level >= def.MaxLevel then
		return nil
	end
	return math.floor(def.BaseCost * def.CostMultiplier ^ level)
end

function ShopService.TryBuyUpgrade(player: Player, upgradeName: unknown): boolean
	-- Validate everything the client sent
	if typeof(upgradeName) ~= "string" then
		return false
	end
	local cost = ShopService.GetUpgradeCost(player, upgradeName :: string)
	if not cost then
		return false
	end
	if not DataService.TrySpend(player, cost) then
		return false
	end
	local data = DataService.Get(player)
	local upgrade = data.Upgrades[upgradeName]
	if upgrade then
		upgrade.Level += 1
	else
		data.Upgrades[upgradeName :: string] = { Level = 1 }
	end
	return true
end

function ShopService.TryBuyShopItem(player: Player, itemName: unknown): boolean
	if typeof(itemName) ~= "string" then
		return false
	end
	for _, item in Config.ShopItems do
		if item.name == itemName then
			if DataService.TrySpend(player, item.price) then
				local data = DataService.Get(player)
				data.Upgrades["item:" .. item.name] = { Level = 1 }
				return true
			end
			return false
		end
	end
	return false
end

function ShopService.PromptGamePass(player: Player, passId: unknown)
	if typeof(passId) ~= "number" then
		return
	end
	-- Only prompt for passes this game actually defines
	for _, passDef in Config.GamePasses do
		if passDef.id == passId then
			MarketplaceService:PromptGamePassPurchase(player, passId)
			return
		end
	end
end

function ShopService.RefreshOwnedPasses(player: Player)
	local data = DataService.Get(player)
	if not data then
		return
	end
	for _, passDef in Config.GamePasses do
		local ok, owns = pcall(function()
			return MarketplaceService:UserOwnsGamePassAsync(player.UserId, passDef.id)
		end)
		if ok and owns then
			data.OwnedPasses[passDef.id] = true
		end
	end
end

function ShopService.Init()
	MarketplaceService.PromptGamePassPurchaseFinished:Connect(
		function(player: Player, passId: number, purchased: boolean)
			if purchased then
				local data = DataService.Get(player)
				if data then
					data.OwnedPasses[passId] = true
					DataService.Save(player)
				end
			end
		end
	)
end

return ShopService
