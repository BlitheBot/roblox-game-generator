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

-- Mobile safe-area: on touch devices, nudge top-row UI of inset-respecting GUIs
-- clear of the notch/topbar (the shared HUD manages its own inset).
local Players = game:GetService("Players")
local GuiService = game:GetService("GuiService")
local UserInputService = game:GetService("UserInputService")
local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")
local function adjustForSafeArea(gui: Instance)
	if not gui:IsA("ScreenGui") or gui.IgnoreGuiInset or not UserInputService.TouchEnabled then
		return
	end
	local extra = math.min(GuiService:GetGuiInset().Y, 24)
	for _, child in gui:GetChildren() do
		if child:IsA("GuiObject") and child.Position.Y.Scale == 0 and child.Position.Y.Offset < 80 then
			child.Position = child.Position + UDim2.fromOffset(0, extra)
		end
	end
end
for _, gui in playerGui:GetChildren() do
	adjustForSafeArea(gui)
end
playerGui.ChildAdded:Connect(function(gui)
	task.defer(adjustForSafeArea, gui)
end)
