--!strict
-- Pet collect client: currency HUD, egg shop buttons, scrolling pet
-- inventory with equip toggles. Sends intents only.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage.Shared.Config)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local RequestHatch = Remotes:WaitForChild("RequestHatch") :: RemoteEvent
local RequestEquip = Remotes:WaitForChild("RequestEquip") :: RemoteEvent
local StateChanged = Remotes:WaitForChild("StateChanged") :: RemoteEvent

local playerGui = Players.LocalPlayer:WaitForChild("PlayerGui")

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "PetUI"
screenGui.ResetOnSpawn = false

local currencyLabel = Instance.new("TextLabel")
currencyLabel.Size = UDim2.fromOffset(260, 40)
currencyLabel.Position = UDim2.new(0.5, -130, 0, 12)
currencyLabel.BackgroundColor3 = Color3.fromRGB(30, 30, 40)
currencyLabel.BackgroundTransparency = 0.25
currencyLabel.TextColor3 = Color3.fromRGB(255, 225, 120)
currencyLabel.TextScaled = true
currencyLabel.Font = Enum.Font.FredokaOne
currencyLabel.Parent = screenGui

-- Egg shop (left side)
for i, egg in Config.Eggs do
	local button = Instance.new("TextButton")
	button.Size = UDim2.fromOffset(220, 44)
	button.Position = UDim2.new(0, 12, 0, 70 + (i - 1) * 52)
	button.BackgroundColor3 = Color3.fromRGB(60, 130, 80)
	button.TextColor3 = Color3.new(1, 1, 1)
	button.TextScaled = true
	button.Font = Enum.Font.FredokaOne
	button.Text = ("%s — %d"):format(egg.Name, egg.Cost)
	button.Parent = screenGui
	button.Activated:Connect(function()
		RequestHatch:FireServer(egg.Name)
	end)
end

-- Pet inventory (right side, scrolling)
local inventory = Instance.new("ScrollingFrame")
inventory.Size = UDim2.fromOffset(240, 320)
inventory.Position = UDim2.new(1, -252, 0.5, -160)
inventory.BackgroundColor3 = Color3.fromRGB(30, 30, 40)
inventory.BackgroundTransparency = 0.25
inventory.CanvasSize = UDim2.new(0, 0, 0, 0)
inventory.AutomaticCanvasSize = Enum.AutomaticSize.Y
inventory.Parent = screenGui

local listLayout = Instance.new("UIListLayout")
listLayout.Padding = UDim.new(0, 4)
listLayout.Parent = inventory

screenGui.Parent = playerGui

local function rarityColor(rarityName: string): Color3
	for _, rarity in Config.Rarities do
		if rarity.Name == rarityName then
			return rarity.Color
		end
	end
	return Color3.new(1, 1, 1)
end

StateChanged.OnClientEvent:Connect(function(state)
	currencyLabel.Text = math.floor(state.Currency) .. " " .. Config.CurrencyName

	-- Rebuild inventory rows (small list; fine to rebuild per update)
	for _, child in inventory:GetChildren() do
		if child:IsA("TextButton") then
			child:Destroy()
		end
	end

	local equippedSet: { [string]: boolean } = {}
	for _, petId in state.Equipped do
		equippedSet[petId] = true
	end

	for petId, pet in state.Pets do
		local row = Instance.new("TextButton")
		row.Size = UDim2.new(1, -8, 0, 40)
		row.BackgroundColor3 = equippedSet[petId] and Color3.fromRGB(70, 100, 160)
			or Color3.fromRGB(50, 50, 60)
		row.TextColor3 = rarityColor(pet.Rarity)
		row.TextScaled = true
		row.Font = Enum.Font.FredokaOne
		row.Text = ("%s (%s) x%d"):format(pet.Name, pet.Rarity, pet.Power)
		row.Parent = inventory
		row.Activated:Connect(function()
			RequestEquip:FireServer(petId)
		end)
	end
end)
