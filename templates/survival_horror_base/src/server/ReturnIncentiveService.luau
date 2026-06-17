--!strict
-- ReturnIncentiveService (Improvement 4) — gives players a concrete reason to
-- come back. On leave it records when the player left and their earn rate; on
-- return it grants capped offline earnings + a welcome-back bonus (away > 2h)
-- via the universal ServerStorage.GrantCurrency contract, and sends a return
-- message to the client.
--
-- Earn rate is read from the player attribute "IncomePerSecond" when the game
-- publishes it, otherwise estimated from Config so every template still grants
-- something. Offline earnings are capped at 8 hours.

local DataStoreService = game:GetService("DataStoreService")
local ServerStorage = game:GetService("ServerStorage")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local ReturnMessages = Remotes:WaitForChild("ReturnMessages") :: RemoteEvent

local ReturnIncentiveService = {}

local MAX_OFFLINE_SECONDS = 8 * 3600
local MIN_AWAY_SECONDS = 300       -- only show a return message if away > 5 min
local WELCOME_BACK_SECONDS = 7200  -- welcome-back bonus if away > 2 hours

local store = DataStoreService:GetDataStore("ReturnData_" .. tostring(Config.GameTitle) .. "_v1")

local function estimatedRate(player: Player): number
	local attr = player:GetAttribute("IncomePerSecond")
	if typeof(attr) == "number" and attr > 0 then
		return attr
	end
	-- Fall back to a Config-derived estimate (guards for templates without
	-- these fields so the call never errors).
	local base = (typeof(Config.BaseDropValue) == "number") and Config.BaseDropValue or 1
	local interval = (typeof(Config.DropIntervalSeconds) == "number") and Config.DropIntervalSeconds or 1
	if interval <= 0 then
		interval = 1
	end
	return math.max(0.1, base / interval)
end

local function grant(player: Player, amount: number)
	if amount <= 0 then
		return
	end
	local hook = ServerStorage:FindFirstChild("GrantCurrency")
	if hook and hook:IsA("BindableEvent") then
		hook:Fire(player, amount)
	end
end

function ReturnIncentiveService.onPlayerLeaving(player: Player)
	local data = {
		leftAt = os.time(),
		incomePerSecond = estimatedRate(player),
	}
	pcall(function()
		store:SetAsync(tostring(player.UserId), data)
	end)
end

function ReturnIncentiveService.onPlayerReturning(player: Player)
	local data
	local ok = pcall(function()
		data = store:GetAsync(tostring(player.UserId))
	end)
	if not ok or not data then
		return
	end

	local awaySeconds = os.time() - (data.leftAt or os.time())
	if awaySeconds < MIN_AWAY_SECONDS then
		return
	end

	local rate = (typeof(data.incomePerSecond) == "number") and data.incomePerSecond or estimatedRate(player)
	local offlineEarnings = math.floor(math.min(rate * awaySeconds, rate * MAX_OFFLINE_SECONDS))

	local awayHours = math.floor(awaySeconds / 3600)
	local awayMinutes = math.floor(awaySeconds / 60)
	local awayText = if awayHours >= 1
		then awayHours .. " hour" .. (if awayHours > 1 then "s" else "")
		else awayMinutes .. " minute" .. (if awayMinutes > 1 then "s" else "")

	local messages = {}
	if offlineEarnings > 0 then
		grant(player, offlineEarnings)
		table.insert(messages, {
			title = "Welcome back! 🎉",
			body = "You were away for " .. awayText .. " and earned "
				.. tostring(offlineEarnings) .. " " .. tostring(Config.CurrencyName) .. "!",
			type = "offline_earnings",
			value = offlineEarnings,
		})
	end

	if awaySeconds > WELCOME_BACK_SECONDS then
		local bonus = math.floor(offlineEarnings * 0.1)
		if bonus > 0 then
			grant(player, bonus)
			table.insert(messages, {
				title = "Welcome Back Bonus! ⭐",
				body = "Thanks for returning! Here's a bonus " .. tostring(bonus)
					.. " " .. tostring(Config.CurrencyName) .. "!",
				type = "welcome_back_bonus",
				value = bonus,
			})
		end
	end

	pcall(function()
		store:RemoveAsync(tostring(player.UserId))
	end)

	if #messages > 0 then
		ReturnMessages:FireClient(player, messages)
	end
end

return ReturnIncentiveService
