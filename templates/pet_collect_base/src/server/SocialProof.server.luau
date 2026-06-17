--!strict
-- SocialProof initializer (Improvement 3) — wires achievement announcements
-- without touching the bespoke economy services. The universal first-join
-- welcome always fires; richer triggers are opt-in via player attributes, so a
-- game that sets PrestigeLevel / SurvivalStreak / RareDrop attributes (or whose
-- services require SocialProofService directly) gets the full set for free.

local Players = game:GetService("Players")

local SocialProofService = require(script.Parent.SocialProofService)

local function wirePlayer(player: Player)
	SocialProofService.onFirstJoin(player)

	-- Opt-in attribute-driven triggers (no effect until a game sets them).
	player:GetAttributeChangedSignal("PrestigeLevel"):Connect(function()
		local lvl = player:GetAttribute("PrestigeLevel")
		if typeof(lvl) == "number" and lvl > 0 then
			SocialProofService.onPrestige(player)
		end
	end)

	player:GetAttributeChangedSignal("SurvivalStreak"):Connect(function()
		local streak = player:GetAttribute("SurvivalStreak")
		if typeof(streak) == "number" then
			SocialProofService.onSurvivalStreak(player, streak)
		end
	end)

	player:GetAttributeChangedSignal("LastRareDrop"):Connect(function()
		local drop = player:GetAttribute("LastRareDrop")
		if typeof(drop) == "string" and drop ~= "" then
			-- Format "Rarity|ItemName"
			local rarity, item = string.match(drop, "^(.-)|(.+)$")
			if rarity and item then
				SocialProofService.onRareDrop(player, rarity, item)
			end
		end
	end)
end

Players.PlayerAdded:Connect(wirePlayer)
for _, player in ipairs(Players:GetPlayers()) do
	wirePlayer(player)
end
