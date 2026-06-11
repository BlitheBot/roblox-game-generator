--!strict
-- UpgradeUI: scrollable upgrade list with buy buttons. Sends purchase
-- requests to the server; never mutates state locally.

local Players = game:GetService("Players")

local Config = require(game.ReplicatedStorage.Shared.Config)

local UpgradeUI = {}

local rows: { [string]: TextButton } = {}

function UpgradeUI.Build(onBuyUpgrade: (upgradeName: string) -> ())
	local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

	local screenGui = Instance.new("ScreenGui")
	screenGui.Name = "UpgradeUI"
	screenGui.ResetOnSpawn = false

	local panel = Instance.new("Frame")
	panel.Size = UDim2.fromOffset(240, 56 * #Config.Upgrades + 48)
	panel.Position = UDim2.new(0, 12, 0.5, -((56 * #Config.Upgrades + 48) // 2))
	panel.BackgroundColor3 = Color3.fromRGB(30, 30, 40)
	panel.BackgroundTransparency = 0.25
	panel.Parent = screenGui

	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 10)
	corner.Parent = panel

	local title = Instance.new("TextLabel")
	title.Size = UDim2.new(1, 0, 0, 40)
	title.BackgroundTransparency = 1
	title.TextColor3 = Color3.new(1, 1, 1)
	title.TextScaled = true
	title.Font = Enum.Font.FredokaOne
	title.Text = "{{THEME_DESCRIPTOR}} Upgrades"
	title.Parent = panel

	for i, def in Config.Upgrades do
		local button = Instance.new("TextButton")
		button.Size = UDim2.new(1, -16, 0, 48)
		button.Position = UDim2.new(0, 8, 0, 44 + (i - 1) * 56)
		button.BackgroundColor3 = Color3.fromRGB(60, 130, 80)
		button.TextColor3 = Color3.new(1, 1, 1)
		button.TextScaled = true
		button.Font = Enum.Font.FredokaOne
		button.Text = def.Name
		button.Parent = panel

		local btnCorner = Instance.new("UICorner")
		btnCorner.CornerRadius = UDim.new(0, 8)
		btnCorner.Parent = button

		button.Activated:Connect(function()
			onBuyUpgrade(def.Name)
		end)
		rows[def.Name] = button
	end

	screenGui.Parent = playerGui
end

function UpgradeUI.Update(state: any)
	for _, def in Config.Upgrades do
		local button = rows[def.Name]
		if button then
			local upgrade = state.Upgrades[def.Name]
			local level = upgrade and upgrade.Level or 0
			local cost = math.floor(def.BaseCost * def.CostMultiplier ^ level)
			if level >= def.MaxLevel then
				button.Text = def.Name .. " (MAX)"
				button.BackgroundColor3 = Color3.fromRGB(90, 90, 90)
			else
				button.Text = ("%s [%d] — %d"):format(def.Name, level, cost)
				button.BackgroundColor3 = state.Currency >= cost
						and Color3.fromRGB(60, 130, 80)
					or Color3.fromRGB(120, 60, 60)
			end
		end
	end
end

return UpgradeUI
