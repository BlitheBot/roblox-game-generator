--!strict
-- RetentionService: drop-in daily login reward + streak system.
-- Self-contained — owns its DataStore, creates its remotes at runtime,
-- and needs no template edits. Integration points (both optional):
--   * ServerStorage.GrantCurrency BindableEvent — fired (player, amount)
--     to award the daily reward in the game's real currency
--   * player attribute "StreakMultiplier" — income scripts may read it
--     (default 1) to apply the streak bonus to earnings

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local STORE_NAME = "RetentionData_v1"
local BASE_DAILY_REWARD = 100
-- LiveOps-tunable boost applied to milestone-streak rewards (concept.balance)
local RETENTION_REWARD_BOOST = {{RETENTION_REWARD_BOOST}}
local STREAK_REWARD_CAP = 30 -- reward keeps escalating up to day 30

-- Streak milestone multipliers (applied to both the daily reward and the
-- StreakMultiplier attribute income scripts read)
local function milestoneMultiplier(streak: number): number
	if streak >= 30 then
		return 3
	elseif streak >= 7 then
		return 2
	elseif streak >= 3 then
		return 1.5
	end
	return 1
end

local function nextMilestone(streak: number): number
	if streak < 3 then
		return 3
	elseif streak < 7 then
		return 7
	elseif streak < 30 then
		return 30
	end
	return streak
end

local store = nil
pcall(function()
	store = DataStoreService:GetDataStore(STORE_NAME)
end)

-- Runtime remotes — no default.project.json entry needed
local remotesFolder = ReplicatedStorage:FindFirstChild("RetentionRemotes") :: Folder?
if not remotesFolder then
	local folder = Instance.new("Folder")
	folder.Name = "RetentionRemotes"
	folder.Parent = ReplicatedStorage
	remotesFolder = folder
end
local stateRemote = (remotesFolder :: Folder):FindFirstChild("RetentionState") :: RemoteEvent?
if not stateRemote then
	local remote = Instance.new("RemoteEvent")
	remote.Name = "RetentionState"
	remote.Parent = remotesFolder
	stateRemote = remote
end

local function utcDay(): number
	return math.floor(os.time() / 86400)
end

local function loadRecord(player: Player): { LastClaimDay: number, Streak: number }
	local record = { LastClaimDay = 0, Streak = 0 }
	if store then
		local ok, saved = pcall(function()
			return (store :: DataStore):GetAsync(tostring(player.UserId))
		end)
		if ok and typeof(saved) == "table" then
			local savedTable = saved :: { [string]: any }
			if typeof(savedTable.LastClaimDay) == "number" then
				record.LastClaimDay = savedTable.LastClaimDay
			end
			if typeof(savedTable.Streak) == "number" then
				record.Streak = savedTable.Streak
			end
		end
	end
	return record
end

local function saveRecord(player: Player, record: { LastClaimDay: number, Streak: number })
	if store then
		pcall(function()
			(store :: DataStore):SetAsync(tostring(player.UserId), record)
		end)
	end
end

local function grantCurrency(player: Player, amount: number)
	-- Template integration point — when the template wired a GrantCurrency
	-- BindableEvent, the reward lands in the game's real currency
	local grantEvent = ServerStorage:FindFirstChild("GrantCurrency")
	if grantEvent and grantEvent:IsA("BindableEvent") then
		grantEvent:Fire(player, amount)
	end
end

local function onPlayerAdded(player: Player)
	local record = loadRecord(player)
	local today = utcDay()
	local claimedNow = false
	local reward = 0

	if record.LastClaimDay ~= today then
		if record.LastClaimDay == today - 1 then
			record.Streak += 1 -- consecutive day: streak continues
		else
			record.Streak = 1 -- gap: streak resets
		end
		record.LastClaimDay = today
		local multiplier = milestoneMultiplier(record.Streak)
		reward = math.floor(BASE_DAILY_REWARD * math.min(record.Streak, STREAK_REWARD_CAP) * multiplier
			* (if record.Streak >= 3 then RETENTION_REWARD_BOOST else 1))
		claimedNow = true
		saveRecord(player, record)
		grantCurrency(player, reward)
	end

	local multiplier = milestoneMultiplier(record.Streak)
	player:SetAttribute("LoginStreak", record.Streak)
	player:SetAttribute("StreakMultiplier", multiplier)
	player:SetAttribute("DailyReward", reward);

	(stateRemote :: RemoteEvent):FireClient(player, {
		Streak = record.Streak,
		Reward = reward,
		Multiplier = multiplier,
		ClaimedNow = claimedNow,
		NextMilestone = nextMilestone(record.Streak),
	})
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in Players:GetPlayers() do
	task.spawn(onPlayerAdded, player)
end
