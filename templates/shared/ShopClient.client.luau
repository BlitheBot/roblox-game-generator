--[[
	ShopClient — professional, conversion-oriented shop UI for every game.

	- Tab navigation (All / Passes / Currency / Cosmetics)
	- Featured "daily deal" highlight on the first item
	- Item cards with clear pricing, owned badge, animated buy feedback
	- Opens from the HUD action bar via the client-side ToggleShop BindableEvent

	Items are read defensively from the template's Config (ShopItems / GamePasses)
	so the same script works across all four templates; nothing here changes a
	gameplay system — purchases route to MarketplaceService (real ids) or the
	existing RequestPurchase remote when present.
--]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
local MarketplaceService = game:GetService("MarketplaceService")

local DS = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

-- ── Source items from Config (best-effort, never hard-fails) ──────────────
local currencyName = "Coins"
local catalog = {}

do
	local ok, Config = pcall(function()
		return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
	end)
	if ok and typeof(Config) == "table" then
		if type(Config.CurrencyName) == "string" then
			currencyName = Config.CurrencyName
		end
		for _, item in ipairs(Config.ShopItems or {}) do
			table.insert(catalog, {
				name = item.name or "Item",
				description = (item.type or "cosmetic"):gsub("^%l", string.upper),
				price = item.price or 0,
				category = (item.type == "currency") and "currency" or "cosmetics",
				icon = item.type == "currency" and "💰" or "✨",
			})
		end
		for _, pass in ipairs(Config.GamePasses or {}) do
			table.insert(catalog, {
				name = pass.name or "Pass",
				description = (pass.effect or "Boost"):gsub("_", " "),
				price = pass.price_robux or 99,
				robux = true,
				passId = tonumber(pass.id) or 0,
				category = "passes",
				icon = "🎟️",
			})
		end
	end
end

if #catalog == 0 then
	catalog = {
		{ name = "Starter Pack", description = "Boost your start", price = 250, category = "currency", icon = "💰" },
		{ name = "Sparkle Trail", description = "Cosmetic effect", price = 500, category = "cosmetics", icon = "✨" },
	}
end

-- ── GUI scaffolding ───────────────────────────────────────────────────────
local shopGui = Instance.new("ScreenGui")
shopGui.Name = "ShopGui"
shopGui.ResetOnSpawn = false
shopGui.DisplayOrder = 20
shopGui.Enabled = false
shopGui.IgnoreGuiInset = true
shopGui.Parent = playerGui

local backdrop = Instance.new("Frame")
backdrop.Size = UDim2.new(1, 0, 1, 0)
backdrop.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
backdrop.BackgroundTransparency = 0.5
backdrop.BorderSizePixel = 0
backdrop.Parent = shopGui

local mainPanel = DS.createPanel({
	size = UDim2.new(0, 560, 0, 480),
	position = UDim2.new(0.5, -280, 0.5, -240),
	color = DS.Colors.BgDark,
	shadow = true,
	parent = shopGui,
})
mainPanel.ClipsDescendants = true

local header = DS.createPanel({
	size = UDim2.new(1, 0, 0, 56),
	color = DS.Colors.BgMedium,
	corner = DS.CornerRadius.MD,
	parent = mainPanel,
})

DS.createLabel({
	text = "🛒  SHOP",
	size = UDim2.new(1, -60, 1, 0),
	position = UDim2.new(0, 20, 0, 0),
	style = "title",
	parent = header,
})

local isOpen = false
local function closeShop()
	TweenService:Create(mainPanel, DS.Animations.Normal, {
		Size = UDim2.new(0, 0, 0, 0),
		Position = UDim2.new(0.5, 0, 0.5, 0),
	}):Play()
	task.delay(0.25, function()
		shopGui.Enabled = false
		isOpen = false
	end)
end

DS.createButton({
	text = "✕",
	size = UDim2.new(0, 40, 0, 40),
	position = UDim2.new(1, -48, 0.5, -20),
	style = "ghost",
	onClick = closeShop,
	parent = header,
})

-- ── Tabs ──────────────────────────────────────────────────────────────────
local tabBar = Instance.new("Frame")
tabBar.Size = UDim2.new(1, -32, 0, 40)
tabBar.Position = UDim2.new(0, 16, 0, 64)
tabBar.BackgroundTransparency = 1
tabBar.Parent = mainPanel

local tabLayout = Instance.new("UIListLayout")
tabLayout.FillDirection = Enum.FillDirection.Horizontal
tabLayout.Padding = UDim.new(0, 6)
tabLayout.Parent = tabBar

local itemScroll = Instance.new("ScrollingFrame")
itemScroll.Size = UDim2.new(1, -32, 1, -180)
itemScroll.Position = UDim2.new(0, 16, 0, 120)
itemScroll.BackgroundTransparency = 1
itemScroll.BorderSizePixel = 0
itemScroll.ScrollBarThickness = 4
itemScroll.ScrollBarImageColor3 = DS.Colors.BgLight
itemScroll.CanvasSize = UDim2.new(0, 0, 0, 0)
itemScroll.AutomaticCanvasSize = Enum.AutomaticSize.Y
itemScroll.Parent = mainPanel

local itemGrid = Instance.new("UIGridLayout")
itemGrid.CellSize = UDim2.new(0, 156, 0, 180)
itemGrid.CellPadding = UDim2.new(0, 8, 0, 8)
itemGrid.HorizontalAlignment = Enum.HorizontalAlignment.Left
itemGrid.Parent = itemScroll

DS.createDivider(mainPanel, UDim2.new(0, 0, 0, 112))

local requestPurchase
do
	local remotes = ReplicatedStorage:FindFirstChild("Remotes")
	if remotes then
		local rp = remotes:FindFirstChild("RequestPurchase")
		if rp and rp:IsA("RemoteEvent") then
			requestPurchase = rp
		end
	end
end

local function buyItem(item, buyBtn)
	if item.robux and item.passId and item.passId > 0 then
		MarketplaceService:PromptGamePassPurchase(player, item.passId)
		return
	end
	if item.productId and item.productId > 0 then
		MarketplaceService:PromptProductPurchase(player, item.productId)
		return
	end
	if requestPurchase then
		requestPurchase:FireServer(item.name)
	end
	-- Visual confirmation pulse
	local original = buyBtn.BackgroundColor3
	buyBtn.BackgroundColor3 = DS.Colors.Success
	TweenService:Create(buyBtn, DS.Animations.Normal, { BackgroundColor3 = original }):Play()
end

local function createItemCard(item, isFeatured)
	local card = DS.createPanel({
		size = UDim2.new(0, 156, 0, 180),
		color = DS.Colors.BgMedium,
		parent = itemScroll,
	})

	if isFeatured then
		local glow = Instance.new("UIStroke")
		glow.Color = DS.Colors.Warning
		glow.Thickness = 2
		glow.Parent = card
	end

	local iconArea = DS.createPanel({
		size = UDim2.new(1, -16, 0, 90),
		position = UDim2.new(0, 8, 0, 8),
		color = DS.Colors.BgLight,
		parent = card,
	})

	local iconLabel = Instance.new("TextLabel")
	iconLabel.Size = UDim2.new(1, 0, 1, 0)
	iconLabel.BackgroundTransparency = 1
	iconLabel.Text = item.icon or "🎁"
	iconLabel.TextSize = 40
	iconLabel.Font = DS.Fonts.Body
	iconLabel.Parent = iconArea

	if isFeatured then
		DS.createBadge("⭐ DEAL", DS.Colors.Warning, card)
	end

	DS.createLabel({
		text = item.name,
		size = UDim2.new(1, -16, 0, 20),
		position = UDim2.new(0, 8, 0, 106),
		style = "subtitle",
		parent = card,
	})
	DS.createLabel({
		text = item.description or "",
		size = UDim2.new(1, -16, 0, 28),
		position = UDim2.new(0, 8, 0, 126),
		style = "small",
		parent = card,
	})

	local priceText = item.robux and ("R$ " .. tostring(item.price)) or ("🪙 " .. tostring(item.price))
	local buyBtn
	buyBtn = DS.createButton({
		text = priceText,
		size = UDim2.new(1, -16, 0, 32),
		position = UDim2.new(0, 8, 1, -40),
		style = "primary",
		onClick = function()
			buyItem(item, buyBtn)
		end,
		parent = card,
	})

	return card
end

local tabs = { "All", "Passes", "Currency", "Cosmetics" }
local tabButtons = {}
local currentTab = "all"

local function refreshItems()
	for _, child in itemScroll:GetChildren() do
		if child:IsA("Frame") then
			child:Destroy()
		end
	end
	local first = true
	for _, item in ipairs(catalog) do
		if currentTab == "all" or item.category == currentTab then
			createItemCard(item, first and currentTab == "all")
			first = false
		end
	end
end

local function setActiveTab(tabName)
	currentTab = tabName:lower()
	for _, btn in pairs(tabButtons) do
		local isActive = btn.Name == tabName
		TweenService:Create(btn, DS.Animations.Fast, {
			BackgroundColor3 = isActive and DS.Colors.Primary or DS.Colors.BgLight,
			TextColor3 = isActive and DS.Colors.PrimaryText or DS.Colors.TextSecondary,
		}):Play()
	end
	refreshItems()
end

for _, tabName in ipairs(tabs) do
	local tabBtn = DS.createButton({
		text = tabName,
		size = UDim2.new(0, 110, 0, 36),
		style = "secondary",
		onClick = function()
			setActiveTab(tabName)
		end,
		parent = tabBar,
	})
	tabBtn.Name = tabName
	table.insert(tabButtons, tabBtn)
end

-- ── Footer balance ──────────────────────────────────────────────────────────
local footer = DS.createPanel({
	size = UDim2.new(1, 0, 0, 48),
	position = UDim2.new(0, 0, 1, -48),
	color = DS.Colors.BgMedium,
	parent = mainPanel,
})

local balanceLabel = DS.createLabel({
	text = "Your balance: 0 " .. currencyName,
	size = UDim2.new(1, 0, 1, 0),
	style = "body",
	align = "Center",
	parent = footer,
})

-- ── Open / close ────────────────────────────────────────────────────────────
local function openShop()
	if isOpen then
		return
	end
	shopGui.Enabled = true
	isOpen = true
	mainPanel.Size = UDim2.new(0, 0, 0, 0)
	mainPanel.Position = UDim2.new(0.5, 0, 0.5, 0)
	TweenService:Create(mainPanel, DS.Animations.Spring, {
		Size = UDim2.new(0, 560, 0, 480),
		Position = UDim2.new(0.5, -280, 0.5, -240),
	}):Play()
	setActiveTab("All")
end

backdrop.InputBegan:Connect(function(input)
	if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
		closeShop()
	end
end)

local toggleShop = ReplicatedStorage:WaitForChild("ToggleShop", 10)
if toggleShop then
	toggleShop.Event:Connect(function()
		if isOpen then
			closeShop()
		else
			openShop()
		end
	end)
end

-- Keep footer balance in sync with whatever state remote the template pushes.
local remotes = ReplicatedStorage:FindFirstChild("Remotes")
if remotes then
	for _, name in { "StateChanged", "RoundState", "UpdateHUD" } do
		local remote = remotes:FindFirstChild(name)
		if remote and remote:IsA("RemoteEvent") then
			remote.OnClientEvent:Connect(function(data)
				if typeof(data) == "table" then
					local currency = data.Currency or data.currency
					if currency ~= nil then
						balanceLabel.Text = "Your balance: " .. tostring(math.floor(currency)) .. " " .. currencyName
					end
				end
			end)
		end
	end
end

refreshItems()

return { open = openShop }
