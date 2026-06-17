--!strict
-- SocialProofService (Improvement 3) — server-wide achievement announcements.
--
-- Broadcasts real player achievements to every client so the game feels alive
-- even at low CCU. All announcements are triggered by genuine player actions
-- (never faked). Other server code can require this module and call the on*
-- helpers; the companion SocialProof.server.luau wires the universal first-join
-- announcement and opt-in attribute-driven triggers with no extra wiring.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local AnnounceRemote = Remotes:WaitForChild("SocialProofAnnouncement") :: RemoteEvent

local SocialProofService = {}

local ANNOUNCEMENTS: { [string]: { string } } = {
	prestige = {
		"🏆 {player} just prestiged their empire! Incredible!",
		"⭐ {player} reached Prestige! What a grinder!",
		"🎉 {player} has ascended to Prestige! Respect!",
	},
	rare_drop = {
		"✨ {player} just pulled a {rarity} {item}! So lucky!",
		"🌟 WOW! {player} got a {rarity} {item}!",
		"🔥 {player} is on fire — just got a {rarity} {item}!",
	},
	milestone = {
		"📈 {player} just reached {milestone}! Impressive!",
		"💪 {player} hit {milestone}! Keep it up!",
	},
	trade = {
		"🤝 {player1} and {player2} just completed a legendary trade!",
		"💰 Big trade! {player1} and {player2} swapped some rare items!",
	},
	streak = {
		"🔥 {player} is on a {count} round survival streak! Can they keep it going?",
		"😤 Nobody can stop {player}! {count} rounds survived!",
	},
	first_join = {
		"👋 Welcome {player} to the server! Say hi!",
	},
	level_up = {
		"⬆️ {player} just leveled up! Getting stronger!",
	},
}

local COOLDOWN_SECONDS: { [string]: number } = {
	prestige = 0,
	rare_drop = 30,
	milestone = 60,
	trade = 0,
	streak = 120,
	first_join = 0,
	level_up = 300,
}

local RARITY_RANK: { [string]: number } = {
	Common = 1, Uncommon = 2, Rare = 3, Epic = 4, Legendary = 5, Mythic = 6,
}

local cooldowns: { [string]: number } = {}

local function canAnnounce(player: Player, eventType: string): boolean
	local key = tostring(player.UserId) .. "_" .. eventType
	local last = cooldowns[key] or 0
	local cd = COOLDOWN_SECONDS[eventType] or 60
	return (os.clock() - last) >= cd
end

local function recordAnnouncement(player: Player, eventType: string)
	cooldowns[tostring(player.UserId) .. "_" .. eventType] = os.clock()
end

local function pickRandom(t: { string }): string
	return t[math.random(1, #t)]
end

local function formatAnnouncement(template: string, vars: { [string]: any }): string
	local result = template
	for key, value in pairs(vars) do
		result = string.gsub(result, "{" .. key .. "}", tostring(value))
	end
	return result
end

function SocialProofService.announce(eventType: string, vars: { [string]: any }, targetPlayer: Player?)
	local templates = ANNOUNCEMENTS[eventType]
	if not templates then
		return
	end
	if targetPlayer and not canAnnounce(targetPlayer, eventType) then
		return
	end
	local message = formatAnnouncement(pickRandom(templates), vars)
	AnnounceRemote:FireAllClients(message, eventType)
	if targetPlayer then
		recordAnnouncement(targetPlayer, eventType)
	end
end

function SocialProofService.onPrestige(player: Player)
	SocialProofService.announce("prestige", { player = player.Name }, player)
end

function SocialProofService.onRareDrop(player: Player, rarity: string, itemName: string)
	if (RARITY_RANK[rarity] or 0) >= 3 then
		SocialProofService.announce("rare_drop", {
			player = player.Name, rarity = rarity, item = itemName,
		}, player)
	end
end

function SocialProofService.onMilestone(player: Player, milestoneName: string)
	SocialProofService.announce("milestone", {
		player = player.Name, milestone = milestoneName,
	}, player)
end

function SocialProofService.onTrade(player1: Player, player2: Player)
	SocialProofService.announce("trade", {
		player1 = player1.Name, player2 = player2.Name,
	}, nil)
end

function SocialProofService.onSurvivalStreak(player: Player, count: number)
	if count >= 3 then
		SocialProofService.announce("streak", {
			player = player.Name, count = count,
		}, player)
	end
end

function SocialProofService.onLevelUp(player: Player)
	SocialProofService.announce("level_up", { player = player.Name }, player)
end

function SocialProofService.onFirstJoin(player: Player)
	task.delay(3, function()
		if player.Parent then
			SocialProofService.announce("first_join", { player = player.Name }, nil)
		end
	end)
end

return SocialProofService
