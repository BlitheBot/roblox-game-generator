--!strict
-- Round manager: lobby → map vote → round → results loop.
-- Votes are validated server-side; currency rewards are server-authoritative.

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local Config = require(ReplicatedStorage.Shared.Config)
local MonsterAI = require(script.Parent.MonsterAI)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestVote = Remotes:WaitForChild("RequestVote") :: RemoteEvent
local RoundState = Remotes:WaitForChild("RoundState") :: RemoteEvent
local PlaySound = Remotes:WaitForChild("PlaySound") :: RemoteEvent
local OnboardingStepComplete = Remotes:WaitForChild("OnboardingStepComplete") :: RemoteEvent
local ServerError = Remotes:WaitForChild("ServerError") :: RemoteEvent

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

local store = nil
pcall(function()
	store = DataStoreService:GetDataStore("PlayerData_v1")
end)

local currency: { [number]: number } = {}
local votes: { [number]: string } = {}
local alive: { [number]: boolean } = {}
local phase = "lobby"

local function load(player: Player)
	currency[player.UserId] = 0
	if store then
		local ok, saved = pcall(function()
			return store:GetAsync(tostring(player.UserId))
		end)
		if ok and typeof(saved) == "number" then
			currency[player.UserId] = saved
		end
	end
end

local function save(player: Player)
	local amount = currency[player.UserId]
	if not (amount and store) then
		return
	end
	-- Retry up to 3 times with backoff before telling the player it failed.
	for attempt = 1, 3 do
		local ok = pcall(function()
			store:SetAsync(tostring(player.UserId), amount)
		end)
		if ok then
			return
		end
		task.wait(attempt)
	end
	if player.Parent then
		ServerError:FireClient(player, "datastore_failed")
	end
end

local function broadcast(payload: { [string]: any })
	payload.Phase = phase
	for _, player in Players:GetPlayers() do
		payload.Currency = currency[player.UserId] or 0
		RoundState:FireClient(player, payload)
	end
end

local function tallyVotes(): string
	local counts: { [string]: number } = {}
	for _, mapName in votes do
		counts[mapName] = (counts[mapName] or 0) + 1
	end
	local winner = Config.Maps[1]
	local best = -1
	for mapName, count in counts do
		if count > best then
			best = count
			winner = mapName
		end
	end
	return winner
end

local function eliminate(player: Player)
	if not alive[player.UserId] then
		return
	end
	alive[player.UserId] = false
	local reward = math.floor(Config.SurvivalReward * Config.EliminationPenaltyKeepFraction)
	currency[player.UserId] = (currency[player.UserId] or 0) + reward
	local character = player.Character
	local humanoid = character and character:FindFirstChildOfClass("Humanoid")
	if humanoid then
		humanoid.Health = 0
	end
	PlaySound:FireClient(player, "survival_horror.player_hurt")
	broadcast({ Eliminated = player.Name })
end

local function anySurvivors(): boolean
	for _, isAlive in alive do
		if isAlive then
			return true
		end
	end
	return false
end

local function runRound()
	-- Vote phase
	phase = "voting"
	votes = {}
	broadcast({ Maps = Config.Maps, TimeLeft = Config.VoteSeconds })
	task.wait(Config.VoteSeconds)
	local chosenMap = tallyVotes()

	-- Round phase
	phase = "round"
	alive = {}
	for _, player in Players:GetPlayers() do
		if player.Character then
			alive[player.UserId] = true
		end
	end
	broadcast({ Map = chosenMap, TimeLeft = Config.RoundSeconds, Monster = Config.MonsterName })
	for _, roundPlayer in Players:GetPlayers() do
		OnboardingStepComplete:FireClient(roundPlayer, "RoundJoined")
	end

	MonsterAI.Start(Vector3.new(0, 10, -60), alive, eliminate)

	-- A one-shot heartbeat as the hunt begins sets the tension.
	for _, roundPlayer in Players:GetPlayers() do
		if alive[roundPlayer.UserId] then
			PlaySound:FireClient(roundPlayer, "survival_horror.heartbeat")
		end
	end

	local elapsed = 0
	while elapsed < Config.RoundSeconds and anySurvivors() do
		task.wait(1)
		elapsed += 1
	end
	MonsterAI.Stop()

	-- Results: survivors get full reward
	phase = "results"
	local survivors = {}
	for userId, isAlive in alive do
		if isAlive then
			local reward = Config.SurvivalReward
			local player = Players:GetPlayerByUserId(userId)
			if player then
				-- Bonuses from drop-in systems (absent → 1): retention
				-- streaks and monetization multipliers
				local streakMult = player:GetAttribute("StreakMultiplier")
				if typeof(streakMult) == "number" then
					reward = math.floor(reward * streakMult)
				end
				local monetizationMult = player:GetAttribute("MonetizationMultiplier")
				if typeof(monetizationMult) == "number" then
					reward = math.floor(reward * monetizationMult)
				end
			end
			reward = math.floor(reward * eventMult("coin_multiplier"))
				currency[userId] = (currency[userId] or 0) + reward
			if player then
				table.insert(survivors, player.Name)
					PlaySound:FireClient(player, "success")
				save(player)
			end
		end
	end
	broadcast({ Survivors = survivors })
	for _, resultPlayer in Players:GetPlayers() do
		OnboardingStepComplete:FireClient(resultPlayer, "RoundCompleted")
	end
	task.wait(5)
end

-- Currency grant hook for drop-in systems (e.g. RetentionService daily
-- rewards). Optional contract: systems fire (player, amount) server-side.
local grantCurrency = Instance.new("BindableEvent")
grantCurrency.Name = "GrantCurrency"
grantCurrency.Parent = ServerStorage
grantCurrency.Event:Connect(function(player: Player, amount: number)
	if typeof(amount) == "number" and amount > 0 then
		currency[player.UserId] = (currency[player.UserId] or 0) + amount
	end
end)

-- Companion spend hook (e.g. MonetizationService shop purchases)
local trySpendCurrency = Instance.new("BindableFunction")
trySpendCurrency.Name = "TrySpendCurrency"
trySpendCurrency.Parent = ServerStorage
trySpendCurrency.OnInvoke = function(player: Player, amount: number): boolean
	local balance = currency[player.UserId]
	if not balance or typeof(amount) ~= "number" or amount <= 0 or balance < amount then
		return false
	end
	currency[player.UserId] = balance - amount
	return true
end

Players.PlayerAdded:Connect(load)
Players.PlayerRemoving:Connect(function(player)
	save(player)
	currency[player.UserId] = nil
	votes[player.UserId] = nil
	alive[player.UserId] = nil
end)

game:BindToClose(function()
	for _, player in Players:GetPlayers() do
		save(player)
	end
end)

RequestVote.OnServerEvent:Connect(function(player: Player, mapName: unknown)
	if phase ~= "voting" or typeof(mapName) ~= "string" then
		return
	end
	if table.find(Config.Maps, mapName) then
		votes[player.UserId] = mapName :: string
	end
end)

-- Main loop
task.spawn(function()
	while true do
		phase = "lobby"
		broadcast({ TimeLeft = Config.LobbySeconds })
		task.wait(Config.LobbySeconds)
		if #Players:GetPlayers() >= Config.MinPlayers then
			runRound()
		end
	end
end)

print(("[%s] server initialized"):format(Config.GameTitle))
