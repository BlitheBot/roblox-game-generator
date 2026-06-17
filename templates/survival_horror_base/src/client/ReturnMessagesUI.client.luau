--!strict
-- ReturnMessagesUI (Improvement 4) — shows a centered "welcome back" modal on
-- join when the server sends return messages (offline earnings, bonuses, daily
-- reward ready). A Collect button (and a 12s auto-dismiss) closes it.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local ReturnMessages = Remotes:WaitForChild("ReturnMessages") :: RemoteEvent

local gui = Instance.new("ScreenGui")
gui.Name = "ReturnMessagesGui"
gui.ResetOnSpawn = false
gui.DisplayOrder = 8
gui.Enabled = false
gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")

local shade = Instance.new("Frame")
shade.Size = UDim2.new(1, 0, 1, 0)
shade.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
shade.BackgroundTransparency = 0.5
shade.BorderSizePixel = 0
shade.Parent = gui

local panel = Instance.new("Frame")
panel.Size = UDim2.new(0, 360, 0, 260)
panel.Position = UDim2.new(0.5, -180, 0.5, -130)
panel.BackgroundColor3 = Color3.fromRGB(25, 25, 40)
panel.BorderSizePixel = 0
panel.Parent = shade

local panelCorner = Instance.new("UICorner")
panelCorner.CornerRadius = UDim.new(0, 12)
panelCorner.Parent = panel

local titleLabel = Instance.new("TextLabel")
titleLabel.Size = UDim2.new(1, -20, 0, 40)
titleLabel.Position = UDim2.new(0, 10, 0, 10)
titleLabel.BackgroundTransparency = 1
titleLabel.Font = Enum.Font.GothamBold
titleLabel.TextSize = 20
titleLabel.TextColor3 = Color3.fromRGB(255, 235, 150)
titleLabel.Text = "Welcome back! 🎉"
titleLabel.Parent = panel

local bodyLabel = Instance.new("TextLabel")
bodyLabel.Size = UDim2.new(1, -30, 1, -110)
bodyLabel.Position = UDim2.new(0, 15, 0, 55)
bodyLabel.BackgroundTransparency = 1
bodyLabel.Font = Enum.Font.Gotham
bodyLabel.TextSize = 15
bodyLabel.TextWrapped = true
bodyLabel.TextYAlignment = Enum.TextYAlignment.Top
bodyLabel.TextColor3 = Color3.fromRGB(230, 230, 240)
bodyLabel.Text = ""
bodyLabel.Parent = panel

local collect = Instance.new("TextButton")
collect.Size = UDim2.new(0, 200, 0, 44)
collect.Position = UDim2.new(0.5, -100, 1, -56)
collect.BackgroundColor3 = Color3.fromRGB(60, 200, 120)
collect.Font = Enum.Font.GothamBold
collect.TextSize = 18
collect.TextColor3 = Color3.fromRGB(255, 255, 255)
collect.Text = "Collect!"
collect.Parent = panel

local collectCorner = Instance.new("UICorner")
collectCorner.CornerRadius = UDim.new(0, 8)
collectCorner.Parent = collect

local function hide()
	gui.Enabled = false
end

collect.MouseButton1Click:Connect(hide)

ReturnMessages.OnClientEvent:Connect(function(messages)
	if typeof(messages) ~= "table" or #messages == 0 then
		return
	end
	titleLabel.Text = messages[1].title or "Welcome back! 🎉"
	local lines = {}
	for _, m in ipairs(messages) do
		table.insert(lines, m.body or "")
	end
	bodyLabel.Text = table.concat(lines, "\n\n")
	gui.Enabled = true
	panel.Position = UDim2.new(0.5, -180, 0.5, -100)
	TweenService:Create(
		panel,
		TweenInfo.new(0.3, Enum.EasingStyle.Back, Enum.EasingDirection.Out),
		{ Position = UDim2.new(0.5, -180, 0.5, -130) }
	):Play()
	task.delay(12, hide)
end)
