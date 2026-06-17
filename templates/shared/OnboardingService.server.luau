--[[
	OnboardingService — first-time player guidance (server authority).

	Shows only for first-time players (tracked in a DataStore). Sends the genre's
	step list to the client, which drives the on-screen guide. On completion it
	grants the bonus reward server-side (never trusting the client for the amount)
	through the universal ServerStorage.GrantCurrency contract, marks the player
	done, and fires a reward notification + success sound.

	Design: show-don't-tell, ≤5 steps, never blocks gameplay (the client also
	auto-advances on a timeout so a player is never stuck on a step that this
	template can't emit an event for).
--]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")
local DataStoreService = game:GetService("DataStoreService")

local MECHANIC = "{{MECHANIC_TAG}}"

local OnboardingStore = nil
pcall(function()
	OnboardingStore = DataStoreService:GetDataStore("{{GAME_TITLE}}_Onboarding_v1")
end)

local ONBOARDING_STEPS = {
	idle_tycoon = {
		{ id = "claim_plot", title = "Claim Your First Plot!", description = "Walk up to a plot and claim it to start producing.", arrow_target = "ShopArea", complete_event = "PlotClaimed", reward = 0 },
		{ id = "collect_coins", title = "Collect Your Coins!", description = "Your plot is producing! Coins pile up automatically.", arrow_target = nil, complete_event = "CoinsCollected", reward = 0 },
		{ id = "buy_upgrade", title = "Buy an Upgrade!", description = "Open the shop and buy your first upgrade to earn more.", arrow_target = "ShopArea", complete_event = "UpgradePurchased", reward = 0 },
		{ id = "complete", title = "You're Ready!", description = "Keep upgrading and expanding to build your empire!", arrow_target = nil, complete_event = nil, reward = 500 },
	},
	pet_collect = {
		{ id = "open_egg", title = "Hatch Your First Pet!", description = "Head to the egg area and open your starter egg!", arrow_target = "EggArea", complete_event = "EggOpened", reward = 0 },
		{ id = "equip_pet", title = "Equip Your Pet!", description = "Open your inventory and equip the pet you hatched.", arrow_target = nil, complete_event = "PetEquipped", reward = 0 },
		{ id = "earn_coins", title = "Earn Coins!", description = "Your pet earns coins automatically. Watch it grow!", arrow_target = nil, complete_event = "CoinsEarned", reward = 0 },
		{ id = "open_second_egg", title = "Hatch Another Pet!", description = "Use your coins to open another egg in the shop.", arrow_target = "ShopArea", complete_event = "EggOpened", reward = 250 },
		{ id = "complete", title = "You're a Collector!", description = "Keep hatching to find rarer pets and trade with others!", arrow_target = nil, complete_event = nil, reward = 500 },
	},
	survival_horror = {
		{ id = "join_round", title = "Get Ready!", description = "A round is starting soon — get into position!", arrow_target = "SafeRoom", complete_event = "RoundJoined", reward = 0 },
		{ id = "survive", title = "Survive!", description = "Hide from the monster and survive as long as you can.", arrow_target = nil, complete_event = "RoundCompleted", reward = 0 },
		{ id = "earn_coins", title = "Earn Coins!", description = "You earn coins for surviving. Spend them to get stronger!", arrow_target = "ShopArea", complete_event = nil, reward = 200 },
	},
	incremental_sim = {
		{ id = "first_resource", title = "Gather Resources!", description = "Your machines generate resources automatically.", arrow_target = nil, complete_event = "FirstResourceCollected", reward = 0 },
		{ id = "sell_resource", title = "Sell Your Resources!", description = "Go to the sell area and turn resources into coins.", arrow_target = "SellArea", complete_event = "ResourcesSold", reward = 0 },
		{ id = "buy_upgrade", title = "Buy an Upgrade!", description = "Upgrades make you collect faster. Buy your first!", arrow_target = "UpgradeStation", complete_event = "UpgradePurchased", reward = 0 },
		{ id = "complete", title = "You're Growing!", description = "Keep upgrading until you can rebirth for a big bonus!", arrow_target = nil, complete_event = nil, reward = 500 },
	},
}

local steps = ONBOARDING_STEPS[MECHANIC] or ONBOARDING_STEPS.idle_tycoon

local function totalReward(): number
	local total = 0
	for _, step in ipairs(steps) do
		total += step.reward or 0
	end
	return total
end

local function isNewPlayer(userId: number): boolean
	if not OnboardingStore then
		return true -- no DataStore (Studio/dry run) → treat as new so onboarding shows
	end
	local ok, result = pcall(function()
		return OnboardingStore:GetAsync(tostring(userId))
	end)
	return ok and result == nil
end

local function markComplete(userId: number)
	if not OnboardingStore then
		return
	end
	pcall(function()
		OnboardingStore:SetAsync(tostring(userId), { completedAt = os.time(), version = 1 })
	end)
end

-- Players we have actually started onboarding for this session — a client may
-- only claim the reward if we offered it (anti-farm).
local active: { [number]: boolean } = {}

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local StartOnboarding = Remotes:WaitForChild("StartOnboarding") :: RemoteEvent
local CompleteOnboarding = Remotes:WaitForChild("CompleteOnboarding") :: RemoteEvent
local Notification = Remotes:WaitForChild("Notification") :: RemoteEvent
local PlaySound = Remotes:FindFirstChild("PlaySound")

local function startOnboarding(player: Player)
	if not isNewPlayer(player.UserId) then
		return
	end
	if not player.Character then
		player.CharacterAdded:Wait()
	end
	task.wait(2) -- let the loading screen finish
	active[player.UserId] = true
	StartOnboarding:FireClient(player, steps)
end

local function grantCurrency(player: Player, amount: number)
	local hook = ServerStorage:WaitForChild("GrantCurrency", 10)
	if hook and hook:IsA("BindableEvent") then
		hook:Fire(player, amount)
	end
end

CompleteOnboarding.OnServerEvent:Connect(function(player: Player)
	if not active[player.UserId] then
		return -- never offered, or already claimed → no reward farming
	end
	active[player.UserId] = nil

	local reward = totalReward()
	if reward > 0 then
		grantCurrency(player, reward)
		Notification:FireClient(
			player,
			"Tutorial Complete!",
			"You earned " .. tostring(reward) .. " bonus coins!",
			"reward"
		)
	end
	if PlaySound and PlaySound:IsA("RemoteEvent") then
		PlaySound:FireClient(player, "success")
	end
	markComplete(player.UserId)
end)

Players.PlayerAdded:Connect(function(player)
	task.spawn(startOnboarding, player)
end)
Players.PlayerRemoving:Connect(function(player)
	active[player.UserId] = nil
end)
