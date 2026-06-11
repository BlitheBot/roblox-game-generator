--!strict
-- Central tuning config. All values customized per-game by LuauAgent.

local Config = {
	GameTitle = "{{GAME_TITLE}}",
	CurrencyName = "{{CURRENCY_NAME}}",
	ProductName = "{{PRODUCT_NAME}}",
	ThemeDescriptor = "{{THEME_DESCRIPTOR}}",
	PrestigeName = "{{PRESTIGE_NAME}}",

	-- Economy (numeric knobs are LiveOps-tunable via concept.balance)
	BaseDropValue = {{BASE_DROP_VALUE}},
	DropIntervalSeconds = {{DROP_INTERVAL_SECONDS}},
	StartingCurrency = {{STARTING_CURRENCY}},

	-- Upgrades: each level multiplies drop value and reduces interval
	Upgrades = {
		{ Name = "Faster {{PRODUCT_NAME}}s", BaseCost = 50, CostMultiplier = 1.6, Effect = "interval", EffectValue = 0.92, MaxLevel = 20 },
		{ Name = "Better {{PRODUCT_NAME}}s", BaseCost = 100, CostMultiplier = 1.8, Effect = "value", EffectValue = 1.25, MaxLevel = 25 },
		{ Name = "Extra Dropper", BaseCost = 500, CostMultiplier = 2.5, Effect = "dropper", EffectValue = 1, MaxLevel = 8 },
	},

	-- Prestige
	PrestigeRequirement = 100000, -- currency needed to prestige
	PrestigeMultiplierPerLevel = 0.5, -- +50% income per prestige level

	-- Monetization (filled from concept JSON by LuauAgent)
	GamePasses = {{GAME_PASSES_LUA}},
	ShopItems = {{SHOP_ITEMS_LUA}},
	VipServerEnabled = {{VIP_SERVER_ENABLED}},

	-- Resolved Roblox Toolbox asset ids for decoration models
	ToolboxAssetIds = {{TOOLBOX_ASSET_IDS_LUA}},

	-- Plots
	MaxPlots = 8,
	PlotSize = Vector3.new(64, 1, 64),
}

return Config
