-- RuntimeSafety — shared runtime hardening used by every generated game.
-- Provides: safeCall (pcall wrapper), DataStore access with retries + a
-- mirrored backup key, a Toolbox asset loader with a 10s timeout + fallback,
-- and a generic RemoteEvent guard (rate limit + payload sanity + kick after
-- repeated violations). The compile-time AutoValidator can't catch runtime
-- bugs; this module is the runtime safety net.
local DataStoreService = game:GetService("DataStoreService")
local InsertService = game:GetService("InsertService")
local HttpService = game:GetService("HttpService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")

local RuntimeSafety = {}

local DATASTORE_RETRIES = 3

function RuntimeSafety.safeCall(fn, ...)
	local ok, err = pcall(fn, ...)
	if not ok then
		warn("[SAFE_CALL_ERROR] " .. tostring(err))
	end
	return ok
end

local function withRetries(fn)
	local lastErr
	for attempt = 1, DATASTORE_RETRIES do
		local ok, res = pcall(fn)
		if ok then
			return true, res
		end
		lastErr = res
		task.wait(attempt * 0.5) -- simple linear backoff
	end
	return false, lastErr
end

-- Best-effort remote logging of DataStore failures to the VPS-side
-- datastore_errors table. Off unless Config.TelemetryUrl is set (no ingest
-- server ships in this repo); never allowed to break gameplay.
function RuntimeSafety.logDataStoreError(op: string, key: string, err: string)
	warn(("[DATASTORE_ERROR] op=%s key=%s err=%s"):format(op, tostring(key), tostring(err)))
	local okCfg, Config = pcall(function()
		return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
	end)
	if okCfg and Config and Config.TelemetryUrl and Config.TelemetryUrl ~= "" then
		RuntimeSafety.safeCall(function()
			HttpService:PostAsync(
				Config.TelemetryUrl,
				HttpService:JSONEncode({ op = op, key = key, err = err })
			)
		end)
	end
end

-- Open a DataStore that transparently mirrors writes to a backup key and
-- falls back to it on load. Returns { load(key), save(key, value) }.
function RuntimeSafety.openStore(name: string)
	local store = DataStoreService:GetDataStore(name)
	local backup = DataStoreService:GetDataStore(name .. "_backup")
	local api = {}

	function api.load(key: string)
		local ok, res = withRetries(function()
			return store:GetAsync(key)
		end)
		if ok and res ~= nil then
			return res
		end
		warn("[DATASTORE] primary load failed for " .. tostring(key) .. " — trying backup")
		local okB, resB = withRetries(function()
			return backup:GetAsync(key)
		end)
		if okB then
			return resB
		end
		RuntimeSafety.logDataStoreError("load", key, tostring(res) .. " / " .. tostring(resB))
		return nil
	end

	function api.save(key: string, value)
		local okP = withRetries(function()
			store:SetAsync(key, value)
			return true
		end)
		local okB = withRetries(function()
			backup:SetAsync(key, value)
			return true
		end)
		if not (okP or okB) then
			RuntimeSafety.logDataStoreError("save", key, "primary and backup both failed")
			return false
		end
		return true
	end

	return api
end

-- Load a Toolbox asset with a 10s timeout; on any failure/timeout return the
-- fallback (which must return a visually acceptable Instance, never nil).
function RuntimeSafety.loadAsset(assetId: number, fallbackFn)
	local container
	local done = false
	task.spawn(function()
		local ok, res = pcall(function()
			return InsertService:LoadAsset(assetId)
		end)
		if ok then
			container = res
		end
		done = true
	end)
	local elapsed = 0
	while not done and elapsed < 10 do
		task.wait(0.1)
		elapsed += 0.1
	end
	if container then
		local model = container:GetChildren()[1]
		if model then
			model.Parent = nil -- detach so destroying the container keeps it
			container:Destroy()
			return model
		end
		container:Destroy()
	end
	warn("Asset " .. tostring(assetId) .. " failed to load, using fallback")
	return fallbackFn()
end

-- Attach a generic guard to a RemoteEvent: rate-limit detection (default
-- 10/sec/player) + oversized-payload detection; 3 violations kicks the
-- player. Per-remote argument validation still lives in each service; this
-- is a blanket abuse tripwire on top of it.
function RuntimeSafety.attachRemoteGuard(remote: RemoteEvent, opts)
	opts = opts or {}
	local maxPerSecond = opts.maxPerSecond or 10
	local calls: { [Player]: { number } } = {}
	local violations: { [Player]: number } = {}

	Players.PlayerRemoving:Connect(function(player)
		calls[player] = nil
		violations[player] = nil
	end)

	remote.OnServerEvent:Connect(function(player, ...)
		local now = os.clock()
		local stamps = calls[player]
		if not stamps then
			stamps = {}
			calls[player] = stamps
		end
		local i = 1
		while i <= #stamps do
			if now - stamps[i] > 1 then
				table.remove(stamps, i)
			else
				i += 1
			end
		end
		table.insert(stamps, now)

		local bad = #stamps > maxPerSecond
		for _, arg in { ... } do
			if typeof(arg) == "string" and #arg > 2000 then
				bad = true
			end
		end

		if bad then
			violations[player] = (violations[player] or 0) + 1
			warn(("[ANTI_EXPLOIT] %s violation %d on %s"):format(
				player.Name, violations[player], remote.Name
			))
			if violations[player] >= 3 then
				player:Kick("Too many invalid requests.")
			end
		end
	end)
end

return RuntimeSafety
