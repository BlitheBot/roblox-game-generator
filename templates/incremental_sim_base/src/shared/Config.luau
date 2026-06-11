--!strict
local Config = {
	GameTitle = "{{GAME_TITLE}}",
	CurrencyName = "{{CURRENCY_NAME}}",
	ResourceName = "{{RESOURCE_NAME}}",
	RebirthName = "{{REBIRTH_NAME}}",

	-- Resource grows every tick; selling converts to currency
	-- (numeric knobs are LiveOps-tunable via concept.balance)
	TickSeconds = 1.0,
	BaseGrowthPerTick = {{BASE_GROWTH_PER_TICK}},
	BaseSellValue = {{BASE_SELL_VALUE}},

	Upgrades = {
		{ Name = "Faster Growth", BaseCost = 25, CostMultiplier = 1.5, Effect = "growth", EffectValue = 1.3, MaxLevel = 30 },
		{ Name = "Better Prices", BaseCost = 60, CostMultiplier = 1.7, Effect = "sell", EffectValue = 1.25, MaxLevel = 30 },
	},

	RebirthRequirement = 50000,
	RebirthMultiplierPerLevel = 0.75,

	GamePasses = {{GAME_PASSES_LUA}},
	ShopItems = {{SHOP_ITEMS_LUA}},
	VipServerEnabled = {{VIP_SERVER_ENABLED}},
	ToolboxAssetIds = {{TOOLBOX_ASSET_IDS_LUA}},
}

return Config
