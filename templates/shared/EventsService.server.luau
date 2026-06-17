--[[
	EventsService — keeps games feeling alive with regular, short events.

	Runs server-authoritative events a few times per day:
	  * Happy Hour — 2x coins for 30 min
	  * Lucky Streak — +20% rare chance for 20 min (collection games)
	  * Speed Round — half cooldowns for 15 min

	Other server scripts read the active multiplier through the
	ServerStorage.GetEventMultiplier BindableFunction (the repo's contract
	pattern — a `.server` Script can't be require()d):

		local fn = game:GetService("ServerStorage"):FindFirstChild("GetEventMultiplier")
		local mult = fn and fn:Invoke("coin_multiplier") or 1

	Announced via SocialProofAnnouncement and shown as a HUD banner via UpdateHUD.
--]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

local MECHANIC = "{{MECHANIC_TAG}}"

local EVENT_TYPES = {
	happy_hour = {
		name = "🎉 Happy Hour",
		duration_minutes = 30,
		effect = { coin_multiplier = 2.0 },
		announcement = "🎉 HAPPY HOUR! 2x coins for the next 30 minutes!",
	},
	lucky_streak = {
		name = "🍀 Lucky Streak",
		duration_minutes = 20,
		effect = { rare_chance_boost = 1.2 },
		announcement = "🍀 LUCKY STREAK ACTIVE! +20% rare chance for 20 minutes!",
	},
	speed_round = {
		name = "⚡ Speed Round",
		duration_minutes = 15,
		effect = { cooldown_multiplier = 0.5 },
		announcement = "⚡ SPEED ROUND! Half cooldowns for 15 minutes!",
	},
}

local GENRE_EVENTS = {
	idle_tycoon = { "happy_hour", "speed_round" },
	pet_collect = { "happy_hour", "lucky_streak" },
	survival_horror = { "happy_hour", "speed_round" },
	incremental_sim = { "happy_hour", "speed_round" },
}

local activeEvent = nil
local eventEndTime = 0

local Remotes = ReplicatedStorage:WaitForChild("Remotes", 10)

local function remainingSeconds(): number
	return math.max(0, math.floor(eventEndTime - os.clock()))
end

local function pickRandomEvent(): string
	local available = GENRE_EVENTS[MECHANIC] or { "happy_hour" }
	return available[math.random(1, #available)]
end

local function isActive(): boolean
	return activeEvent ~= nil and os.clock() <= eventEndTime
end

local function getActiveMultiplier(effectType: string): number
	if not isActive() then
		return 1.0
	end
	return activeEvent.effect[effectType] or 1.0
end

local function pushBanner(target: Player?, name: string?, endsIn: number)
	if not Remotes then
		return
	end
	local updateHUD = Remotes:FindFirstChild("UpdateHUD")
	if not (updateHUD and updateHUD:IsA("RemoteEvent")) then
		return
	end
	local payload = { activeEvent = name or false, eventEndsIn = endsIn }
	if target then
		updateHUD:FireClient(target, payload)
	else
		updateHUD:FireAllClients(payload)
	end
end

local function startEvent(eventKey: string)
	local def = EVENT_TYPES[eventKey]
	if not def then
		return
	end
	activeEvent = def
	eventEndTime = os.clock() + def.duration_minutes * 60

	if Remotes then
		local announce = Remotes:FindFirstChild("SocialProofAnnouncement")
		if announce and announce:IsA("RemoteEvent") then
			announce:FireAllClients(def.announcement, "event")
		end
	end
	pushBanner(nil, def.name, def.duration_minutes * 60)
end

local function endEvent()
	if not activeEvent then
		return
	end
	if Remotes then
		local announce = Remotes:FindFirstChild("SocialProofAnnouncement")
		if announce and announce:IsA("RemoteEvent") then
			announce:FireAllClients("Event ended: " .. activeEvent.name, "info")
		end
	end
	activeEvent = nil
	eventEndTime = 0
	pushBanner(nil, false, 0)
end

-- Contract: server scripts query the live multiplier for an effect type.
local getMultiplier = Instance.new("BindableFunction")
getMultiplier.Name = "GetEventMultiplier"
getMultiplier.Parent = ServerStorage
getMultiplier.OnInvoke = function(effectType: string): number
	if isActive() then
		return getActiveMultiplier(effectType)
	end
	if activeEvent then -- expired since last check
		endEvent()
	end
	return 1.0
end

-- New joiners mid-event still see the banner.
Players.PlayerAdded:Connect(function(player)
	if isActive() then
		pushBanner(player, activeEvent.name, remainingSeconds())
	end
end)

-- Schedule random events a few times per day (every 4–10 hours).
task.spawn(function()
	while true do
		task.wait(math.random(4, 10) * 3600)
		if not isActive() then
			startEvent(pickRandomEvent())
		end
	end
end)

-- Expire events promptly.
task.spawn(function()
	while true do
		task.wait(30)
		if activeEvent and os.clock() > eventEndTime then
			endEvent()
		end
	end
end)
