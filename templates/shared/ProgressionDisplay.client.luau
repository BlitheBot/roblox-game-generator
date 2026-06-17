--[[
	ProgressionDisplay — always-visible progress toward the next milestone.

	A fill bar that advances toward the next meaningful goal (per genre, decided
	server-side and sent via UpdateProgress: current, max, label). Lives in the
	HUD, animates smoothly, pulses near completion, and flashes green at 100%.
--]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local Players = game:GetService("Players")

local DS = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local hud = playerGui:WaitForChild("HUD", 10)
if not hud then
	return
end

local progressContainer = DS.createPanel({
	size = DS.getResponsiveSize(UDim2.new(0, 280, 0, 50)),
	position = UDim2.new(0.5, 0, 1, -72),
	color = DS.Colors.BgMedium,
	transparency = 0.05,
	shadow = true,
	parent = hud,
})
progressContainer.AnchorPoint = Vector2.new(0.5, 1)

local progressLabel = DS.createLabel({
	text = "Progress",
	size = UDim2.new(1, -16, 0, 18),
	position = UDim2.new(0, 8, 0, 4),
	style = "small",
	parent = progressContainer,
})

local progressBarBg = Instance.new("Frame")
progressBarBg.Size = UDim2.new(1, -16, 0, 14)
progressBarBg.Position = UDim2.new(0, 8, 0, 26)
progressBarBg.BackgroundColor3 = DS.Colors.BgDark
progressBarBg.BorderSizePixel = 0
progressBarBg.Parent = progressContainer
local barBgCorner = Instance.new("UICorner")
barBgCorner.CornerRadius = UDim.new(1, 0)
barBgCorner.Parent = progressBarBg

local progressBarFill = Instance.new("Frame")
progressBarFill.Size = UDim2.new(0, 0, 1, 0)
progressBarFill.BackgroundColor3 = DS.Colors.Primary
progressBarFill.BorderSizePixel = 0
progressBarFill.Parent = progressBarBg
local barFillCorner = Instance.new("UICorner")
barFillCorner.CornerRadius = UDim.new(1, 0)
barFillCorner.Parent = progressBarFill

local progressPercent = Instance.new("TextLabel")
progressPercent.Size = UDim2.new(1, 0, 1, 0)
progressPercent.BackgroundTransparency = 1
progressPercent.Text = "0%"
progressPercent.TextColor3 = DS.Colors.TextPrimary
progressPercent.Font = DS.Fonts.Button
progressPercent.TextSize = 11
progressPercent.Parent = progressBarBg

local currentProgress = 0

local function updateProgress(current, max, label)
	if label then
		progressLabel.Text = label
	end
	local newProgress = (max and max > 0) and math.clamp(current / max, 0, 1) or 0

	TweenService:Create(progressBarFill, TweenInfo.new(0.5, Enum.EasingStyle.Quad), {
		Size = UDim2.new(newProgress, 0, 1, 0),
	}):Play()
	progressPercent.Text = math.floor(newProgress * 100) .. "%"

	if newProgress >= 1 and currentProgress < 1 then
		TweenService:Create(progressContainer, TweenInfo.new(0.2), {
			BackgroundColor3 = DS.Colors.Success,
		}):Play()
		task.delay(0.5, function()
			TweenService:Create(progressContainer, TweenInfo.new(0.3), {
				BackgroundColor3 = DS.Colors.BgMedium,
			}):Play()
		end)
	end

	currentProgress = newProgress
end

local Remotes = ReplicatedStorage:WaitForChild("Remotes", 10)
if Remotes then
	local progressUpdate = Remotes:FindFirstChild("UpdateProgress")
	if progressUpdate and progressUpdate:IsA("RemoteEvent") then
		progressUpdate.OnClientEvent:Connect(function(current, max, label)
			updateProgress(current, max, label)
		end)
	end
end

return { updateProgress = updateProgress }
