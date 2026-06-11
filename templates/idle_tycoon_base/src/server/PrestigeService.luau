--!strict
-- PrestigeService: "{{PRESTIGE_NAME}}" resets currency and upgrades for a
-- permanent income multiplier. Validates requirement server-side.

local Config = require(game.ReplicatedStorage.Shared.Config)
local DataService = require(script.Parent.DataService)

local PrestigeService = {}

function PrestigeService.CanPrestige(player: Player): boolean
	local data = DataService.Get(player)
	if not data then
		return false
	end
	return data.Currency >= Config.PrestigeRequirement
end

function PrestigeService.TryPrestige(player: Player): boolean
	if not PrestigeService.CanPrestige(player) then
		return false
	end
	local data = DataService.Get(player)
	data.Currency = Config.StartingCurrency
	data.Upgrades = {}
	data.PrestigeLevel += 1
	DataService.Save(player)
	return true
end

return PrestigeService
