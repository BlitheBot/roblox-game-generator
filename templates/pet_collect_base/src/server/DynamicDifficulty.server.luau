--!strict
-- DynamicDifficulty (Improvement 2, pet_collect variant) — flow-state tuning.
--
-- Base behaviour: a per-player "EarnRateMultiplier" attribute kept within ±30%
-- of base, a +10% new-player boost for the first 5 minutes, and a real
-- catch-up grant (via ServerStorage.GrantCurrency) for stuck new players.
--
-- Pet-specific: new players get a small luck nudge ("LuckBonus" = +5% toward
-- Uncommon) for their first 5 egg opens so the first session feels rewarding.
-- The egg-opening code opts in by reading "LuckBonus" and incrementing the
-- "EggOpens" attribute. All state is per-session and resets on rejoin.

local Players = game:GetService("Players")
local ServerStorage = game:GetService("ServerStorage")

local MIN_MULTIPLIER = 0.7
local MAX_MULTIPLIER = 1.3
local ADJUSTMENT_STEP = 0.05
local CHECK_INTERVAL = 30
local NEW_PLAYER_SECONDS = 300
local NEW_PLAYER_LUCK_OPENS = 5
local NEW_PLAYER_LUCK_BONUS = 0.05

type State = {
	sessionStart: number,
	lastCheck: number,
	currencyAtLastCheck: number,
	earnRateMultiplier: number,
}

local playerState: { [number]: State } = {}

local function grant(player: Player, amount: number)
	if amount <= 0 then
		return
	end
	local hook = ServerStorage:FindFirstChild("GrantCurrency")
	if hook and hook:IsA("BindableEvent") then
		hook:Fire(player, math.floor(amount))
	end
end

local function initPlayer(player: Player)
	playerState[player.UserId] = {
		sessionStart = os.clock(),
		lastCheck = os.clock(),
		currencyAtLastCheck = 0,
		earnRateMultiplier = 1.0,
	}
	player:SetAttribute("EarnRateMultiplier", 1.0)
	player:SetAttribute("LuckBonus", NEW_PLAYER_LUCK_BONUS)
end

local function setMultiplier(player: Player, state: State, value: number)
	state.earnRateMultiplier = math.clamp(value, MIN_MULTIPLIER, MAX_MULTIPLIER)
	player:SetAttribute("EarnRateMultiplier", state.earnRateMultiplier)
end

local function assess(player: Player)
	local state = playerState[player.UserId]
	if not state then
		return
	end
	local now = os.clock()
	local elapsed = now - state.lastCheck
	if elapsed <= 0 then
		return
	end
	local sessionMinutes = (now - state.sessionStart) / 60

	local currency = player:GetAttribute("Currency")
	if typeof(currency) == "number" then
		local earnedPerMin = (currency - state.currencyAtLastCheck) / (elapsed / 60)
		state.currencyAtLastCheck = currency
		local nextCost = player:GetAttribute("NextUpgradeCost")
		if typeof(nextCost) == "number" and nextCost > 0 then
			local progressRatio = earnedPerMin / nextCost
			if progressRatio < 0.05 then
				setMultiplier(player, state, state.earnRateMultiplier + ADJUSTMENT_STEP)
				if sessionMinutes < NEW_PLAYER_SECONDS / 60 then
					grant(player, math.min(50, nextCost * 0.05))
				end
			elseif progressRatio > 0.5 and state.earnRateMultiplier > 1.0 then
				setMultiplier(player, state, math.max(1.0, state.earnRateMultiplier - ADJUSTMENT_STEP))
			end
		end
	end

	if sessionMinutes < (NEW_PLAYER_SECONDS / 60) and state.earnRateMultiplier < 1.1 then
		setMultiplier(player, state, 1.1)
	end

	-- Pet luck nudge: clear the new-player bonus once they've opened enough eggs.
	local opens = player:GetAttribute("EggOpens")
	if typeof(opens) == "number" and opens >= NEW_PLAYER_LUCK_OPENS then
		if player:GetAttribute("LuckBonus") ~= 0 then
			player:SetAttribute("LuckBonus", 0)
		end
	end

	state.lastCheck = now
end

Players.PlayerAdded:Connect(function(player)
	initPlayer(player)
	task.spawn(function()
		while player.Parent ~= nil do
			task.wait(CHECK_INTERVAL)
			assess(player)
		end
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	playerState[player.UserId] = nil
end)
