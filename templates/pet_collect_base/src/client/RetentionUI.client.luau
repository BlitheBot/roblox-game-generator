--!strict
-- RetentionUI: drop-in client UI for the daily login reward system.
-- Shows the daily reward toast on join and a "come back tomorrow"
-- prompt once the session passes 5 minutes (the closest client-side
-- approximation of "on session end" — Roblox gives no pre-quit hook).

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local COME_BACK_AFTER_SECONDS = 300 -- 5 minutes played
local TOAST_SECONDS = 6

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "RetentionUI"
screenGui.ResetOnSpawn = false
screenGui.Parent = playerGui

local lastState: { [string]: any }? = nil

local function makePanel(height: number): Frame
	local frame = Instance.new("Frame")
	frame.AnchorPoint = Vector2.new(0.5, 0)
	frame.Position = UDim2.new(0.5, 0, 0.08, 0)
	frame.Size = UDim2.new(0, 340, 0, height)
	frame.BackgroundColor3 = Color3.fromRGB(30, 32, 40)
	frame.BackgroundTransparency = 0.05
	frame.BorderSizePixel = 0
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 12)
	corner.Parent = frame
	frame.Parent = screenGui
	return frame
end

local function makeLabel(parent: Frame, text: string, yOffset: number, size: number, bold: boolean): TextLabel
	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.Position = UDim2.new(0, 12, 0, yOffset)
	label.Size = UDim2.new(1, -24, 0, size + 6)
	label.Font = if bold then Enum.Font.GothamBold else Enum.Font.Gotham
	label.TextSize = size
	label.TextColor3 = Color3.fromRGB(255, 255, 255)
	label.TextWrapped = true
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.Text = text
	label.Parent = parent
	return label
end

local function dismissAfter(frame: Frame, seconds: number)
	task.delay(seconds, function()
		local tween = TweenService:Create(
			frame,
			TweenInfo.new(0.4, Enum.EasingStyle.Quad, Enum.EasingDirection.In),
			{ Position = UDim2.new(0.5, 0, -0.2, 0) }
		)
		tween:Play()
		tween.Completed:Wait()
		frame:Destroy()
	end)
end

local function showDailyToast(state: { [string]: any })
	local panel = makePanel(96)
	local title = if state.ClaimedNow
		then ("Daily reward — Day %d streak!"):format(state.Streak)
		else ("Day %d streak — already claimed today"):format(state.Streak)
	makeLabel(panel, title, 8, 18, true)
	if state.ClaimedNow and state.Reward > 0 then
		makeLabel(panel, ("+%d bonus currency (x%.1f streak bonus)"):format(state.Reward, state.Multiplier), 36, 15, false)
	else
		makeLabel(panel, ("Streak bonus active: x%.1f earnings"):format(state.Multiplier), 36, 15, false)
	end
	if state.NextMilestone > state.Streak then
		makeLabel(panel, ("Reach Day %d for a bigger bonus!"):format(state.NextMilestone), 62, 13, false)
	else
		makeLabel(panel, "Max streak bonus unlocked!", 62, 13, false)
	end
	dismissAfter(panel, TOAST_SECONDS)
end

local function showComeBackPrompt()
	local streak = 1
	if lastState and typeof(lastState.Streak) == "number" then
		streak = lastState.Streak
	end
	local panel = makePanel(110)
	makeLabel(panel, "Come back tomorrow!", 8, 18, true)
	makeLabel(
		panel,
		("Log in tomorrow to keep your streak going — Day %d is waiting with a bigger reward."):format(streak + 1),
		36,
		15,
		false
	)

	local button = Instance.new("TextButton")
	button.AnchorPoint = Vector2.new(0.5, 1)
	button.Position = UDim2.new(0.5, 0, 1, -8)
	button.Size = UDim2.new(0, 120, 0, 26)
	button.BackgroundColor3 = Color3.fromRGB(70, 140, 255)
	button.Font = Enum.Font.GothamBold
	button.TextSize = 14
	button.TextColor3 = Color3.fromRGB(255, 255, 255)
	button.Text = "Got it!"
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 8)
	corner.Parent = button
	button.Parent = panel
	button.Activated:Connect(function()
		panel:Destroy()
	end)
	dismissAfter(panel, 20)
end

-- Daily reward toast on join
task.spawn(function()
	local remotesFolder = ReplicatedStorage:WaitForChild("RetentionRemotes", 15)
	if not remotesFolder then
		return
	end
	local stateRemote = remotesFolder:WaitForChild("RetentionState", 10)
	if not stateRemote or not stateRemote:IsA("RemoteEvent") then
		return
	end
	stateRemote.OnClientEvent:Connect(function(state: { [string]: any })
		lastState = state
		showDailyToast(state)
	end)
end)

-- "Come back tomorrow" prompt after 5+ minutes played (shown once)
task.delay(COME_BACK_AFTER_SECONDS, showComeBackPrompt)
