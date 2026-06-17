--!strict
-- DataService: DataStore persistence with session cache and autosave.
-- All currency/stat mutations go through here. Server-authoritative only.

local DataStoreService = game:GetService("DataStoreService")
local Players = game:GetService("Players")
local RunService = game:GetService("RunService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local Config = require(game.ReplicatedStorage.Shared.Config)

-- Surface a save failure to the player (after retries are exhausted).
local function fireError(player: Player, errType: string)
	local remotes = ReplicatedStorage:FindFirstChild("Remotes")
	local err = remotes and remotes:FindFirstChild("ServerError")
	if err and err:IsA("RemoteEvent") then
		err:FireClient(player, errType)
	end
end

local STORE_NAME = "PlayerData_v1"
local AUTOSAVE_INTERVAL = 120

local DataService = {}

local store = nil
if not RunService:IsStudio() or pcall(function()
	return DataStoreService:GetDataStore(STORE_NAME)
end) then
	local ok, result = pcall(function()
		return DataStoreService:GetDataStore(STORE_NAME)
	end)
	if ok then
		store = result
	end
end

local sessionData: { [number]: any } = {}

local function defaultData()
	return {
		Currency = Config.StartingCurrency,
		PrestigeLevel = 0,
		Upgrades = {},
		OwnedPasses = {},
		TotalEarned = 0,
	}
end

function DataService.Load(player: Player)
	local data = defaultData()
	if store then
		local ok, saved = pcall(function()
			return store:GetAsync(tostring(player.UserId))
		end)
		if ok and saved then
			-- Merge saved over defaults so new fields get defaults
			for key, value in saved do
				data[key] = value
			end
		end
	end
	sessionData[player.UserId] = data
	return data
end

function DataService.Get(player: Player)
	return sessionData[player.UserId]
end

function DataService.Save(player: Player)
	local data = sessionData[player.UserId]
	if not data or not store then
		return
	end
	-- Retry up to 3 times with backoff before telling the player it failed.
	for attempt = 1, 3 do
		local ok = pcall(function()
			store:SetAsync(tostring(player.UserId), data)
		end)
		if ok then
			return
		end
		task.wait(attempt)
	end
	fireError(player, "datastore_failed")
end

function DataService.Release(player: Player)
	DataService.Save(player)
	sessionData[player.UserId] = nil
end

function DataService.AddCurrency(player: Player, amount: number)
	local data = sessionData[player.UserId]
	if not data then
		return
	end
	assert(amount == amount and amount ~= math.huge, "invalid currency amount")
	data.Currency += amount
	if amount > 0 then
		data.TotalEarned += amount
	end
end

function DataService.TrySpend(player: Player, amount: number): boolean
	local data = sessionData[player.UserId]
	if not data or amount <= 0 then
		return false
	end
	if data.Currency < amount then
		return false
	end
	data.Currency -= amount
	return true
end

function DataService.Init()
	task.spawn(function()
		while true do
			task.wait(AUTOSAVE_INTERVAL)
			for _, player in Players:GetPlayers() do
				DataService.Save(player)
			end
		end
	end)

	game:BindToClose(function()
		for _, player in Players:GetPlayers() do
			DataService.Save(player)
		end
	end)
end

return DataService
