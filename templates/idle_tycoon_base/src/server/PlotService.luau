--!strict
-- PlotService: assigns each joining player an empty plot, builds the base
-- tycoon geometry on it, and frees it on leave.

local Players = game:GetService("Players")

local Config = require(game.ReplicatedStorage.Shared.Config)

local PlotService = {}

local plotAssignments: { [number]: Model } = {} -- userId -> plot model
local freePlots: { Model } = {}

local function buildPlot(index: number): Model
	local plot = Instance.new("Model")
	plot.Name = "Plot" .. index

	local base = Instance.new("Part")
	base.Name = "Base"
	base.Anchored = true
	base.Size = Config.PlotSize
	base.Position = Vector3.new((index - 1) * (Config.PlotSize.X + 24), 0.5, 0)
	base.Color = Color3.fromRGB(120, 170, 100)
	base.Parent = plot

	local spawnPad = Instance.new("Part")
	spawnPad.Name = "SpawnPad"
	spawnPad.Anchored = true
	spawnPad.Size = Vector3.new(6, 1, 6)
	spawnPad.Position = base.Position + Vector3.new(0, 1, Config.PlotSize.Z / 2 - 4)
	spawnPad.Color = Color3.fromRGB(230, 220, 130)
	spawnPad.Parent = plot

	-- Dropper anchor points; ProductionService attaches droppers here
	local dropperFolder = Instance.new("Folder")
	dropperFolder.Name = "DropperAnchors"
	dropperFolder.Parent = plot
	for d = 1, 8 do
		local anchor = Instance.new("Part")
		anchor.Name = "Anchor" .. d
		anchor.Anchored = true
		anchor.Transparency = 1
		anchor.CanCollide = false
		anchor.Size = Vector3.new(2, 2, 2)
		anchor.Position = base.Position + Vector3.new(-Config.PlotSize.X / 2 + 8 * d, 8, 0)
		anchor.Parent = dropperFolder
	end

	local collector = Instance.new("Part")
	collector.Name = "Collector"
	collector.Anchored = true
	collector.Size = Vector3.new(Config.PlotSize.X - 8, 1, 8)
	collector.Position = base.Position + Vector3.new(0, 1, -Config.PlotSize.Z / 2 + 6)
	collector.Color = Color3.fromRGB(80, 80, 90)
	collector.Parent = plot

	plot.Parent = workspace:WaitForChild("Plots")
	return plot
end

function PlotService.GetPlot(player: Player): Model?
	return plotAssignments[player.UserId]
end

function PlotService.Assign(player: Player): Model
	local plot = table.remove(freePlots)
	if not plot then
		plot = buildPlot(#workspace.Plots:GetChildren() + 1)
	end
	plotAssignments[player.UserId] = plot
	plot:SetAttribute("OwnerUserId", player.UserId)
	return plot
end

function PlotService.Free(player: Player)
	local plot = plotAssignments[player.UserId]
	if plot then
		plot:SetAttribute("OwnerUserId", nil)
		plotAssignments[player.UserId] = nil
		table.insert(freePlots, plot)
	end
end

function PlotService.Init()
	Players.PlayerRemoving:Connect(PlotService.Free)
end

return PlotService
