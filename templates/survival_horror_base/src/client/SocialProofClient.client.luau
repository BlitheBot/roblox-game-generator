--!strict
-- SocialProofClient (Improvement 3) — displays server announcements as toast
-- notifications that slide in from the top center, hold ~4s, then fade out.
-- Max 3 visible at once; event types are color-coded.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local AnnounceRemote = Remotes:WaitForChild("SocialProofAnnouncement") :: RemoteEvent

local EVENT_COLORS: { [string]: Color3 } = {
	prestige = Color3.fromRGB(255, 215, 0),
	rare_drop = Color3.fromRGB(160, 60, 220),
	milestone = Color3.fromRGB(80, 120, 255),
	trade = Color3.fromRGB(60, 200, 120),
	streak = Color3.fromRGB(255, 100, 0),
	first_join = Color3.fromRGB(200, 200, 220),
	level_up = Color3.fromRGB(100, 220, 255),
}

local MAX_VISIBLE = 3
local DISPLAY_DURATION = 4
local SLIDE_DURATION = 0.3

local activeAnnouncements: { Frame } = {}

local gui = Instance.new("ScreenGui")
gui.Name = "SocialProofGui"
gui.ResetOnSpawn = false
gui.DisplayOrder = 5
gui.Parent = Players.LocalPlayer:WaitForChild("PlayerGui")

local container = Instance.new("Frame")
container.Size = UDim2.new(0, 400, 0, 200)
container.Position = UDim2.new(0.5, -200, 0, 10)
container.BackgroundTransparency = 1
container.Parent = gui

local layout = Instance.new("UIListLayout")
layout.Padding = UDim.new(0, 5)
layout.HorizontalAlignment = Enum.HorizontalAlignment.Center
layout.Parent = container

local function createFrame(message: string, eventType: string): Frame
	local color = EVENT_COLORS[eventType] or Color3.fromRGB(200, 200, 220)

	local frame = Instance.new("Frame")
	frame.Size = UDim2.new(1, 0, 0, 40)
	frame.BackgroundColor3 = Color3.fromRGB(15, 15, 25)
	frame.BackgroundTransparency = 0.1
	frame.BorderSizePixel = 0

	local accent = Instance.new("Frame")
	accent.Size = UDim2.new(0, 4, 1, 0)
	accent.BackgroundColor3 = color
	accent.BorderSizePixel = 0
	accent.Parent = frame

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 6)
	corner.Parent = frame

	local label = Instance.new("TextLabel")
	label.Size = UDim2.new(1, -15, 1, 0)
	label.Position = UDim2.new(0, 10, 0, 0)
	label.BackgroundTransparency = 1
	label.Text = message
	label.TextColor3 = Color3.fromRGB(230, 230, 240)
	label.Font = Enum.Font.Gotham
	label.TextSize = 13
	label.TextXAlignment = Enum.TextXAlignment.Left
	label.TextTruncate = Enum.TextTruncate.AtEnd
	label.Parent = frame

	frame.Position = UDim2.new(0, 0, 0, -50)
	frame.Parent = container
	TweenService:Create(
		frame,
		TweenInfo.new(SLIDE_DURATION, Enum.EasingStyle.Quart, Enum.EasingDirection.Out),
		{ Position = UDim2.new(0, 0, 0, 0) }
	):Play()
	return frame
end

local function showAnnouncement(message: string, eventType: string)
	if #activeAnnouncements >= MAX_VISIBLE then
		local oldest = table.remove(activeAnnouncements, 1)
		if oldest then
			oldest:Destroy()
		end
	end

	local frame = createFrame(message, eventType)
	table.insert(activeAnnouncements, frame)

	task.delay(DISPLAY_DURATION, function()
		if frame and frame.Parent then
			TweenService:Create(
				frame, TweenInfo.new(SLIDE_DURATION), { BackgroundTransparency = 1 }
			):Play()
			task.delay(SLIDE_DURATION, function()
				if frame and frame.Parent then
					frame:Destroy()
				end
				local idx = table.find(activeAnnouncements, frame)
				if idx then
					table.remove(activeAnnouncements, idx)
				end
			end)
		end
	end)
end

AnnounceRemote.OnClientEvent:Connect(showAnnouncement)
