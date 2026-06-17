--[[
	LoadingScreen — polished first impression for every generated game.

	Instantly paints a dark, branded screen on join (no baseplate flash), fades
	in the title + tagline, fills a genre-coloured loading bar, then invites a
	tap to play and fades out. Colours come from the DesignSystem genre palette
	so the loading screen matches the rest of the game.
--]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")

local DS = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local ACCENT = DS.Colors.Primary

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local loadingGui = Instance.new("ScreenGui")
loadingGui.Name = "LoadingScreen"
loadingGui.ResetOnSpawn = false
loadingGui.DisplayOrder = 100
loadingGui.IgnoreGuiInset = true
loadingGui.Parent = playerGui

local bg = Instance.new("Frame")
bg.Size = UDim2.new(1, 0, 1, 0)
bg.BackgroundColor3 = Color3.fromRGB(8, 10, 18)
bg.BorderSizePixel = 0
bg.Parent = loadingGui

-- Subtle dot grid for texture
local patternContainer = Instance.new("Frame")
patternContainer.Size = UDim2.new(1, 0, 1, 0)
patternContainer.BackgroundTransparency = 1
patternContainer.Parent = bg

for row = 1, 8 do
	for col = 1, 12 do
		local dot = Instance.new("Frame")
		dot.Size = UDim2.new(0, 3, 0, 3)
		dot.Position = UDim2.new((col - 1) / 12, 0, (row - 1) / 8, 0)
		dot.BackgroundColor3 = Color3.fromRGB(40, 45, 65)
		dot.BackgroundTransparency = 0.5
		dot.BorderSizePixel = 0
		dot.Parent = patternContainer
		local dotCorner = Instance.new("UICorner")
		dotCorner.CornerRadius = UDim.new(1, 0)
		dotCorner.Parent = dot
	end
end

local logoContainer = Instance.new("Frame")
logoContainer.Size = UDim2.new(0, 400, 0, 200)
logoContainer.Position = UDim2.new(0.5, -200, 0.35, -100)
logoContainer.BackgroundTransparency = 1
logoContainer.Parent = bg

local titleLabel = Instance.new("TextLabel")
titleLabel.Size = UDim2.new(1, 0, 0, 80)
titleLabel.Position = UDim2.new(0, 0, 0, 20)
titleLabel.BackgroundTransparency = 1
titleLabel.Text = "{{GAME_TITLE}}"
titleLabel.TextColor3 = DS.Colors.TextPrimary
titleLabel.Font = DS.Fonts.Title
titleLabel.TextSize = 48
titleLabel.TextTransparency = 1
titleLabel.Parent = logoContainer

local taglineLabel = Instance.new("TextLabel")
taglineLabel.Size = UDim2.new(1, 0, 0, 30)
taglineLabel.Position = UDim2.new(0, 0, 0, 105)
taglineLabel.BackgroundTransparency = 1
taglineLabel.Text = "{{TAGLINE}}"
taglineLabel.TextColor3 = DS.Colors.TextSecondary
taglineLabel.Font = DS.Fonts.Body
taglineLabel.TextSize = 18
taglineLabel.TextTransparency = 1
taglineLabel.Parent = logoContainer

local barContainer = Instance.new("Frame")
barContainer.Size = UDim2.new(0, 300, 0, 6)
barContainer.Position = UDim2.new(0.5, -150, 0.72, 0)
barContainer.BackgroundColor3 = Color3.fromRGB(30, 35, 50)
barContainer.BorderSizePixel = 0
barContainer.Parent = bg
local barContainerCorner = Instance.new("UICorner")
barContainerCorner.CornerRadius = UDim.new(1, 0)
barContainerCorner.Parent = barContainer

local barFill = Instance.new("Frame")
barFill.Size = UDim2.new(0, 0, 1, 0)
barFill.BackgroundColor3 = ACCENT
barFill.BorderSizePixel = 0
barFill.Parent = barContainer
local barFillCorner = Instance.new("UICorner")
barFillCorner.CornerRadius = UDim.new(1, 0)
barFillCorner.Parent = barFill

local loadingText = Instance.new("TextLabel")
loadingText.Size = UDim2.new(0, 300, 0, 24)
loadingText.Position = UDim2.new(0.5, -150, 0.72, 14)
loadingText.BackgroundTransparency = 1
loadingText.Text = "Loading..."
loadingText.TextColor3 = DS.Colors.TextMuted
loadingText.Font = DS.Fonts.Body
loadingText.TextSize = 14
loadingText.Parent = bg

local tapToPlay = Instance.new("TextLabel")
tapToPlay.Size = UDim2.new(0, 300, 0, 30)
tapToPlay.Position = UDim2.new(0.5, -150, 0.82, 0)
tapToPlay.BackgroundTransparency = 1
tapToPlay.Text = "TAP TO PLAY"
tapToPlay.TextColor3 = ACCENT
tapToPlay.Font = DS.Fonts.Button
tapToPlay.TextSize = 16
tapToPlay.TextTransparency = 1
tapToPlay.Parent = bg

local function playLoadingSequence()
	task.wait(0.1)

	TweenService:Create(titleLabel, TweenInfo.new(0.6, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {
		TextTransparency = 0,
	}):Play()

	task.wait(0.3)
	TweenService:Create(taglineLabel, TweenInfo.new(0.4), { TextTransparency = 0 }):Play()
	task.wait(0.4)

	local loadingMessages = {
		"Setting up the world...",
		"Loading assets...",
		"Preparing your experience...",
		"Almost ready...",
	}
	for i, msg in ipairs(loadingMessages) do
		loadingText.Text = msg
		TweenService:Create(barFill, TweenInfo.new(0.35), { Size = UDim2.new(i / 4, 0, 1, 0) }):Play()
		task.wait(0.35)
	end
	loadingText.Text = "Ready!"
	task.wait(0.2)

	TweenService:Create(tapToPlay, TweenInfo.new(0.3), { TextTransparency = 0 }):Play()

	local pulsing = true
	task.spawn(function()
		while pulsing do
			TweenService:Create(tapToPlay, TweenInfo.new(0.8, Enum.EasingStyle.Sine), { TextTransparency = 0.5 }):Play()
			task.wait(0.8)
			if not pulsing then
				break
			end
			TweenService:Create(tapToPlay, TweenInfo.new(0.8, Enum.EasingStyle.Sine), { TextTransparency = 0 }):Play()
			task.wait(0.8)
		end
	end)

	local dismissed = false
	local function dismiss()
		if dismissed then
			return
		end
		dismissed = true
		pulsing = false
		TweenService:Create(bg, TweenInfo.new(0.5), { BackgroundTransparency = 1 }):Play()
		TweenService:Create(titleLabel, TweenInfo.new(0.3), { TextTransparency = 1 }):Play()
		TweenService:Create(taglineLabel, TweenInfo.new(0.3), { TextTransparency = 1 }):Play()
		TweenService:Create(tapToPlay, TweenInfo.new(0.3), { TextTransparency = 1 }):Play()
		TweenService:Create(barContainer, TweenInfo.new(0.3), { BackgroundTransparency = 1 }):Play()
		TweenService:Create(loadingText, TweenInfo.new(0.3), { TextTransparency = 1 }):Play()
		task.delay(0.5, function()
			loadingGui:Destroy()
		end)
	end

	local clickDetector = Instance.new("TextButton")
	clickDetector.Size = UDim2.new(1, 0, 1, 0)
	clickDetector.BackgroundTransparency = 1
	clickDetector.Text = ""
	clickDetector.ZIndex = 10
	clickDetector.Parent = loadingGui
	clickDetector.MouseButton1Click:Connect(dismiss)

	task.delay(3, dismiss)
end

playLoadingSequence()
