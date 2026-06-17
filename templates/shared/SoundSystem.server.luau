--[[
	SoundSystem (server) — persistence + server→client sound plumbing.

	Actual playback happens on clients (SoundClient) for zero-latency feedback
	and per-client volume; the server's jobs are:
	  * Persist each player's Music/SFX volume across sessions (DataStore), via
	    the Volume remote ("save" to store, "load" to fetch).
	  * Let any server script request a client sound through ServerStorage's
	    "PlayGameSound" BindableEvent — fired (player, soundName) or
	    (nil, soundName) to broadcast — which forwards to the PlaySound remote.

	NOTE: the original sketch tried to expose a module by assigning Script.Source
	at runtime; that is impossible outside a plugin, so cross-script access uses
	the BindableEvent contract the rest of this codebase already uses.
--]]

local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")
local Players = game:GetService("Players")

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local Volume = Remotes:WaitForChild("Volume") :: RemoteEvent
local PlaySound = Remotes:WaitForChild("PlaySound") :: RemoteEvent

local store = nil
pcall(function()
	store = DataStoreService:GetDataStore("VolumeSettings_v1")
end)

-- Cache so repeated "load"s in a session don't hammer the DataStore.
local cache: { [number]: { music: number, sfx: number } } = {}

local function clamp01(n: unknown): number?
	if typeof(n) ~= "number" then
		return nil
	end
	return math.clamp(n, 0, 1)
end

Volume.OnServerEvent:Connect(function(player: Player, kind: unknown, music: unknown, sfx: unknown)
	if kind == "save" then
		local m = clamp01(music)
		local s = clamp01(sfx)
		if not m or not s then
			return
		end
		cache[player.UserId] = { music = m, sfx = s }
		if store then
			pcall(function()
				store:SetAsync(tostring(player.UserId), { music = m, sfx = s })
			end)
		end
	elseif kind == "load" then
		local settings = cache[player.UserId]
		if not settings and store then
			local ok, saved = pcall(function()
				return store:GetAsync(tostring(player.UserId))
			end)
			if ok and typeof(saved) == "table" then
				settings = {
					music = clamp01(saved.music) or 0.5,
					sfx = clamp01(saved.sfx) or 0.5,
				}
				cache[player.UserId] = settings
			end
		end
		settings = settings or { music = 0.5, sfx = 0.5 }
		Volume:FireClient(player, "settings", settings.music, settings.sfx)
	end
end)

Players.PlayerRemoving:Connect(function(player)
	cache[player.UserId] = nil
end)

-- Server-side sound request contract for gameplay scripts that prefer a
-- BindableEvent over firing the remote directly. Fire (player, name) to play for
-- one player, or (nil, name) to broadcast.
local playGameSound = Instance.new("BindableEvent")
playGameSound.Name = "PlayGameSound"
playGameSound.Parent = ServerStorage
playGameSound.Event:Connect(function(player: Player?, soundName: string)
	if typeof(soundName) ~= "string" then
		return
	end
	if player then
		PlaySound:FireClient(player, soundName)
	else
		PlaySound:FireAllClients(soundName)
	end
end)
