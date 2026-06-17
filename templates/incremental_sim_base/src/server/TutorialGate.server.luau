--!strict
-- TutorialGate (Bug 2) — decides whether the first-time tutorial should show.
--
-- The tutorial must appear for FIRST-TIME players only. The client can't read a
-- DataStore, so this server script is the source of truth: on join it checks a
-- per-game DataStore flag and publishes the "ShowTutorial" player attribute the
-- StarterGui Tutorial LocalScript reads. When the client reports completion via
-- the TutorialComplete RemoteEvent, the flag is persisted so the player never
-- sees it again. Fails open (shows the tutorial) if the DataStore is unreachable.

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local TutorialComplete = Remotes:WaitForChild("TutorialComplete") :: RemoteEvent

local store = DataStoreService:GetDataStore("Tutorial_" .. tostring(Config.GameTitle) .. "_v1")

local function hasSeenTutorial(player: Player): boolean
	local seen = false
	local ok = pcall(function()
		seen = store:GetAsync(tostring(player.UserId)) == true
	end)
	-- Fail open: if the DataStore is unreachable, treat as a new player so the
	-- tutorial still shows (it just may show again next session on persistent
	-- outages — acceptable vs. never teaching new players).
	if not ok then
		return false
	end
	return seen
end

local function onPlayerAdded(player: Player)
	player:SetAttribute("ShowTutorial", not hasSeenTutorial(player))
end

Players.PlayerAdded:Connect(onPlayerAdded)
for _, player in ipairs(Players:GetPlayers()) do
	onPlayerAdded(player)
end

TutorialComplete.OnServerEvent:Connect(function(player: Player)
	-- No client-supplied args to trust; guard the type anyway.
	if typeof(player) ~= "Instance" then
		return
	end
	player:SetAttribute("ShowTutorial", false)
	pcall(function()
		store:SetAsync(tostring(player.UserId), true)
	end)
end)
