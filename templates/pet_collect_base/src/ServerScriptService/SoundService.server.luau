-- SoundService — sets up looping background ambience so a generated game is
-- never silent. pet_collect: happy, cheerful music.
--
-- The track id is configurable (Config.AmbientSoundId, else AMBIENT_SOUND_ID
-- below). It is left at 0 by default: Roblox audio privacy (post-2022) means
-- an arbitrary audio id will NOT play unless it is permissioned to this
-- experience, so we wire the looping Sound object up and play it only when a
-- real, permissioned id has been assigned — rather than hardcode an id that
-- would silently fail.
local SoundService = game:GetService("SoundService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local GENRE = "pet_collect (happy cheerful music)"
local AMBIENT_SOUND_ID = 0
local AMBIENT_VOLUME = 0.3

local Config
local okCfg, mod = pcall(function()
	return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
end)
if okCfg then
	Config = mod
end

local soundId = AMBIENT_SOUND_ID
if Config and tonumber(Config.AmbientSoundId) then
	soundId = tonumber(Config.AmbientSoundId)
end

local ambient = Instance.new("Sound")
ambient.Name = "AmbientMusic"
ambient.Looped = true
ambient.Volume = AMBIENT_VOLUME
ambient.Parent = SoundService

if soundId and soundId > 0 then
	ambient.SoundId = "rbxassetid://" .. tostring(soundId)
	ambient:Play()
else
	warn(("[SoundService] No ambient audio id set for %s; staying silent until a permissioned audio asset is assigned to Config.AmbientSoundId."):format(GENRE))
end
