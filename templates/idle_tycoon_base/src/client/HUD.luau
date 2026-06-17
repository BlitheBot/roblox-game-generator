--!strict
-- HUD: prestige button. Pure rendering; all state comes from the server via
-- StateChanged. The currency counter now lives in the shared HUDClient
-- (ReplicatedStorage-driven), so this script only owns the prestige CTA.

local Players = game:GetService("Players")

local Config = require(game.ReplicatedStorage.Shared.Config)

local HUD = {}

local screenGui: ScreenGui? = nil
local prestigeButton: TextButton? = nil

function HUD.Build(onPrestige: () -> ())
	local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

	screenGui = Instance.new("ScreenGui")
	screenGui.Name = "PrestigeHUD"
	screenGui.ResetOnSpawn = false

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

function HUD.Update(state: any)
	if prestigeButton then
		prestigeButton.Visible = state.CanPrestige == true
	end
end

return HUD
