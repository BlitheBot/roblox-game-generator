--[[
	SoundConfig — single source of truth for every sound id in the game.

	Required by both SoundSystem.server and SoundClient so the id table never
	drifts between server and client.

	AUDIO REALITY (do not "fix" by pasting random catalog ids): since 2022 Roblox
	gates third-party audio behind a per-experience permission — an arbitrary id
	will silently NOT play unless it has been granted to this universe. The one
	exception is Roblox-OWNED audio (uploaded by Roblox itself), which is exempt
	and plays in any place. So:
	  * Sound EFFECTS below use Roblox-owned UI sound ids → they work everywhere.
	  * Ambient MUSIC is left at 0 and resolved at runtime from Config.AmbientSoundId
	    (a permissioned track the pipeline assigns) — playing a random music id
	    here would just fail silently, which is why the base SoundService already
	    refuses to. Everything funnels through resolve() so swapping a moderated id
	    is a one-line change.
--]]

local SoundConfig = {}

-- Roblox-owned UI sound ids (privacy-exempt, play in any experience).
local CLICK = 6042053997 -- short clean click / tap
local WHOOSH = 6042053626 -- panel open / transition whoosh
local CHIME = 4590662766 -- positive chime / confirm

-- Flat sounds, looked up by name.
SoundConfig.Sounds = {
	-- UI
	button_click = CLICK,
	button_hover = CLICK,
	screen_open = WHOOSH,
	screen_close = WHOOSH,
	tab_switch = CLICK,

	-- Economy
	coin_earn = CHIME,
	coin_earn_big = CHIME,
	purchase_success = CHIME,
	purchase_fail = CLICK,
	level_up = CHIME,
	prestige = CHIME,

	-- Rarity (case / egg reveals) — drama scales with tier
	rarity_common = CLICK,
	rarity_uncommon = CLICK,
	rarity_rare = WHOOSH,
	rarity_epic = WHOOSH,
	rarity_legendary = CHIME,
	rarity_mythic = CHIME,

	-- Feedback
	success = CHIME,
	error = CLICK,
	warning = CLICK,
	notification = WHOOSH,

	-- Ambient music: 0 → resolved from Config.AmbientSoundId at runtime (see note above)
	ambient_idle_tycoon = 0,
	ambient_pet_collect = 0,
	ambient_survival_horror = 0,
	ambient_incremental_sim = 0,
}

-- Genre-specific gameplay sounds, addressed as "genre.key" (e.g. "pet_collect.egg_hatch").
SoundConfig.Genre = {
	idle_tycoon = {
		machine_start = WHOOSH,
		conveyor_loop = WHOOSH,
		upgrade_buy = CHIME,
		plot_claim = CHIME,
	},
	pet_collect = {
		egg_shake = CLICK,
		egg_crack = WHOOSH,
		egg_hatch = CHIME,
		pet_equip = CLICK,
		trade_success = CHIME,
	},
	survival_horror = {
		monster_growl = WHOOSH,
		player_hurt = CLICK,
		door_creak = WHOOSH,
		heartbeat = CLICK,
		safe_room_enter = CHIME,
	},
	incremental_sim = {
		resource_tick = CLICK,
		sell_resources = CHIME,
		rebirth = CHIME,
		upgrade = CHIME,
	},
}

-- Resolve a flat name ("coin_earn") or a dotted genre name ("pet_collect.egg_hatch")
-- to an asset id, or nil if unknown.
function SoundConfig.resolve(name)
	if type(name) ~= "string" then
		return nil
	end
	local genre, key = string.match(name, "^([%w_]+)%.([%w_]+)$")
	if genre then
		local t = SoundConfig.Genre[genre]
		return t and t[key] or nil
	end
	return SoundConfig.Sounds[name]
end

return SoundConfig
