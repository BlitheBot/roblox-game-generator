--!strict
-- MonetizationService: drop-in three-tier monetization layer.
-- Config is baked at build time via {{MONETIZATION_LUA}} (ConceptGenerator
-- three-tier schema). Self-contained DataStores + runtime remotes; optional
-- template contracts (all degrade gracefully when absent):
--   * ServerStorage.GrantCurrency  BindableEvent  — award soft currency
--   * ServerStorage.TrySpendCurrency BindableFunction — spend soft currency
--   * player attribute "MonetizationMultiplier" — income scripts multiply
--     by it (VIP 1.5x, season pass 2x, founders 2x, stacking)
--
-- Robux purchases need platform-created products/passes; their ids arrive
-- via config (0 = not yet assigned → that purchase is hidden client-side).
-- Note: no countdown timers and no purchase-streak rewards by design —
-- this layer avoids pressure mechanics aimed at young players.

local DataStoreService = game:GetService("DataStoreService")
local MarketplaceService = game:GetService("MarketplaceService")
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")
local TextService = game:GetService("TextService")

local MONETIZATION = {{MONETIZATION_LUA}}

local STARTER_OFFER_AFTER_SECONDS = 180 -- shown once, no countdown pressure
local DAILY_DEAL_DISCOUNT = 0.4
local FLASH_SALE_DISCOUNT = 0.5
local FLASH_SALE_HOURS = 2
local SEASON_PASS_DAYS = 30
local SEASON_TRACK_TIERS = 20
local SEASON_TIER_MINUTES = 15 -- one free-track tier per 15 min played
local FIRST_PURCHASE_BONUS = 1.1 -- hidden 10% thank-you on first bundle

local playerStore = nil
pcall(function()
	playerStore = DataStoreService:GetDataStore("MonetizationData_v1")
end)
local globalStore = nil
pcall(function()
	globalStore = DataStoreService:GetDataStore("MonetizationGlobal_v1")
end)

-- ── runtime remotes ─────────────────────────────────────────
local remotes = Instance.new("Folder")
remotes.Name = "MonetizationRemotes"
remotes.Parent = ReplicatedStorage
local stateRemote = Instance.new("RemoteEvent")
stateRemote.Name = "MonetizationState"
stateRemote.Parent = remotes
local requestRemote = Instance.new("RemoteEvent")
requestRemote.Name = "MonetizationRequest"
requestRemote.Parent = remotes
local announceRemote = Instance.new("RemoteEvent")
announceRemote.Name = "MonetizationAnnounce"
announceRemote.Parent = remotes

-- ── per-player session state ────────────────────────────────
type PlayerRecord = {
	OwnedItems: { [string]: boolean },
	SeasonPassExpiry: number,
	SeasonTiersClaimed: number,
	PlayMinutes: number,
	FirstPurchaseDone: boolean,
	StarterPackSeen: boolean,
	StarterPackOwned: boolean,
	NameTag: { Text: string, Color: string }?,
	FoundersRank: number, -- 0 = not a founder
}

local records: { [number]: PlayerRecord } = {}
local joinClock: { [number]: number } = {}
-- Same-server gift intents: buyerUserId → { target: number, item: string }
local giftIntents: { [number]: { target: number, item: string } } = {}
-- Pending bundle/starter purchase prompts: userId → kind
local productIntents: { [number]: string } = {}

local function defaultRecord(): PlayerRecord
	return {
		OwnedItems = {},
		SeasonPassExpiry = 0,
		SeasonTiersClaimed = 0,
		PlayMinutes = 0,
		FirstPurchaseDone = false,
		StarterPackSeen = false,
		StarterPackOwned = false,
		NameTag = nil,
		FoundersRank = 0,
	}
end

local function loadRecord(userId: number): PlayerRecord
	local record = defaultRecord()
	if playerStore then
		local ok, saved = pcall(function()
			return (playerStore :: DataStore):GetAsync(tostring(userId))
		end)
		if ok and typeof(saved) == "table" then
			for key, value in saved :: { [string]: any } do
				(record :: any)[key] = value
			end
		end
	end
	return record
end

local function saveRecord(userId: number)
	local record = records[userId]
	if record and playerStore then
		pcall(function()
			(playerStore :: DataStore):SetAsync(tostring(userId), record)
		end)
	end
end

-- ── soft-currency contracts ─────────────────────────────────
local function grantCurrency(player: Player, amount: number)
	local event = ServerStorage:FindFirstChild("GrantCurrency")
	if event and event:IsA("BindableEvent") then
		event:Fire(player, amount)
	end
end

local function trySpendCurrency(player: Player, amount: number): boolean
	local fn = ServerStorage:FindFirstChild("TrySpendCurrency")
	if fn and fn:IsA("BindableFunction") then
		local ok, result = pcall(function()
			return fn:Invoke(player, amount)
		end)
		return ok and result == true
	end
	return false
end

-- ── multipliers / status effects ────────────────────────────
local function seasonPassActive(record: PlayerRecord): boolean
	return record.SeasonPassExpiry > os.time()
end

local function refreshMultiplier(player: Player)
	local record = records[player.UserId]
	if not record then
		return
	end
	local mult = 1
	if record.OwnedItems["__vip"] then
		mult *= 1.5
	end
	if seasonPassActive(record) then
		mult *= 2
	end
	if record.FoundersRank > 0 then
		mult *= 2
	end
	player:SetAttribute("MonetizationMultiplier", mult)
	player:SetAttribute("VIP", record.OwnedItems["__vip"] == true)
end

local function applyCharacterEffects(player: Player)
	local record = records[player.UserId]
	local character = player.Character
	if not record or not character then
		return
	end
	local head = character:FindFirstChild("Head")
	if not head or not head:IsA("BasePart") then
		return
	end
	local existing = head:FindFirstChild("MonetizationTag")
	if existing then
		existing:Destroy()
	end
	local tagText = nil
	local tagColor = Color3.fromRGB(255, 215, 80)
	if record.NameTag then
		tagText = record.NameTag.Text
		local ok, parsed = pcall(Color3.fromHex, record.NameTag.Color)
		if ok then
			tagColor = parsed
		end
	elseif record.OwnedItems["__vip"] then
		tagText = "VIP"
	end
	if tagText then
		local billboard = Instance.new("BillboardGui")
		billboard.Name = "MonetizationTag"
		billboard.Size = UDim2.new(0, 200, 0, 40)
		billboard.StudsOffset = Vector3.new(0, 2.4, 0)
		billboard.AlwaysOnTop = true
		local label = Instance.new("TextLabel")
		label.BackgroundTransparency = 1
		label.Size = UDim2.new(1, 0, 1, 0)
		label.Font = Enum.Font.GothamBold
		label.TextScaled = true
		label.TextColor3 = tagColor
		label.TextStrokeTransparency = 0.2
		label.Text = tagText
		label.Parent = billboard
		billboard.Parent = head
	end
	-- Founders particle effect, visible to everyone
	if record.FoundersRank > 0 then
		local root = character:FindFirstChild("HumanoidRootPart")
		if root and root:IsA("BasePart") and not root:FindFirstChild("FoundersAura") then
			local sparkles = Instance.new("Sparkles")
			sparkles.Name = "FoundersAura"
			sparkles.SparkleColor = Color3.fromRGB(255, 200, 60)
			sparkles.Parent = root
		end
	end
end

-- ── daily deal + flash sale (deterministic across servers) ──
local function utcDay(): number
	return math.floor(os.time() / 86400)
end

local function dailyDeal(): { name: string, price: number, original: number }?
	local pool = MONETIZATION.casual_tier and MONETIZATION.casual_tier.daily_deal_pool
	if not pool or #pool == 0 then
		return nil
	end
	local pick = pool[(utcDay() % #pool) + 1]
	for _, item in MONETIZATION.shop_items or {} do
		if item.name == pick then
			local original = item.price
			return {
				name = pick,
				price = math.max(1, math.floor(original * (1 - DAILY_DEAL_DISCOUNT))),
				original = original,
			}
		end
	end
	return nil
end

local function flashSale(): { name: string, price: number, original: number, endsAt: number }?
	-- Deterministic schedule: hash the day; ~3 sale days a week, a 2h
	-- window at a day-specific hour. Every server agrees without
	-- cross-server messaging.
	local day = utcDay()
	local seed = (day * 2654435761) % 7
	if seed > 2 then
		return nil
	end
	local startHour = (day * 40503) % 22
	local nowHour = (os.time() % 86400) / 3600
	if nowHour < startHour or nowHour >= startHour + FLASH_SALE_HOURS then
		return nil
	end
	local items = MONETIZATION.shop_items or {}
	if #items == 0 then
		return nil
	end
	local item = items[(day % #items) + 1]
	local dayStart = day * 86400
	return {
		name = item.name,
		price = math.max(1, math.floor(item.price * (1 - FLASH_SALE_DISCOUNT))),
		original = item.price,
		endsAt = dayStart + (startHour + FLASH_SALE_HOURS) * 3600,
	}
end

local lastAnnouncedSaleDay = -1
task.spawn(function()
	while true do
		local sale = flashSale()
		if sale and lastAnnouncedSaleDay ~= utcDay() then
			lastAnnouncedSaleDay = utcDay()
			announceRemote:FireAllClients({
				kind = "flash_sale",
				text = ("[FLASH SALE] 50%% off %s — %d hours only!"):format(
					sale.name, FLASH_SALE_HOURS
				),
				sale = sale,
			})
		end
		task.wait(60)
	end
end)

-- ── limited stock (global counters via UpdateAsync) ─────────
local function stockKey(itemName: string): string
	return "stock_" .. itemName
end

local function remainingStock(itemName: string, initialStock: number): number
	if not globalStore then
		return initialStock
	end
	local sold = 0
	pcall(function()
		sold = (globalStore :: DataStore):GetAsync(stockKey(itemName)) or 0
	end)
	return math.max(0, initialStock - sold)
end

local function tryConsumeStock(itemName: string, initialStock: number): boolean
	if not globalStore then
		return false
	end
	local consumed = false
	pcall(function()
		(globalStore :: DataStore):UpdateAsync(stockKey(itemName), function(sold)
			sold = sold or 0
			if sold >= initialStock then
				return sold -- sold out: leave unchanged
			end
			consumed = true
			return sold + 1
		end)
	end)
	return consumed
end

local function tryClaimFoundersRank(): number
	if not globalStore then
		return 0
	end
	local limit = (MONETIZATION.whale_tier and MONETIZATION.whale_tier.founders_pack_limit) or 100
	local rank = 0
	pcall(function()
		(globalStore :: DataStore):UpdateAsync("founders_count", function(count)
			count = count or 0
			if count >= limit then
				return count
			end
			rank = count + 1
			return count + 1
		end)
	end)
	return rank
end

-- ── state replication ───────────────────────────────────────
local function pushState(player: Player)
	local record = records[player.UserId]
	if not record then
		return
	end
	local limitedView = {}
	for _, item in (MONETIZATION.whale_tier and MONETIZATION.whale_tier.limited_items) or {} do
		table.insert(limitedView, {
			name = item.name,
			price = item.price,
			remaining = remainingStock(item.name, item.stock),
		})
	end
	local foundersSold = 0
	if globalStore then
		pcall(function()
			foundersSold = (globalStore :: DataStore):GetAsync("founders_count") or 0
		end)
	end
	stateRemote:FireClient(player, {
		Config = MONETIZATION,
		Limited = limitedView,
		Owned = record.OwnedItems,
		SeasonPassActive = seasonPassActive(record),
		SeasonPassExpiry = record.SeasonPassExpiry,
		SeasonTiersClaimed = record.SeasonTiersClaimed,
		PlayMinutes = record.PlayMinutes,
		FoundersRank = record.FoundersRank,
		FoundersSold = foundersSold,
		DailyDeal = dailyDeal(),
		FlashSale = flashSale(),
		StarterPackOwned = record.StarterPackOwned,
	})
end

-- ── season pass free track (rewards play time) ──────────────
local function tickSeasonTrack(player: Player)
	local record = records[player.UserId]
	if not record then
		return
	end
	record.PlayMinutes += 1
	local earnedTiers = math.min(SEASON_TRACK_TIERS, math.floor(record.PlayMinutes / SEASON_TIER_MINUTES))
	while record.SeasonTiersClaimed < earnedTiers do
		record.SeasonTiersClaimed += 1
		local reward = 100 * record.SeasonTiersClaimed
		if seasonPassActive(record) then
			reward *= 2
		end
		grantCurrency(player, reward)
		announceRemote:FireClient(player, {
			kind = "tier_up",
			text = ("Reward track tier %d reached — +%d currency!"):format(
				record.SeasonTiersClaimed, reward
			),
		})
	end
end

-- ── purchase handling (soft currency) ───────────────────────
local function buyShopItem(player: Player, itemName: string)
	local record = records[player.UserId]
	if not record or record.OwnedItems[itemName] then
		return
	end
	local price: number? = nil
	for _, item in MONETIZATION.shop_items or {} do
		if item.name == itemName then
			price = item.price
		end
	end
	if price == nil then
		return
	end
	local deal = dailyDeal()
	if deal and deal.name == itemName then
		price = deal.price
	end
	local sale = flashSale()
	if sale and sale.name == itemName then
		price = math.min(price :: number, sale.price)
	end
	if trySpendCurrency(player, price :: number) then
		record.OwnedItems[itemName] = true
		saveRecord(player.UserId)
		pushState(player)
	end
end

-- ── Robux receipts ──────────────────────────────────────────
local function productIds(): { [string]: number }
	return (MONETIZATION.product_ids or {}) :: { [string]: number }
end

local function bundleAmount(bundleName: string): number
	for _, bundle in (MONETIZATION.casual_tier and MONETIZATION.casual_tier.currency_bundles) or {} do
		if bundle.name == bundleName then
			return bundle.amount
		end
	end
	return 0
end

MarketplaceService.ProcessReceipt = function(receiptInfo)
	local player = Players:GetPlayerByUserId(receiptInfo.PlayerId)
	if not player then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end
	local record = records[player.UserId]
	if not record then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	local kind = nil
	for name, id in productIds() do
		if id == receiptInfo.ProductId then
			kind = name
		end
	end
	if kind == nil then
		return Enum.ProductPurchaseDecision.NotProcessedYet
	end

	if kind == "bundle_small" or kind == "bundle_medium" or kind == "bundle_large" then
		local bundleName = kind:sub(8):gsub("^%l", string.upper)
		local amount = bundleAmount(bundleName)
		if amount <= 0 then
			return Enum.ProductPurchaseDecision.NotProcessedYet
		end
		-- First Purchase Guarantee: quiet 10% bonus on a first bundle
		if not record.FirstPurchaseDone then
			amount = math.floor(amount * FIRST_PURCHASE_BONUS)
			record.FirstPurchaseDone = true
		end
		local intent = giftIntents[player.UserId]
		if intent then
			local target = Players:GetPlayerByUserId(intent.target)
			giftIntents[player.UserId] = nil
			if target then
				grantCurrency(target, amount)
				announceRemote:FireClient(target, {
					kind = "gift",
					text = ("%s sent you a gift: +%d currency!"):format(player.Name, amount),
				})
			else
				grantCurrency(player, amount) -- target left: keep it yourself
			end
		else
			grantCurrency(player, amount)
		end
	elseif kind == "starter_pack" then
		if record.StarterPackOwned then
			return Enum.ProductPurchaseDecision.PurchaseGranted
		end
		record.StarterPackOwned = true
		record.FirstPurchaseDone = true
		grantCurrency(player, bundleAmount("Medium"))
	elseif kind == "season_pass" then
		local base = math.max(os.time(), record.SeasonPassExpiry)
		record.SeasonPassExpiry = base + SEASON_PASS_DAYS * 86400
		local cosmetic = MONETIZATION.mid_tier and MONETIZATION.mid_tier.season_pass_exclusive_cosmetic
		if cosmetic then
			record.OwnedItems[cosmetic] = true
		end
	elseif kind == "vip_pass" then
		record.OwnedItems["__vip"] = true
	elseif kind == "founders_pack" then
		local rank = tryClaimFoundersRank()
		if rank == 0 then
			-- Sold out between prompt and receipt: never grant, Roblox
			-- refunds an unprocessed receipt
			return Enum.ProductPurchaseDecision.NotProcessedYet
		end
		record.FoundersRank = rank
	elseif kind == "custom_nametag" then
		record.OwnedItems["__nametag"] = true
	else
		-- limited_1/limited_2/limited_3
		local index = tonumber(kind:match("^limited_(%d)$") or "")
		local items = (MONETIZATION.whale_tier and MONETIZATION.whale_tier.limited_items) or {}
		local item = index and items[index]
		if not item then
			return Enum.ProductPurchaseDecision.NotProcessedYet
		end
		if record.OwnedItems[item.name] then
			return Enum.ProductPurchaseDecision.PurchaseGranted
		end
		if not tryConsumeStock(item.name, item.stock) then
			return Enum.ProductPurchaseDecision.NotProcessedYet -- sold out
		end
		record.OwnedItems[item.name] = true
	end

	saveRecord(player.UserId)
	refreshMultiplier(player)
	applyCharacterEffects(player)
	pushState(player)
	return Enum.ProductPurchaseDecision.PurchaseGranted
end

-- ── client requests ─────────────────────────────────────────
requestRemote.OnServerEvent:Connect(function(player: Player, action: unknown, arg1: unknown, arg2: unknown)
	local record = records[player.UserId]
	if not record or typeof(action) ~= "string" then
		return
	end

	if action == "buy_item" and typeof(arg1) == "string" then
		buyShopItem(player, arg1)
	elseif action == "prompt_product" and typeof(arg1) == "string" then
		local id = productIds()[arg1]
		if id and id > 0 then
			-- Stock gate before prompting a limited item
			local index = tonumber((arg1 :: string):match("^limited_(%d)$") or "")
			if index then
				local items = (MONETIZATION.whale_tier and MONETIZATION.whale_tier.limited_items) or {}
				local item = items[index]
				if not item or remainingStock(item.name, item.stock) <= 0 then
					return
				end
			end
			giftIntents[player.UserId] = nil
			pcall(function()
				MarketplaceService:PromptProductPurchase(player, id)
			end)
		end
	elseif action == "gift_bundle" and typeof(arg1) == "string" and typeof(arg2) == "string" then
		-- Gift a currency bundle to another player on this server
		local id = productIds()[arg1]
		if not id or id <= 0 or not arg1:match("^bundle_") then
			return
		end
		local target = Players:FindFirstChild(arg2 :: string)
		if not target or not target:IsA("Player") or target == player then
			return
		end
		giftIntents[player.UserId] = { target = target.UserId, item = arg1 }
		pcall(function()
			MarketplaceService:PromptProductPurchase(player, id)
		end)
	elseif action == "set_nametag" and typeof(arg1) == "string" and typeof(arg2) == "string" then
		if not record.OwnedItems["__nametag"] then
			return
		end
		local text = (arg1 :: string):sub(1, 20)
		-- Server-side filtering — custom text shown to others MUST pass
		-- TextService moderation
		local filtered = nil
		pcall(function()
			local result = TextService:FilterStringAsync(text, player.UserId)
			filtered = result:GetNonChatStringForBroadcastAsync()
		end)
		if not filtered or filtered == "" then
			return
		end
		local color = (arg2 :: string):match("^#%x%x%x%x%x%x$") and arg2 or "#FFD750"
		record.NameTag = { Text = filtered :: string, Color = color :: string }
		saveRecord(player.UserId)
		applyCharacterEffects(player)
		pushState(player)
	end
end)

-- ── lifecycle ───────────────────────────────────────────────
Players.PlayerAdded:Connect(function(player)
	records[player.UserId] = loadRecord(player.UserId)
	joinClock[player.UserId] = os.clock()
	refreshMultiplier(player)
	player.CharacterAdded:Connect(function()
		task.wait(0.5)
		applyCharacterEffects(player)
	end)
	applyCharacterEffects(player)
	pushState(player)

	local record = records[player.UserId]
	-- Starter pack: offered exactly once, a few minutes into the first
	-- session, with no countdown — it simply stays available until bought
	if not record.StarterPackSeen and not record.StarterPackOwned then
		task.delay(STARTER_OFFER_AFTER_SECONDS, function()
			local current = records[player.UserId]
			if not player.Parent or not current or current.StarterPackOwned then
				return
			end
			current.StarterPackSeen = true
			saveRecord(player.UserId)
			announceRemote:FireClient(player, {
				kind = "starter_offer",
				text = "A welcome gift is waiting in the shop!",
			})
		end)
	end

	task.spawn(function()
		while player.Parent do
			task.wait(60)
			if records[player.UserId] then
				tickSeasonTrack(player)
				refreshMultiplier(player) -- season pass may expire mid-session
			end
		end
	end)
end)

Players.PlayerRemoving:Connect(function(player)
	saveRecord(player.UserId)
	records[player.UserId] = nil
	joinClock[player.UserId] = nil
	giftIntents[player.UserId] = nil
	productIntents[player.UserId] = nil
end)

game:BindToClose(function()
	for _, player in Players:GetPlayers() do
		saveRecord(player.UserId)
	end
end)
