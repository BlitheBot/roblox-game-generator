-- LoadingScreen — shown on join so players never see a blank baseplate.
-- Black screen with the game title, a tagline and a 2-second loading bar
-- that fills then fades out.
local TweenService = game:GetService("TweenService")
local Players = game:GetService("Players")

local GAME_TITLE = "{{GAME_TITLE}}"
local TAGLINE = "Hatch eggs, collect rare pets and trade with friends!"
local ACCENT = Color3.fromRGB(255, 150, 200)

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local gui = Instance.new("ScreenGui")
gui.Name = "LoadingScreen"
gui.IgnoreGuiInset = true
gui.DisplayOrder = 1000
gui.ResetOnSpawn = false
gui.Parent = playerGui

local bg = Instance.new("Frame")
bg.Size = UDim2.fromScale(1, 1)
bg.BackgroundColor3 = Color3.fromRGB(10, 10, 14)
bg.BorderSizePixel = 0
bg.Parent = gui

local title = Instance.new("TextLabel")
title.Size = UDim2.fromScale(0.8, 0.18)
title.Position = UDim2.fromScale(0.1, 0.30)
title.BackgroundTransparency = 1
title.Font = Enum.Font.GothamBlack
title.TextScaled = true
title.TextColor3 = Color3.fromRGB(255, 255, 255)
title.Text = GAME_TITLE
title.Parent = bg

local tagline = Instance.new("TextLabel")
tagline.Size = UDim2.fromScale(0.7, 0.07)
tagline.Position = UDim2.fromScale(0.15, 0.50)
tagline.BackgroundTransparency = 1
tagline.Font = Enum.Font.Gotham
tagline.TextScaled = true
tagline.TextColor3 = Color3.fromRGB(190, 190, 200)
tagline.Text = TAGLINE
tagline.Parent = bg

local barBg = Instance.new("Frame")
barBg.Size = UDim2.fromScale(0.5, 0.025)
barBg.Position = UDim2.fromScale(0.25, 0.64)
barBg.BackgroundColor3 = Color3.fromRGB(40, 40, 46)
barBg.BorderSizePixel = 0
barBg.Parent = bg
local barCorner = Instance.new("UICorner")
barCorner.CornerRadius = UDim.new(1, 0)
barCorner.Parent = barBg

local barFill = Instance.new("Frame")
barFill.Size = UDim2.fromScale(0, 1)
barFill.BackgroundColor3 = ACCENT
barFill.BorderSizePixel = 0
barFill.Parent = barBg
local fillCorner = Instance.new("UICorner")
fillCorner.CornerRadius = UDim.new(1, 0)
fillCorner.Parent = barFill

-- Fill the bar over 2 seconds
TweenService:Create(barFill, TweenInfo.new(2, Enum.EasingStyle.Quad), { Size = UDim2.fromScale(1, 1) }):Play()
task.wait(2.2)

-- Fade everything out and clean up
local info = TweenInfo.new(0.6)
TweenService:Create(bg, info, { BackgroundTransparency = 1 }):Play()
TweenService:Create(barBg, info, { BackgroundTransparency = 1 }):Play()
TweenService:Create(barFill, info, { BackgroundTransparency = 1 }):Play()
for _, lbl in { title, tagline } do
	TweenService:Create(lbl, info, { TextTransparency = 1 }):Play()
end
task.wait(0.7)
gui:Destroy()
