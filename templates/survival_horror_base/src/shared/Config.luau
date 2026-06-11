--!strict
local Config = {
	GameTitle = "{{GAME_TITLE}}",
	CurrencyName = "{{CURRENCY_NAME}}",
	MonsterName = "{{MONSTER_NAME}}",

	-- Round flow
	LobbySeconds = 20,
	VoteSeconds = 10,
	RoundSeconds = {{ROUND_SECONDS}},
	MinPlayers = 1,

	-- Rewards (numeric knobs are LiveOps-tunable via concept.balance)
	SurvivalReward = {{SURVIVAL_REWARD}},
	EliminationPenaltyKeepFraction = 0.4, -- eliminated players keep 40% of reward

	-- Monster tuning
	MonsterSpeed = 22,
	MonsterAttackRange = 6,

	-- Map list is LiveOps-extendable via concept.maps (content drops)
	Maps = {{MAPS_LUA}},

	GamePasses = {{GAME_PASSES_LUA}},
	ShopItems = {{SHOP_ITEMS_LUA}},
	VipServerEnabled = {{VIP_SERVER_ENABLED}},
	ToolboxAssetIds = {{TOOLBOX_ASSET_IDS_LUA}},
}

return Config
