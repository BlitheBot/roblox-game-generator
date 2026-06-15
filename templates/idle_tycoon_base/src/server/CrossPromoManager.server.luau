--!strict
-- CrossPromoManager: drop-in cross-game referral billboards.
-- SIBLINGS is baked in at build time by the LuauAgent from the other
-- live games on this genre account. For each sibling, a billboard Part
-- with a SurfaceGui ("Play our other game: <title>") spawns near the
-- spawn point, with a ProximityPrompt that teleports to that game.
-- The sibling list also replicates to clients via a runtime
-- CrossPromoSiblings RemoteEvent for any future client-side UI.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TeleportService = game:GetService("TeleportService")

local SIBLINGS = {{CROSS_PROMO_LUA}}

type Sibling = { title: string, universe_id: number, place_id: number }

-- Runtime remote — no default.project.json entry needed
local remotesFolder = ReplicatedStorage:FindFirstChild("CrossPromoRemotes") :: Folder?
if not remotesFolder then
	local folder = Instance.new("Folder")
	folder.Name = "CrossPromoRemotes"
	folder.Parent = ReplicatedStorage
	remotesFolder = folder
end
local siblingsRemote = (remotesFolder :: Folder):FindFirstChild("CrossPromoSiblings") :: RemoteEvent?
if not siblingsRemote then
	local remote = Instance.new("RemoteEvent")
	remote.Name = "CrossPromoSiblings"
	remote.Parent = remotesFolder
	siblingsRemote = remote
end

local function basePosition(): Vector3
	local spawnLocation = workspace:FindFirstChildOfClass("SpawnLocation")
	if spawnLocation then
		return spawnLocation.Position + Vector3.new(0, 6, -18)
	end
	return Vector3.new(0, 8, -30)
end

local function makeBillboard(sibling: Sibling, index: number)
	local part = Instance.new("Part")
	part.Name = ("CrossPromoBillboard_%d"):format(index)
	part.Anchored = true
	part.CanCollide = false
	part.Size = Vector3.new(12, 6, 0.5)
	part.Color = Color3.fromRGB(25, 28, 38)
	part.Position = basePosition() + Vector3.new((index - 1) * 14, 0, 0)

	local gui = Instance.new("SurfaceGui")
	gui.Face = Enum.NormalId.Front
	gui.SizingMode = Enum.SurfaceGuiSizingMode.PixelsPerStud
	gui.PixelsPerStud = 40
	gui.Parent = part

	local label = Instance.new("TextLabel")
	label.BackgroundTransparency = 1
	label.Size = UDim2.new(1, 0, 0.6, 0)
	label.Position = UDim2.new(0, 0, 0.05, 0)
	label.Font = Enum.Font.GothamBold
	label.TextScaled = true
	label.TextColor3 = Color3.fromRGB(255, 255, 255)
	label.TextWrapped = true
	label.Text = ("Play our other game:\n%s"):format(sibling.title)
	label.Parent = gui

	local hint = Instance.new("TextLabel")
	hint.BackgroundTransparency = 1
	hint.Size = UDim2.new(1, 0, 0.25, 0)
	hint.Position = UDim2.new(0, 0, 0.7, 0)
	hint.Font = Enum.Font.Gotham
	hint.TextScaled = true
	hint.TextColor3 = Color3.fromRGB(120, 200, 255)
	hint.Text = "Walk up and interact to play!"
	hint.Parent = gui

	local prompt = Instance.new("ProximityPrompt")
	prompt.ActionText = "Play " .. sibling.title
	prompt.ObjectText = "Our other game"
	prompt.HoldDuration = 0.5
	prompt.MaxActivationDistance = 12
	prompt.RequiresLineOfSight = false
	prompt.Parent = part
	prompt.Triggered:Connect(function(player: Player)
		pcall(function()
			TeleportService:TeleportAsync(sibling.place_id, { player })
		end)
	end)

	part.Parent = workspace
end

local valid: { Sibling } = {}
for _, sibling in SIBLINGS :: { Sibling } do
	if typeof(sibling.place_id) == "number" and sibling.place_id > 0 and sibling.title ~= "" then
		table.insert(valid, sibling)
	end
end

for index, sibling in valid do
	makeBillboard(sibling, index)
end

local function pushSiblings(player: Player)
	(siblingsRemote :: RemoteEvent):FireClient(player, valid)
end

Players.PlayerAdded:Connect(pushSiblings)
for _, player in Players:GetPlayers() do
	task.spawn(pushSiblings, player)
end

if #valid > 0 then
	print(("[CrossPromo] %d sibling billboard(s) active"):format(#valid))
end
