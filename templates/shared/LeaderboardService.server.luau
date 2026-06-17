--[[
	LeaderboardService — universal global leaderboard for all templates.

	Tracks the most relevant stat per genre (idle: total earned, pet: rarest pet
	value, survival: rounds won, incremental: rebirth count) in an
	OrderedDataStore, and broadcasts the top 10 every 60s via LeaderboardUpdate.

	Servers submit scores through the ServerStorage.SubmitScore BindableEvent
	(player, value) — a `.server` Script can't be require()d. Writes are throttled
	per player and use UpdateAsync(max) so a score can never regress, which also
	lets session-based metrics (e.g. rounds won) accumulate safely. The current
	stored score is readable via the ServerStorage.GetLeaderboardScore
	BindableFunction.
--]]

local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")
local Players = game:GetService("Players")

local LeaderboardStore = nil
pcall(function()
	LeaderboardStore = DataStoreService:GetOrderedDataStore("{{GAME_TITLE}}_Leaderboard_v1")
end)

local WRITE_THROTTLE = 30 -- seconds between writes per player (OrderedDataStore limits)
local lastWrite: { [number]: number } = {}

local function updateScore(userId: number, value: number)
	if not LeaderboardStore or typeof(value) ~= "number" or value < 0 then
		return
	end
	local now = os.clock()
	if lastWrite[userId] and now - lastWrite[userId] < WRITE_THROTTLE then
		return
	end
	lastWrite[userId] = now
	pcall(function()
		LeaderboardStore:UpdateAsync(tostring(userId), function(old)
			old = tonumber(old) or 0
			return math.max(old, math.floor(value))
		end)
	end)
end

local function getScore(userId: number): number
	if not LeaderboardStore then
		return 0
	end
	local ok, value = pcall(function()
		return LeaderboardStore:GetAsync(tostring(userId))
	end)
	return (ok and tonumber(value)) or 0
end

local function getTop10()
	if not LeaderboardStore then
		return {}
	end
	local ok, pages = pcall(function()
		return LeaderboardStore:GetSortedAsync(false, 10)
	end)
	if not ok then
		return {}
	end
	local results = {}
	for rank, entry in ipairs(pages:GetCurrentPage()) do
		local userId = tonumber(entry.key)
		local name = "Player"
		local online = userId and Players:GetPlayerByUserId(userId)
		if online then
			name = online.Name
		elseif userId then
			local nameOk, fetched = pcall(function()
				return Players:GetNameFromUserIdAsync(userId)
			end)
			name = (nameOk and fetched) or ("Player" .. tostring(entry.key))
		end
		table.insert(results, { rank = rank, name = name, value = entry.value, userId = entry.key })
	end
	return results
end

-- Contracts for the game's server scripts.
local submit = Instance.new("BindableEvent")
submit.Name = "SubmitScore"
submit.Parent = ServerStorage
submit.Event:Connect(function(player: Player, value: number)
	if typeof(player) == "Instance" and player:IsA("Player") then
		updateScore(player.UserId, value)
	end
end)

local query = Instance.new("BindableFunction")
query.Name = "GetLeaderboardScore"
query.Parent = ServerStorage
query.OnInvoke = function(player: Player): number
	if typeof(player) == "Instance" and player:IsA("Player") then
		return getScore(player.UserId)
	end
	return 0
end

Players.PlayerRemoving:Connect(function(player)
	lastWrite[player.UserId] = nil
end)

-- Broadcast the top 10 to all clients every 60 seconds.
task.spawn(function()
	while true do
		task.wait(60)
		local top10 = getTop10()
		local remotes = ReplicatedStorage:FindFirstChild("Remotes")
		local lbUpdate = remotes and remotes:FindFirstChild("LeaderboardUpdate")
		if lbUpdate and lbUpdate:IsA("RemoteEvent") then
			lbUpdate:FireAllClients(top10)
		end
	end
end)
