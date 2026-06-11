--!strict
-- Main client entry: builds UI and forwards user intents to the server.

local ReplicatedStorage = game:GetService("ReplicatedStorage")

local HUD = require(script.Parent.HUD)
local UpgradeUI = require(script.Parent.UpgradeUI)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestUpgrade = Remotes:WaitForChild("RequestUpgrade") :: RemoteEvent
local RequestPrestige = Remotes:WaitForChild("RequestPrestige") :: RemoteEvent
local StateChanged = Remotes:WaitForChild("StateChanged") :: RemoteEvent

HUD.Build(function()
	RequestPrestige:FireServer()
end)

UpgradeUI.Build(function(upgradeName: string)
	RequestUpgrade:FireServer(upgradeName)
end)

StateChanged.OnClientEvent:Connect(function(state)
	HUD.Update(state)
	UpgradeUI.Update(state)
end)
