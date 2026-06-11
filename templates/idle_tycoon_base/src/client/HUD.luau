--!strict
-- HUD: currency counter + prestige button. Pure rendering; all state comes
-- from the server via StateChanged.

local Players = game:GetService("Players")

local Config = require(game.ReplicatedStorage.Shared.Config)

local HUD = {}

local screenGui: ScreenGui? = nil
local currencyLabel: TextLabel? = nil
local prestigeButton: TextButton? = nil

function HUD.Build(onPrestige: () -> ())
	local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

	screenGui = Instance.new("ScreenGui")
	screenGui.Name = "HUD"
	screenGui.ResetOnSpawn = false

	local frame = Instance.new("Frame")
	frame.Size = UDim2.fromOffset(260, 60)
	frame.Position = UDim2.new(0.5, -130, 0, 12)
	frame.BackgroundColor3 = Color3.fromRGB(30, 30, 40)
	frame.BackgroundTransparency = 0.25
	frame.Parent = screenGui

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 10)
	corner.Parent = frame

	currencyLabel = Instance.new("TextLabel")
	currencyLabel.Size = UDim2.fromScale(1, 1)
	currencyLabel.BackgroundTransparency = 1
	currencyLabel.TextColor3 = Color3.fromRGB(255, 225, 120)
	currencyLabel.TextScaled = true
	currencyLabel.Font = Enum.Font.FredokaOne
	currencyLabel.Text = "0 " .. Config.CurrencyName
	currencyLabel.Parent = frame

	prestigeButton = Instance.new("TextButton")
	prestigeButton.Size = UDim2.fromOffset(180, 44)
	prestigeButton.Position = UDim2.new(1, -192, 1, -56)
	prestigeButton.BackgroundColor3 = Color3.fromRGB(170, 60, 200)
	prestigeButton.TextColor3 = Color3.new(1, 1, 1)
	prestigeButton.TextScaled = true
	prestigeButton.Font = Enum.Font.FredokaOne
	prestigeButton.Text = Config.PrestigeName
	prestigeButton.Visible = false
	prestigeButton.Parent = screenGui

	local btnCorner = Instance.new("UICorner")
	btnCorner.CornerRadius = UDim.new(0, 10)
	btnCorner.Parent = prestigeButton

	prestigeButton.Activated:Connect(onPrestige)

	screenGui.Parent = playerGui
end

local function formatNumber(n: number): string
	if n >= 1e9 then
		return string.format("%.1fB", n / 1e9)
	elseif n >= 1e6 then
		return string.format("%.1fM", n / 1e6)
	elseif n >= 1e3 then
		return string.format("%.1fK", n / 1e3)
	end
	return tostring(math.floor(n))
end

function HUD.Update(state: any)
	if currencyLabel then
		currencyLabel.Text = formatNumber(state.Currency) .. " " .. Config.CurrencyName
	end
	if prestigeButton then
		prestigeButton.Visible = state.CanPrestige == true
	end
end

return HUD
