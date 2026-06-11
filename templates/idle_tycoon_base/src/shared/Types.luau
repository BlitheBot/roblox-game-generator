--!strict
-- Shared type definitions for client/server state replication.

export type UpgradeState = {
	Level: number,
}

export type PlayerState = {
	Currency: number,
	PrestigeLevel: number,
	Upgrades: { [string]: UpgradeState },
	OwnedPasses: { [number]: boolean },
	TotalEarned: number,
}

export type StatePayload = {
	Currency: number,
	PrestigeLevel: number,
	Upgrades: { [string]: UpgradeState },
	CanPrestige: boolean,
}

return {}
