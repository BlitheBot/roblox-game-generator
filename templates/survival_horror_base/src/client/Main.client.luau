--!strict
-- Horror client: phase banner, map vote buttons, currency display.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestVote = Remotes:WaitForChild("RequestVote") :: RemoteEvent
local RoundState = Remotes:WaitForChild("RoundState") :: RemoteEvent

local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "HorrorUI"
screenGui.ResetOnSpawn = false

local banner = Instance.new("TextLabel")
banner.Size = UDim2.fromOffset(420, 48)
banner.Position = UDim2.new(0.5, -210, 0, 12)
banner.BackgroundColor3 = Color3.fromRGB(15, 15, 20)
banner.BackgroundTransparency = 0.2
banner.TextColor3 = Color3.fromRGB(220, 60, 60)
banner.TextScaled = true
banner.Font = Enum.Font.Creepster
banner.Text = "Waiting..."
banner.Parent = screenGui

-- Currency is shown by the shared HUDClient (ReplicatedStorage-driven).

local voteFrame = Instance.new("Frame")
voteFrame.Size = UDim2.fromOffset(220, 52 * #Config.Maps + 8)
voteFrame.Position = UDim2.new(0.5, -110, 0.5, -((52 * #Config.Maps + 8) // 2))
voteFrame.BackgroundColor3 = Color3.fromRGB(15, 15, 20)
voteFrame.BackgroundTransparency = 0.2
voteFrame.Visible = false
voteFrame.Parent = screenGui

for i, mapName in Config.Maps do
	local button = Instance.new("TextButton")
	button.Size = UDim2.new(1, -16, 0, 44)
	button.Position = UDim2.new(0, 8, 0, 8 + (i - 1) * 52)
	button.BackgroundColor3 = Color3.fromRGB(60, 60, 80)
	button.TextColor3 = Color3.new(1, 1, 1)
	button.TextScaled = true
	button.Font = Enum.Font.FredokaOne
	button.Text = mapName
	button.Parent = voteFrame
	button.Activated:Connect(function()
		RequestVote:FireServer(mapName)
		voteFrame.Visible = false
	end)
end

screenGui.Parent = playerGui

RoundState.OnClientEvent:Connect(function(state)
	voteFrame.Visible = state.Phase == "voting"

	if state.Phase == "lobby" then
		banner.Text = "Next round soon..."
	elseif state.Phase == "voting" then
		banner.Text = "Vote for a map!"
	elseif state.Phase == "round" then
		banner.Text = Config.MonsterName .. " is hunting..."
	elseif state.Phase == "results" then
		local survivors = state.Survivors or {}
		banner.Text = #survivors > 0 and ("Survivors: " .. table.concat(survivors, ", "))
			or "No one survived..."
	end
end)
