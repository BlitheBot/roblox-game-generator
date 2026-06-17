--!strict
-- DynamicDifficulty (Improvement 2, survival_horror variant) — flow tuning.
--
-- Base behaviour: a per-player "EarnRateMultiplier" attribute within ±30% of
-- base, a +10% new-player boost for the first 5 minutes, and a real catch-up
-- grant (via ServerStorage.GrantCurrency) for stuck new players.
--
-- Horror-specific: a per-player "MonsterDifficultyMultiplier" kept within ±20%.
-- New players (first 3 rounds) face slightly slower/blinder monsters; players
-- on a 5+ round survival streak face a slight challenge bump. MonsterAI opts in
-- by reading the attribute; the game increments "RoundsPlayed" / "SurvivalStreak".
-- All state is per-session and resets on rejoin.

local Players = game:GetService("Players")
local ServerStorage = game:GetService("ServerStorage")

local MIN_MULTIPLIER = 0.7
local MAX_MULTIPLIER = 1.3
local MONSTER_MIN = 0.8
local MONSTER_MAX = 1.2
local ADJUSTMENT_STEP = 0.05
local CHECK_INTERVAL = 30
local NEW_PLAYER_SECONDS = 300
local NEW_PLAYER_ROUNDS = 3
local CHALLENGE_STREAK = 5

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
	player:SetAttribute("MonsterDifficultyMultiplier", MONSTER_MIN) -- ease new players in
end

local function setMultiplier(player: Player, state: State, value: number)
	state.earnRateMultiplier = math.clamp(value, MIN_MULTIPLIER, MAX_MULTIPLIER)
	player:SetAttribute("EarnRateMultiplier", state.earnRateMultiplier)
end

local function updateMonsterDifficulty(player: Player)
	local rounds = player:GetAttribute("RoundsPlayed")
	local streak = player:GetAttribute("SurvivalStreak")
	local mult = 1.0
	if typeof(rounds) == "number" and rounds < NEW_PLAYER_ROUNDS then
		mult = MONSTER_MIN
	elseif typeof(streak) == "number" and streak >= CHALLENGE_STREAK then
		mult = MONSTER_MAX
	end
	player:SetAttribute("MonsterDifficultyMultiplier", math.clamp(mult, MONSTER_MIN, MONSTER_MAX))
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

	updateMonsterDifficulty(player)
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
