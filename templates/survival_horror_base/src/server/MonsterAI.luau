--!strict
-- MonsterAI: spawns {{MONSTER_NAME}} and chases the nearest living survivor.
-- Touching a survivor eliminates them. Server-side only.

local Players = game:GetService("Players")
local PathfindingService = game:GetService("PathfindingService")

local Config = require(game.ReplicatedStorage.Shared.Config)

local MonsterAI = {}

local monster: Model? = nil
local active = false

local function buildMonster(spawnPosition: Vector3): Model
	local model = Instance.new("Model")
	model.Name = Config.MonsterName

	local body = Instance.new("Part")
	body.Name = "HumanoidRootPart"
	body.Size = Vector3.new(4, 6, 3)
	body.Position = spawnPosition
	body.Color = Color3.fromRGB(20, 20, 25)
	body.Material = Enum.Material.Neon
	body.Parent = model

	local humanoid = Instance.new("Humanoid")
	humanoid.WalkSpeed = Config.MonsterSpeed
	humanoid.MaxHealth = math.huge
	humanoid.Health = math.huge
	humanoid.Parent = model

	model.PrimaryPart = body
	model.Parent = workspace
	return model
end

local function nearestSurvivor(from: Vector3, alive: { [number]: boolean }): Player?
	local best: Player? = nil
	local bestDist = math.huge
	for _, player in Players:GetPlayers() do
		if alive[player.UserId] then
			local character = player.Character
			local root = character and character:FindFirstChild("HumanoidRootPart") :: BasePart?
			if root then
				local dist = (root.Position - from).Magnitude
				if dist < bestDist then
					bestDist = dist
					best = player
				end
			end
		end
	end
	return best
end

function MonsterAI.Start(
	spawnPosition: Vector3,
	alive: { [number]: boolean },
	onEliminated: (player: Player) -> ()
)
	MonsterAI.Stop()
	monster = buildMonster(spawnPosition)
	active = true

	task.spawn(function()
		while active and monster and monster.Parent do
			local root = monster.PrimaryPart
			if not root then
				break
			end
			local target = nearestSurvivor(root.Position, alive)
			if target and target.Character then
				local targetRoot = target.Character:FindFirstChild("HumanoidRootPart") :: BasePart?
				local humanoid = monster:FindFirstChildOfClass("Humanoid")
				if targetRoot and humanoid then
					humanoid:MoveTo(targetRoot.Position)
					if (targetRoot.Position - root.Position).Magnitude <= Config.MonsterAttackRange then
						onEliminated(target)
					end
				end
			end
			task.wait(0.25)
		end
	end)
end

function MonsterAI.Stop()
	active = false
	if monster then
		monster:Destroy()
		monster = nil
	end
end

return MonsterAI
