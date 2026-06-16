-- AssetHealthCheck — on server start, test-load every resolved Toolbox asset
-- through RuntimeSafety.loadAsset (10s timeout + fallback) and log how many
-- succeeded vs. fell back, so broken/unavailable asset ids are visible.
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local RuntimeSafety = require(
	ReplicatedStorage:WaitForChild("Shared"):WaitForChild("RuntimeSafety")
)

local okCfg, Config = pcall(function()
	return require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("Config"))
end)
local assetIds = (okCfg and Config and Config.ToolboxAssetIds) or {}

task.spawn(function()
	local loaded, fellBack = 0, 0
	for _, id in assetIds do
		local model = RuntimeSafety.loadAsset(id, function()
			return nil
		end)
		if model then
			loaded += 1
			model:Destroy()
		else
			fellBack += 1
			warn("[AssetHealthCheck] asset " .. tostring(id) .. " unavailable — flag for replacement")
		end
	end
	print(("[AssetHealthCheck] %d asset(s) loaded, %d fell back"):format(loaded, fellBack))
end)
