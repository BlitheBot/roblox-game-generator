--!strict
local Config = {
	GameTitle = "{{GAME_TITLE}}",
	CurrencyName = "{{CURRENCY_NAME}}",
	PetNoun = "{{PET_NOUN}}",
	EggNoun = "{{EGG_NOUN}}",

	-- Currency earned passively per second per equipped pet power
	-- (numeric knobs are LiveOps-tunable via concept.balance)
	BaseIncomePerSecond = {{BASE_INCOME_PER_SECOND}},
	StartingCurrency = {{PET_STARTING_CURRENCY}},
	MaxEquipped = 3,

	-- Rarity table: weight = relative hatch chance, power = income multiplier
	Rarities = {
		{ Name = "Common", Weight = 60, Power = 1, Color = Color3.fromRGB(180, 180, 180) },
		{ Name = "Uncommon", Weight = 25, Power = 3, Color = Color3.fromRGB(80, 200, 120) },
		{ Name = "Rare", Weight = 10, Power = 10, Color = Color3.fromRGB(80, 130, 240) },
		{ Name = "Epic", Weight = 4, Power = 40, Color = Color3.fromRGB(190, 80, 240) },
		{ Name = "Legendary", Weight = 1, Power = 200, Color = Color3.fromRGB(255, 180, 40) },
	},

	-- Pet name pools per rarity (customized per theme by LuauAgent)
	PetNames = {{PET_NAMES_LUA}},

	Eggs = {
		{ Name = "Basic {{EGG_NOUN}}", Cost = 100 },
		{ Name = "Golden {{EGG_NOUN}}", Cost = 2500, WeightBonus = 2 },
		{ Name = "Mythic {{EGG_NOUN}}", Cost = 50000, WeightBonus = 5 },
	},

	GamePasses = {{GAME_PASSES_LUA}},
	ShopItems = {{SHOP_ITEMS_LUA}},
	VipServerEnabled = {{VIP_SERVER_ENABLED}},
	ToolboxAssetIds = {{TOOLBOX_ASSET_IDS_LUA}},
}

return Config
