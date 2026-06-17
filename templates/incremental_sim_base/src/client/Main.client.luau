--!strict
-- Incremental sim client: resource/currency HUD, sell + upgrade + rebirth
-- buttons. Sends intents only; server owns all state.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestAction = Remotes:WaitForChild("RequestAction") :: RemoteEvent
local StateChanged = Remotes:WaitForChild("StateChanged") :: RemoteEvent

local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "SimUI"
screenGui.ResetOnSpawn = false

local function makeLabel(yOffset: number): TextLabel
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromOffset(260, 36)
	label.Position = UDim2.new(0.5, -130, 0, yOffset)
	label.BackgroundColor3 = Color3.fromRGB(30, 30, 40)
	label.BackgroundTransparency = 0.25
	label.TextColor3 = Color3.fromRGB(255, 225, 120)
	label.TextScaled = true
	label.Font = Enum.Font.FredokaOne
	label.Parent = screenGui
	return label
end

local function makeButton(text: string, yOffset: number, color: Color3): TextButton
	local button = Instance.new("TextButton")
	button.Size = UDim2.fromOffset(200, 44)
	button.Position = UDim2.new(0, 12, 0, yOffset)
	button.BackgroundColor3 = color
	button.TextColor3 = Color3.new(1, 1, 1)
	button.TextScaled = true
	button.Font = Enum.Font.FredokaOne
	button.Text = text
	button.Parent = screenGui
	return button
end

local resourceLabel = makeLabel(12)
-- Currency is shown by the shared HUDClient (ReplicatedStorage-driven).

local sellButton = makeButton("Sell " .. Config.ResourceName, 120, Color3.fromRGB(60, 130, 80))
sellButton.Activated:Connect(function()
	RequestAction:FireServer("sell")
end)

local upgradeButtons: { [string]: TextButton } = {}
for i, def in Config.Upgrades do
	local button = makeButton(def.Name, 176 + (i - 1) * 52, Color3.fromRGB(70, 100, 160))
	button.Activated:Connect(function()
		RequestAction:FireServer("upgrade", def.Name)
	end)
	upgradeButtons[def.Name] = button
end

local rebirthButton = makeButton(Config.RebirthName, 176 + #Config.Upgrades * 52, Color3.fromRGB(170, 60, 200))
rebirthButton.Visible = false
rebirthButton.Activated:Connect(function()
	RequestAction:FireServer("rebirth")
end)

screenGui.Parent = playerGui

StateChanged.OnClientEvent:Connect(function(state)
	resourceLabel.Text = math.floor(state.Resource) .. " " .. Config.ResourceName
	rebirthButton.Visible = state.CanRebirth == true
	for _, def in Config.Upgrades do
		local button = upgradeButtons[def.Name]
		local upgrade = state.Upgrades[def.Name]
		local level = upgrade and upgrade.Level or 0
		local cost = math.floor(def.BaseCost * def.CostMultiplier ^ level)
		button.Text = ("%s [%d] — %d"):format(def.Name, level, cost)
	end
end)
