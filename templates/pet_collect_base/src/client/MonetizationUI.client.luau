--!strict
-- MonetizationUI: drop-in client UI for the three-tier monetization layer.
-- Shop panel (daily deal with crossed-out price, anchored currency
-- bundles with BEST VALUE badge, season pass with transparent value math,
-- VIP, limited items with live stock / SOLD OUT, founders counter, name
-- tag, gifting) plus a purchase-preview modal shown before every Robux
-- prompt so there are never surprises after purchase.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local screenGui = Instance.new("ScreenGui")
screenGui.Name = "MonetizationUI"
screenGui.ResetOnSpawn = false
screenGui.Parent = playerGui

local state: { [string]: any } = {}
local requestRemote: RemoteEvent? = nil

-- ── widgets ─────────────────────────────────────────────────

local function styled(frame: GuiObject, radius: number?)
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, radius or 10)
	corner.Parent = frame
end

local function label(parent: Instance, text: string, size: number, bold: boolean): TextLabel
	local l = Instance.new("TextLabel")
	l.BackgroundTransparency = 1
	l.Size = UDim2.new(1, -16, 0, size + 8)
	l.Font = if bold then Enum.Font.GothamBold else Enum.Font.Gotham
	l.TextSize = size
	l.TextColor3 = Color3.fromRGB(255, 255, 255)
	l.TextXAlignment = Enum.TextXAlignment.Left
	l.TextWrapped = true
	l.Text = text
	l.Parent = parent
	return l
end

local function button(parent: Instance, text: string, color: Color3): TextButton
	local b = Instance.new("TextButton")
	b.Size = UDim2.new(0, 150, 0, 32)
	b.BackgroundColor3 = color
	b.Font = Enum.Font.GothamBold
	b.TextSize = 15
	b.TextColor3 = Color3.fromRGB(255, 255, 255)
	b.Text = text
	styled(b, 8)
	b.Parent = parent
	return b
end

-- Toast announcements (flash sales, gifts, tier-ups, starter offer)
local function toast(text: string, seconds: number?)
	local frame = Instance.new("Frame")
	frame.AnchorPoint = Vector2.new(0.5, 0)
	frame.Position = UDim2.new(0.5, 0, 0.02, 0)
	frame.Size = UDim2.new(0, 420, 0, 44)
	frame.BackgroundColor3 = Color3.fromRGB(40, 32, 60)
	styled(frame)
	local l = label(frame, text, 16, true)
	l.Position = UDim2.new(0, 12, 0, 6)
	l.TextXAlignment = Enum.TextXAlignment.Center
	frame.Parent = screenGui
	task.delay(seconds or 6, function()
		frame:Destroy()
	end)
end

-- Purchase preview modal: exactly what you get, then confirm
local function purchasePreview(title: string, lines: { string }, onConfirm: () -> ())
	local overlay = Instance.new("Frame")
	overlay.Size = UDim2.new(1, 0, 1, 0)
	overlay.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
	overlay.BackgroundTransparency = 0.45
	overlay.Parent = screenGui

	local panel = Instance.new("Frame")
	panel.AnchorPoint = Vector2.new(0.5, 0.5)
	panel.Position = UDim2.new(0.5, 0, 0.5, 0)
	panel.Size = UDim2.new(0, 360, 0, 130 + #lines * 24)
	panel.BackgroundColor3 = Color3.fromRGB(34, 36, 46)
	styled(panel)
	panel.Parent = overlay

	local list = Instance.new("UIListLayout")
	list.Padding = UDim.new(0, 4)
	list.HorizontalAlignment = Enum.HorizontalAlignment.Center
	list.Parent = panel

	label(panel, title, 20, true)
	label(panel, "You will receive:", 14, false)
	for _, line in lines do
		label(panel, "• " .. line, 15, false)
	end

	local row = Instance.new("Frame")
	row.BackgroundTransparency = 1
	row.Size = UDim2.new(1, 0, 0, 40)
	row.Parent = panel
	local rowList = Instance.new("UIListLayout")
	rowList.FillDirection = Enum.FillDirection.Horizontal
	rowList.Padding = UDim.new(0, 12)
	rowList.HorizontalAlignment = Enum.HorizontalAlignment.Center
	rowList.Parent = row

	button(row, "Confirm", Color3.fromRGB(60, 160, 80)).Activated:Connect(function()
		overlay:Destroy()
		onConfirm()
	end)
	button(row, "Cancel", Color3.fromRGB(120, 60, 60)).Activated:Connect(function()
		overlay:Destroy()
	end)
end

local function request(...)
	if requestRemote then
		requestRemote:FireServer(...)
	end
end

-- ── shop panel ──────────────────────────────────────────────

local shopOpen = false
local shopFrame: Frame? = nil

local function section(parent: Instance, title: string): Frame
	local frame = Instance.new("Frame")
	frame.BackgroundColor3 = Color3.fromRGB(40, 43, 56)
	frame.Size = UDim2.new(1, -12, 0, 40)
	frame.AutomaticSize = Enum.AutomaticSize.Y
	styled(frame, 8)
	frame.Parent = parent
	local list = Instance.new("UIListLayout")
	list.Padding = UDim.new(0, 4)
	list.Parent = frame
	local pad = Instance.new("UIPadding")
	pad.PaddingTop = UDim.new(0, 8)
	pad.PaddingBottom = UDim.new(0, 8)
	pad.PaddingLeft = UDim.new(0, 10)
	pad.PaddingRight = UDim.new(0, 10)
	pad.Parent = frame
	label(frame, title, 17, true)
	return frame
end

local function rebuildShop()
	if shopFrame then
		shopFrame:Destroy()
		shopFrame = nil
	end
	if not shopOpen then
		return
	end
	local config = state.Config or {}
	local casual = config.casual_tier or {}
	local mid = config.mid_tier or {}
	local whale = config.whale_tier or {}
	local owned = state.Owned or {}
	local productIds = (config.product_ids or {}) :: { [string]: number }

	local frame = Instance.new("ScrollingFrame")
	frame.AnchorPoint = Vector2.new(1, 0.5)
	frame.Position = UDim2.new(1, -10, 0.5, 0)
	frame.Size = UDim2.new(0, 380, 0.8, 0)
	frame.BackgroundColor3 = Color3.fromRGB(28, 30, 40)
	frame.ScrollBarThickness = 6
	frame.AutomaticCanvasSize = Enum.AutomaticSize.Y
	frame.CanvasSize = UDim2.new(0, 0, 0, 0)
	styled(frame)
	frame.Parent = screenGui
	shopFrame = frame
	local list = Instance.new("UIListLayout")
	list.Padding = UDim.new(0, 8)
	list.HorizontalAlignment = Enum.HorizontalAlignment.Center
	list.Parent = frame

	-- Daily deal
	local deal = state.DailyDeal
	if deal then
		local s = section(frame, "🔥 Daily Deal")
		label(s, ("%s — %d (was %d)"):format(deal.name, deal.price, deal.original), 15, false)
		if owned[deal.name] then
			label(s, "Owned ✓", 14, false)
		else
			button(s, "Buy", Color3.fromRGB(220, 120, 40)).Activated:Connect(function()
				request("buy_item", deal.name)
			end)
		end
	end

	-- Flash sale
	local sale = state.FlashSale
	if sale and not owned[sale.name] then
		local s = section(frame, "⚡ Flash Sale")
		label(s, ("%s — %d (was %d)"):format(sale.name, sale.price, sale.original), 15, false)
		button(s, "Buy", Color3.fromRGB(220, 80, 80)).Activated:Connect(function()
			request("buy_item", sale.name)
		end)
	end

	-- Starter pack (one-time welcome offer, no countdown)
	if state.StarterPackOwned == false and productIds.starter_pack and productIds.starter_pack > 0 then
		local s = section(frame, "🎁 Welcome Gift — 99 R$")
		label(s, tostring(casual.starter_pack_contents or "A welcome bundle"), 14, false)
		button(s, "View", Color3.fromRGB(80, 140, 220)).Activated:Connect(function()
			purchasePreview("Welcome Pack — 99 R$", {
				tostring(casual.starter_pack_contents or "currency bundle"),
			}, function()
				request("prompt_product", "starter_pack")
			end)
		end)
	end

	-- Currency bundles
	local bundles = casual.currency_bundles or {}
	if #bundles > 0 then
		local s = section(frame, "💰 Currency Bundles")
		for _, bundle in bundles do
			local kind = "bundle_" .. string.lower(bundle.name)
			if productIds[kind] and productIds[kind] > 0 then
				local badge = bundle.badge and (" [" .. bundle.badge .. "]") or ""
				local row = label(s, ("%s%s — %d currency for %d R$"):format(
					bundle.name, badge, bundle.amount, bundle.price), 15, bundle.badge ~= nil)
				if bundle.badge then
					row.TextColor3 = Color3.fromRGB(120, 230, 120)
				end
				local buy = button(s, "Buy " .. bundle.name, Color3.fromRGB(80, 140, 220))
				buy.Activated:Connect(function()
					purchasePreview(bundle.name .. " Bundle — " .. bundle.price .. " R$", {
						bundle.amount .. " currency",
					}, function()
						request("prompt_product", kind)
					end)
				end)
				local gift = button(s, "Gift " .. bundle.name, Color3.fromRGB(150, 100, 200))
				gift.Activated:Connect(function()
					local box = Instance.new("TextBox")
					box.PlaceholderText = "Friend's username (this server)"
					box.Size = UDim2.new(1, -20, 0, 28)
					box.BackgroundColor3 = Color3.fromRGB(60, 60, 75)
					box.TextColor3 = Color3.fromRGB(255, 255, 255)
					box.TextSize = 14
					box.Font = Enum.Font.Gotham
					styled(box, 6)
					box.Parent = s
					box.FocusLost:Connect(function(enter)
						local name = box.Text
						box:Destroy()
						if enter and name ~= "" then
							purchasePreview("Gift to " .. name, {
								bundle.amount .. " currency → " .. name,
							}, function()
								request("gift_bundle", kind, name)
							end)
						end
					end)
					box:CaptureFocus()
				end)
			end
		end
	end

	-- Season pass with transparent value math
	if productIds.season_pass and productIds.season_pass > 0 then
		local s = section(frame, "🏆 Season Pass — " .. tostring(mid.season_pass_price or 499) .. " R$")
		local perks = mid.season_pass_perks or {}
		for _, perk in perks do
			label(s, "• " .. tostring(perk), 14, false)
		end
		-- Honest value math: 30 days of 2x + cosmetic + boosted dailies
		label(s, "Contents bought separately would cost 1500+ R$ — pass price 499 R$", 13, true)
		if state.SeasonPassActive then
			local daysLeft = math.max(0, math.floor((state.SeasonPassExpiry - os.time()) / 86400))
			label(s, ("Active — %d days left"):format(daysLeft), 14, false)
		else
			button(s, "View Pass", Color3.fromRGB(80, 140, 220)).Activated:Connect(function()
				local lines = {}
				for _, perk in perks do
					table.insert(lines, tostring(perk))
				end
				purchasePreview("Season Pass — 30 days", lines, function()
					request("prompt_product", "season_pass")
				end)
			end)
		end
	end

	-- VIP
	if productIds.vip_pass and productIds.vip_pass > 0 then
		local s = section(frame, "👑 VIP — " .. tostring(mid.vip_pass_price or 999) .. " R$ (permanent)")
		for _, perk in mid.vip_pass_perks or {} do
			label(s, "• " .. tostring(perk), 14, false)
		end
		label(s, "• " .. tostring(mid.vip_exclusive_feature or "VIP area"), 14, false)
		if owned["__vip"] then
			label(s, "Owned ✓", 14, false)
		else
			button(s, "View VIP", Color3.fromRGB(220, 180, 60)).Activated:Connect(function()
				local lines = { "1.5x permanent earnings", "VIP name tag" }
				purchasePreview("VIP Pass — permanent", lines, function()
					request("prompt_product", "vip_pass")
				end)
			end)
		end
	end

	-- Limited items with live stock
	local limited = (whale.limited_items or {}) :: { any }
	if #limited > 0 then
		local s = section(frame, "💎 Limited Edition")
		for index, item in state.LimitedView or limited do
			local name = item.name
			local remaining = item.remaining
			local kind = "limited_" .. index
			if owned[name] then
				label(s, ("%s — Owned ✓"):format(name), 15, false)
			elseif remaining ~= nil and remaining <= 0 then
				local l = label(s, ("%s — SOLD OUT"):format(name), 15, true)
				l.TextColor3 = Color3.fromRGB(220, 90, 90)
			else
				label(s, ("%s — %d R$ (%s remaining)"):format(
					name, item.price, tostring(remaining or "?")), 15, false)
				if productIds[kind] and productIds[kind] > 0 then
					button(s, "View", Color3.fromRGB(160, 80, 220)).Activated:Connect(function()
						purchasePreview(name .. " — " .. item.price .. " R$", {
							name .. " (limited: once sold out, gone forever)",
						}, function()
							request("prompt_product", kind)
						end)
					end)
				end
			end
		end
	end

	-- Founders pack with public counter
	if productIds.founders_pack and productIds.founders_pack > 0 then
		local limit = whale.founders_pack_limit or 100
		local sold = state.FoundersSold or 0
		local s = section(frame, "🌟 Founders Pack — " .. tostring(whale.founders_pack_price or 4999) .. " R$")
		label(s, ("First %d players only — %d/%d claimed"):format(limit, sold, limit), 14, true)
		if (state.FoundersRank or 0) > 0 then
			label(s, ("You are Founder #%d ✓"):format(state.FoundersRank), 14, false)
		elseif sold < limit then
			button(s, "View", Color3.fromRGB(230, 160, 60)).Activated:Connect(function()
				purchasePreview("Founders Pack", {
					"Permanent 2x earnings",
					"Founders aura visible to everyone",
					"Permanent Founders leaderboard spot",
				}, function()
					request("prompt_product", "founders_pack")
				end)
			end)
		else
			local l = label(s, "SOLD OUT", 15, true)
			l.TextColor3 = Color3.fromRGB(220, 90, 90)
		end
	end

	-- Custom name tag
	if productIds.custom_nametag and productIds.custom_nametag > 0 then
		local s = section(frame, "✏️ Custom Name Tag — " .. tostring(whale.custom_nametag_price or 2499) .. " R$")
		if owned["__nametag"] then
			label(s, "Owned — set your tag:", 14, false)
			local box = Instance.new("TextBox")
			box.PlaceholderText = "Tag text (filtered)"
			box.Size = UDim2.new(1, -20, 0, 28)
			box.BackgroundColor3 = Color3.fromRGB(60, 60, 75)
			box.TextColor3 = Color3.fromRGB(255, 255, 255)
			box.TextSize = 14
			box.Font = Enum.Font.Gotham
			styled(box, 6)
			box.Parent = s
			box.FocusLost:Connect(function(enter)
				if enter and box.Text ~= "" then
					request("set_nametag", box.Text, "#FFD750")
				end
			end)
		else
			button(s, "View", Color3.fromRGB(100, 180, 220)).Activated:Connect(function()
				purchasePreview("Custom Name Tag", {
					"Colored name tag above your character, visible to everyone",
					"Pure style — no gameplay impact",
				}, function()
					request("prompt_product", "custom_nametag")
				end)
			end)
		end
	end
end

-- Shop toggle button
local toggle = button(screenGui, "🛍️ Shop", Color3.fromRGB(70, 110, 200))
toggle.AnchorPoint = Vector2.new(1, 1)
toggle.Position = UDim2.new(1, -10, 1, -10)
toggle.Activated:Connect(function()
	shopOpen = not shopOpen
	rebuildShop()
end)

-- ── wiring ──────────────────────────────────────────────────
task.spawn(function()
	local folder = ReplicatedStorage:WaitForChild("MonetizationRemotes", 15)
	if not folder then
		return
	end
	local stateRemote = folder:WaitForChild("MonetizationState", 10)
	requestRemote = folder:WaitForChild("MonetizationRequest", 10) :: RemoteEvent
	local announceRemote = folder:WaitForChild("MonetizationAnnounce", 10)

	if stateRemote and stateRemote:IsA("RemoteEvent") then
		stateRemote.OnClientEvent:Connect(function(newState: { [string]: any })
			-- Server sends limited stock inside the state payload
			newState.LimitedView = nil
			local config = newState.Config or {}
			local whale = config.whale_tier or {}
			local view = {}
			for index, item in (whale.limited_items or {}) :: { any } do
				view[index] = item
			end
			-- Merge live remaining counts when provided
			for _, live in (newState.Limited or {}) :: { any } do
				for index, item in view do
					if item.name == live.name then
						view[index] = live
					end
				end
			end
			newState.LimitedView = view
			state = newState
			rebuildShop()
		end)
	end
	if announceRemote and announceRemote:IsA("RemoteEvent") then
		announceRemote.OnClientEvent:Connect(function(payload: { [string]: any })
			if typeof(payload) == "table" and typeof(payload.text) == "string" then
				toast(payload.text, if payload.kind == "flash_sale" then 10 else 6)
				if payload.kind == "starter_offer" then
					shopOpen = true
					rebuildShop()
				end
			end
		end)
	end
end)
