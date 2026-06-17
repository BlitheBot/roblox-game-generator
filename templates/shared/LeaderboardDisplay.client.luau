--[[
	LeaderboardDisplay — top 10 players, toggled with the L key or a 🏆 button
	(so it's reachable on mobile too). Fed by the LeaderboardUpdate remote.
--]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")

local DS = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local lbGui = Instance.new("ScreenGui")
lbGui.Name = "LeaderboardGui"
lbGui.ResetOnSpawn = false
lbGui.DisplayOrder = 16
lbGui.Enabled = false
lbGui.Parent = playerGui

local panel = DS.createPanel({
	size = DS.getResponsiveSize(UDim2.new(0, 360, 0, 480)),
	position = UDim2.new(0.5, 0, 0.5, 0),
	color = DS.Colors.BgDark,
	shadow = true,
	parent = lbGui,
})
panel.AnchorPoint = Vector2.new(0.5, 0.5)

DS.createLabel({
	text = "🏆 LEADERBOARD",
	size = UDim2.new(1, 0, 0, 50),
	style = "title",
	align = "Center",
	parent = panel,
})

local listFrame = Instance.new("ScrollingFrame")
listFrame.Size = UDim2.new(1, -24, 1, -110)
listFrame.Position = UDim2.new(0, 12, 0, 56)
listFrame.BackgroundTransparency = 1
listFrame.BorderSizePixel = 0
listFrame.ScrollBarThickness = 4
listFrame.ScrollBarImageColor3 = DS.Colors.BgLight
listFrame.CanvasSize = UDim2.new(0, 0, 0, 0)
listFrame.AutomaticCanvasSize = Enum.AutomaticSize.Y
listFrame.Parent = panel

local listLayout = Instance.new("UIListLayout")
listLayout.Padding = UDim.new(0, 6)
listLayout.SortOrder = Enum.SortOrder.LayoutOrder
listLayout.Parent = listFrame

DS.createButton({
	text = "Close",
	size = UDim2.new(1, -24, 0, 44),
	position = UDim2.new(0, 12, 1, -56),
	style = "secondary",
	onClick = function()
		lbGui.Enabled = false
	end,
	parent = panel,
})

local function formatValue(n)
	n = tonumber(n) or 0
	if n >= 1e6 then
		return string.format("%.1fM", n / 1e6)
	elseif n >= 1e3 then
		return string.format("%.1fK", n / 1e3)
	end
	return tostring(math.floor(n))
end

local function populateLeaderboard(data)
	for _, child in listFrame:GetChildren() do
		if child:IsA("Frame") then
			child:Destroy()
		end
	end

	if typeof(data) ~= "table" or #data == 0 then
		DS.createLabel({
			text = "No scores yet — be the first!",
			size = UDim2.new(1, 0, 0, 40),
			style = "muted",
			align = "Center",
			parent = listFrame,
		})
		return
	end

	local medals = { "🥇", "🥈", "🥉" }
	for _, entry in ipairs(data) do
		local row = DS.createPanel({
			size = UDim2.new(1, 0, 0, 44),
			color = entry.rank <= 3 and DS.Colors.BgLight or DS.Colors.BgMedium,
			parent = listFrame,
		})
		row.LayoutOrder = entry.rank

		DS.createLabel({
			text = (medals[entry.rank] or ("#" .. entry.rank)) .. "  " .. tostring(entry.name),
			size = UDim2.new(0.6, 0, 1, 0),
			position = UDim2.new(0, 12, 0, 0),
			style = "body",
			parent = row,
		})
		DS.createLabel({
			text = formatValue(entry.value),
			size = UDim2.new(0.35, -12, 1, 0),
			position = UDim2.new(0.65, 0, 0, 0),
			style = "number",
			align = "Right",
			parent = row,
		})
	end
end

-- Toggle: L key (desktop) + a floating 🏆 button (mobile/everyone).
local function toggle()
	lbGui.Enabled = not lbGui.Enabled
end

local toggleGui = Instance.new("ScreenGui")
toggleGui.Name = "LeaderboardToggle"
toggleGui.ResetOnSpawn = false
toggleGui.DisplayOrder = 9
toggleGui.Parent = playerGui

DS.createButton({
	text = "🏆",
	size = UDim2.new(0, 44, 0, 44),
	position = UDim2.new(1, -56, 0, 114),
	style = "secondary",
	onClick = toggle,
	parent = toggleGui,
})

UserInputService.InputBegan:Connect(function(input, processed)
	if processed then
		return
	end
	if input.KeyCode == Enum.KeyCode.L then
		toggle()
	end
end)

local Remotes = ReplicatedStorage:WaitForChild("Remotes", 10)
if Remotes then
	local lbUpdate = Remotes:FindFirstChild("LeaderboardUpdate")
	if lbUpdate and lbUpdate:IsA("RemoteEvent") then
		lbUpdate.OnClientEvent:Connect(populateLeaderboard)
	end
end
