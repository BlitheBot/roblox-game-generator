--[[
	HUDClient — unified, polished HUD for every generated game.

	Layout:
	┌─────────────────────────────────────────────────┐
	│ [💰 1,234]                        [⭐ NAME]      │
	│                                                  │
	│                  [GAME WORLD]                    │
	│                                                  │
	│               [ 🎒 Inventory ] [ 🛒 Shop ]      │
	└─────────────────────────────────────────────────┘

	Mobile-first (44px touch targets), compact, and animated. It is intentionally
	gameplay-agnostic: it reads the currency value off whatever state remote a
	template already pushes (StateChanged / RoundState) plus optional UpdateHUD
	and Notification remotes, so it works across all four templates without any
	gameplay-system change.
--]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local TweenService = game:GetService("TweenService")
local GuiService = game:GetService("GuiService")

local DS = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

-- This ScreenGui ignores the GUI inset, so add the top inset (notch / topbar)
-- manually to keep top elements out of the mobile safe area.
local topInset = GuiService:GetGuiInset().Y
local topY = 12 + topInset
local mobileScale = DS.isSmallScreen() and 0.85 or 1

local hudGui = Instance.new("ScreenGui")
hudGui.Name = "HUD"
hudGui.ResetOnSpawn = false
hudGui.DisplayOrder = 10
hudGui.IgnoreGuiInset = true
hudGui.Parent = playerGui

local function formatNumber(n)
	n = tonumber(n) or 0
	if n >= 1e9 then
		return string.format("%.1fB", n / 1e9)
	elseif n >= 1e6 then
		return string.format("%.1fM", n / 1e6)
	elseif n >= 1e3 then
		return string.format("%.1fK", n / 1e3)
	end
	return tostring(math.floor(n))
end

-- ═══════════════════════════════════
-- TOP LEFT — Currency
-- ═══════════════════════════════════
local currencyPanel = DS.createPanel({
	size = DS.getResponsiveSize(UDim2.new(0, 168, 0, 44)),
	position = UDim2.new(0, 12, 0, topY),
	color = DS.Colors.BgMedium,
	transparency = 0.05,
	shadow = true,
	parent = hudGui,
})

local coinIcon = Instance.new("Frame")
coinIcon.Size = UDim2.new(0, 28, 0, 28)
coinIcon.Position = UDim2.new(0, 8, 0.5, -14)
coinIcon.BackgroundColor3 = DS.Colors.CurrencyGold
coinIcon.BorderSizePixel = 0
coinIcon.Parent = currencyPanel
local coinCorner = Instance.new("UICorner")
coinCorner.CornerRadius = DS.CornerRadius.Full
coinCorner.Parent = coinIcon

local coinGlyph = Instance.new("TextLabel")
coinGlyph.Size = UDim2.new(1, 0, 1, 0)
coinGlyph.BackgroundTransparency = 1
coinGlyph.Text = "$"
coinGlyph.Font = DS.Fonts.Number
coinGlyph.TextSize = 18
coinGlyph.TextColor3 = DS.Colors.PrimaryText
coinGlyph.Parent = coinIcon

local currencyLabel = DS.createLabel({
	text = "0",
	size = UDim2.new(1, -48, 1, 0),
	position = UDim2.new(0, 44, 0, 0),
	style = "number",
	align = "Left",
	parent = currencyPanel,
})

-- Animated currency counter: each update bumps a token; the running coroutine
-- stops as soon as a newer update supersedes it, so concurrent updates never
-- fight over the label.
local displayedCurrency = 0
local animToken = 0

local function updateCurrencyDisplay(newAmount)
	newAmount = tonumber(newAmount)
	if not newAmount then
		return
	end
	local startValue = displayedCurrency
	local diff = newAmount - startValue
	if diff == 0 then
		return
	end

	animToken += 1
	local myToken = animToken
	local steps = 14
	task.spawn(function()
		for i = 1, steps do
			if animToken ~= myToken then
				return
			end
			displayedCurrency = startValue + diff * (i / steps)
			currencyLabel.Text = formatNumber(displayedCurrency)
			task.wait(0.02)
		end
		displayedCurrency = newAmount
		currencyLabel.Text = formatNumber(newAmount)
	end)

	if diff > 0 then
		TweenService:Create(currencyPanel, DS.Animations.Fast, { BackgroundColor3 = Color3.fromRGB(60, 50, 10) }):Play()
		task.delay(0.3, function()
			TweenService:Create(currencyPanel, DS.Animations.Normal, { BackgroundColor3 = DS.Colors.BgMedium }):Play()
		end)
	end
end

-- ═══════════════════════════════════
-- TOP RIGHT — Stats / status
-- ═══════════════════════════════════
local statsPanel = DS.createPanel({
	size = DS.getResponsiveSize(UDim2.new(0, 168, 0, 44)),
	position = UDim2.new(1, DS.isSmallScreen() and -155 or -180, 0, topY),
	color = DS.Colors.BgMedium,
	transparency = 0.05,
	shadow = true,
	parent = hudGui,
})

local statsLabel = DS.createLabel({
	text = "⭐ " .. player.DisplayName,
	size = UDim2.new(1, -16, 1, 0),
	position = UDim2.new(0, 8, 0, 0),
	style = "subtitle",
	align = "Center",
	parent = statsPanel,
})

-- ═══════════════════════════════════
-- TOP CENTER — Live event banner
-- ═══════════════════════════════════
local eventBanner = DS.createPanel({
	size = DS.getResponsiveSize(UDim2.new(0, 260, 0, 32)),
	position = UDim2.new(0.5, 0, 0, topY + 50),
	color = DS.Colors.Accent or DS.Colors.Primary,
	shadow = true,
	parent = hudGui,
})
eventBanner.AnchorPoint = Vector2.new(0.5, 0)
eventBanner.Visible = false

local eventLabel = DS.createLabel({
	text = "",
	size = UDim2.new(1, -12, 1, 0),
	position = UDim2.new(0, 6, 0, 0),
	style = "subtitle",
	align = "Center",
	color = DS.Colors.PrimaryText,
	parent = eventBanner,
})

local eventName = nil
local eventDeadline = 0
local eventToken = 0

local function setEvent(name, endsIn)
	if not name or name == false then
		eventName = nil
		eventToken += 1
		eventBanner.Visible = false
		return
	end
	eventName = tostring(name)
	eventDeadline = os.clock() + (tonumber(endsIn) or 0)
	eventBanner.Visible = true
	eventToken += 1
	local myToken = eventToken
	task.spawn(function()
		while eventToken == myToken and eventName do
			local left = math.max(0, math.floor(eventDeadline - os.clock()))
			eventLabel.Text = string.format("%s · %d:%02d", eventName, left // 60, left % 60)
			if left <= 0 then
				eventBanner.Visible = false
				return
			end
			task.wait(1)
		end
	end)
end

-- ═══════════════════════════════════
-- BOTTOM CENTER — Quick action bar
-- ═══════════════════════════════════
local actionBar = DS.createPanel({
	size = UDim2.new(0, 0, 0, 52),
	position = UDim2.new(0.5, 0, 1, -64),
	color = DS.Colors.BgMedium,
	transparency = 0.05,
	shadow = true,
	parent = hudGui,
})
actionBar.AnchorPoint = Vector2.new(0.5, 0)
actionBar.AutomaticSize = Enum.AutomaticSize.X

local actionLayout = Instance.new("UIListLayout")
actionLayout.FillDirection = Enum.FillDirection.Horizontal
actionLayout.HorizontalAlignment = Enum.HorizontalAlignment.Center
actionLayout.VerticalAlignment = Enum.VerticalAlignment.Center
actionLayout.Padding = UDim.new(0, 6)
actionLayout.Parent = actionBar

local actionPadding = Instance.new("UIPadding")
actionPadding.PaddingLeft = UDim.new(0, 8)
actionPadding.PaddingRight = UDim.new(0, 8)
actionPadding.PaddingTop = UDim.new(0, 6)
actionPadding.PaddingBottom = UDim.new(0, 6)
actionPadding.Parent = actionBar

local function addActionButton(icon, label, onClick)
	return DS.createButton({
		text = label,
		icon = icon,
		size = UDim2.new(0, 110, 0, 40),
		style = "secondary",
		onClick = onClick,
		parent = actionBar,
	})
end

-- Shop button drives the shared ShopClient via a client-side BindableEvent so
-- no extra RemoteEvent (and no server handler) is required.
local toggleShop = ReplicatedStorage:WaitForChild("ToggleShop", 10)
addActionButton("🛒", "Shop", function()
	if toggleShop then
		toggleShop:Fire()
	end
end)

-- ═══════════════════════════════════
-- NOTIFICATIONS
-- ═══════════════════════════════════
local notifContainer = Instance.new("Frame")
notifContainer.Size = UDim2.new(0, 300, 1, -140)
notifContainer.Position = UDim2.new(1, -312, 0, 64)
notifContainer.BackgroundTransparency = 1
notifContainer.Parent = hudGui

local notifLayout = Instance.new("UIListLayout")
notifLayout.Padding = UDim.new(0, 6)
notifLayout.HorizontalAlignment = Enum.HorizontalAlignment.Right
notifLayout.VerticalAlignment = Enum.VerticalAlignment.Top
notifLayout.SortOrder = Enum.SortOrder.LayoutOrder
notifLayout.Parent = notifContainer

local function showNotification(title, message, notifType)
	local typeColors = {
		success = DS.Colors.Success,
		error = DS.Colors.Error,
		warning = DS.Colors.Warning,
		info = DS.Colors.Info,
		reward = DS.Colors.CurrencyGold,
	}
	local accentColor = typeColors[notifType] or DS.Colors.Info

	local notif = DS.createPanel({
		size = UDim2.new(1, 0, 0, 64),
		color = DS.Colors.BgMedium,
		shadow = true,
		parent = notifContainer,
	})

	local accent = Instance.new("Frame")
	accent.Size = UDim2.new(0, 4, 1, 0)
	accent.BackgroundColor3 = accentColor
	accent.BorderSizePixel = 0
	accent.Parent = notif
	local accentCorner = Instance.new("UICorner")
	accentCorner.CornerRadius = DS.CornerRadius.SM
	accentCorner.Parent = accent

	DS.createLabel({
		text = title or "",
		size = UDim2.new(1, -24, 0, 24),
		position = UDim2.new(0, 16, 0, 8),
		style = "subtitle",
		parent = notif,
	})
	DS.createLabel({
		text = message or "",
		size = UDim2.new(1, -24, 0, 20),
		position = UDim2.new(0, 16, 0, 32),
		style = "small",
		parent = notif,
	})

	notif.Position = UDim2.new(1, 20, 0, 0)
	TweenService:Create(notif, DS.Animations.Spring, { Position = UDim2.new(0, 0, 0, 0) }):Play()

	task.delay(4, function()
		TweenService:Create(notif, DS.Animations.Normal, { Position = UDim2.new(1, 20, 0, 0), BackgroundTransparency = 1 }):Play()
		task.delay(0.3, function()
			notif:Destroy()
		end)
	end)
end

-- ═══════════════════════════════════
-- STATE WIRING
-- ═══════════════════════════════════
local function applyState(data)
	if typeof(data) ~= "table" then
		return
	end
	local currency = data.Currency or data.currency
	if currency ~= nil then
		updateCurrencyDisplay(currency)
	end
	if data.stats then
		statsLabel.Text = "⭐ " .. tostring(data.stats)
	elseif data.Phase then
		statsLabel.Text = "⭐ " .. tostring(data.Phase):upper()
	end
	if data.activeEvent ~= nil then
		setEvent(data.activeEvent, data.eventEndsIn)
	end
end

local Remotes = ReplicatedStorage:WaitForChild("Remotes", 10)
if Remotes then
	-- Connect to whichever state-push remotes this template ships.
	for _, name in { "StateChanged", "RoundState", "UpdateHUD" } do
		local remote = Remotes:FindFirstChild(name)
		if remote and remote:IsA("RemoteEvent") then
			remote.OnClientEvent:Connect(applyState)
		end
	end

	local notification = Remotes:FindFirstChild("Notification")
	if notification and notification:IsA("RemoteEvent") then
		notification.OnClientEvent:Connect(function(title, message, notifType)
			showNotification(title, message, notifType)
		end)
	end
end

return {
	showNotification = showNotification,
	updateCurrency = updateCurrencyDisplay,
	addActionButton = addActionButton,
}
