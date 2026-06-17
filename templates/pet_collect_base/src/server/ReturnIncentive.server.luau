--!strict
-- ReturnIncentive initializer (Improvement 4) — wires the leave/return hooks
-- independently of the bespoke DataService so it works in every template.

local Players = game:GetService("Players")

local ReturnIncentiveService = require(script.Parent.ReturnIncentiveService)

Players.PlayerAdded:Connect(function(player)
	-- Small delay so any per-player data the game loads is in place first.
	task.delay(2, function()
		if player.Parent then
			ReturnIncentiveService.onPlayerReturning(player)
		end
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	ReturnIncentiveService.onPlayerLeaving(player)
end)
