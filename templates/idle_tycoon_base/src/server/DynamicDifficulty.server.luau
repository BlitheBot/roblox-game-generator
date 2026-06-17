--!strict
-- DynamicDifficulty (Improvement 2) — keeps players in the flow state.
--
-- Every 30s it assesses each player's progression and makes small, invisible,
-- per-player adjustments (never beyond ±30% of base) published as the
-- "EarnRateMultiplier" attribute, which the economy can opt into reading.
-- New players are protected with a +10% boost for their first 5 minutes, and a
-- genuinely stuck new player gets a tiny catch-up grant via the universal
-- ServerStorage.GrantCurrency contract so the help is real even before the
-- economy opts in. All state is per-session and resets on rejoin (never saved).

local Players = game:GetService("Players")
local ServerStorage = game:GetService("ServerStorage")

local MIN_MULTIPLIER = 0.7
local MAX_MULTIPLIER = 1.3
local ADJUSTMENT_STEP = 0.05
local CHECK_INTERVAL = 30
local NEW_PLAYER_SECONDS = 300

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

	-- Currency-driven adjustment (opt-in: the game publishes a "Currency"
	-- attribute). Without it, only new-player protection applies.
	local currency = player:GetAttribute("Currency")
	if typeof(currency) == "number" then
		local earnedPerMin = (currency - state.currencyAtLastCheck) / (elapsed / 60)
		state.currencyAtLastCheck = currency

		local nextCost = player:GetAttribute("NextUpgradeCost")
		if typeof(nextCost) == "number" and nextCost > 0 then
			local progressRatio = earnedPerMin / nextCost
			if progressRatio < 0.05 then
				-- Stuck — nudge earn rate up and, for new players, grant a tiny
				-- invisible catch-up so progress is actually felt.
				setMultiplier(player, state, state.earnRateMultiplier + ADJUSTMENT_STEP)
				if sessionMinutes < NEW_PLAYER_SECONDS / 60 then
					grant(player, math.min(50, nextCost * 0.05))
				end
			elseif progressRatio > 0.5 and state.earnRateMultiplier > 1.0 then
				-- Rushing — normalize back toward base (never below 1.0 here).
				setMultiplier(player, state, math.max(1.0, state.earnRateMultiplier - ADJUSTMENT_STEP))
			end
		end
	end

	-- New-player protection: first 5 minutes always get at least +10%.
	if sessionMinutes < (NEW_PLAYER_SECONDS / 60) and state.earnRateMultiplier < 1.1 then
		setMultiplier(player, state, 1.1)
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
