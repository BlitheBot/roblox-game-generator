-- NewPlayerExperience — the first 60 seconds hook. On spawn: a 3s cinematic
-- camera pan across the map, a welcome toast, a bobbing tutorial arrow over
-- the nearest landmark (cleared once the player moves), and a confetti burst
-- to finish. Self-contained and defensive so it never blocks gameplay.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local GAME_TITLE = "{{GAME_TITLE}}"
local CURRENCY_NAME = "{{CURRENCY_NAME}}"

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local gui = Instance.new("ScreenGui")
gui.Name = "NewPlayerExperience"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.DisplayOrder = 50
gui.Parent = playerGui

local function toast(text: string)
	local frame = Instance.new("Frame")
	frame.Size = UDim2.fromScale(0.5, 0.08)
	frame.Position = UDim2.fromScale(0.25, -0.12)
	frame.BackgroundColor3 = Color3.fromRGB(15, 20, 35)
	frame.BackgroundTransparency = 0.1
	frame.BorderSizePixel = 0
	frame.Parent = gui
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 8)
	corner.Parent = frame
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(0.92, 0.8)
	label.Position = UDim2.fromScale(0.04, 0.1)
	label.BackgroundTransparency = 1
	label.Font = Enum.Font.GothamBold
	label.TextScaled = true
	label.TextColor3 = Color3.fromRGB(255, 215, 0)
	label.Text = text
	label.Parent = frame
	TweenService:Create(frame, TweenInfo.new(0.5, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {
		Position = UDim2.fromScale(0.25, 0.05),
	}):Play()
	task.delay(4, function()
		TweenService:Create(frame, TweenInfo.new(0.4), { Position = UDim2.fromScale(0.25, -0.12) }):Play()
		task.wait(0.5)
		frame:Destroy()
	end)
end

-- Pick the nearest prominent landmark (neon parts are the portals/eggs/signs)
local function findLandmark(origin: Vector3): BasePart?
	local best, bestDist
	for _, obj in Workspace:GetDescendants() do
		if obj:IsA("BasePart") and obj.Material == Enum.Material.Neon then
			local d = (obj.Position - origin).Magnitude
			if d > 8 and (not bestDist or d < bestDist) then
				best, bestDist = obj, d
			end
		end
	end
	return best
end

local function showArrow(target: BasePart)
	local holder = Instance.new("Part")
	holder.Anchored = true
	holder.CanCollide = false
	holder.Transparency = 1
	holder.Size = Vector3.new(1, 1, 1)
	holder.CFrame = CFrame.new(target.Position + Vector3.new(0, target.Size.Y / 2 + 6, 0))
	holder.Parent = Workspace
	local bb = Instance.new("BillboardGui")
	bb.Size = UDim2.fromOffset(70, 70)
	bb.AlwaysOnTop = true
	bb.Adornee = holder
	bb.Parent = holder
	local label = Instance.new("TextLabel")
	label.Size = UDim2.fromScale(1, 1)
	label.BackgroundTransparency = 1
	label.Font = Enum.Font.GothamBold
	label.TextScaled = true
	label.TextColor3 = Color3.fromRGB(255, 215, 0)
	label.TextStrokeTransparency = 0
	label.Text = "⬇"
	label.Parent = bb
	-- gentle bob
	TweenService:Create(holder, TweenInfo.new(0.6, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true), {
		CFrame = holder.CFrame * CFrame.new(0, 2, 0),
	}):Play()
	return holder
end

local function burst()
	local feedback = ReplicatedStorage:FindFirstChild("FeedbackBurst")
	if feedback and feedback:IsA("BindableEvent") then
		feedback:Fire()
		return
	end
	local char = player.Character
	local root = char and char:FindFirstChild("HumanoidRootPart")
	if not root then
		return
	end
	local emitter = Instance.new("ParticleEmitter")
	emitter.Texture = "rbxassetid://6101304403"
	emitter.Rate = 0
	emitter.Lifetime = NumberRange.new(0.8, 1.5)
	emitter.Speed = NumberRange.new(12, 22)
	emitter.SpreadAngle = Vector2.new(180, 180)
	emitter.LightEmission = 1
	emitter.Parent = root
	emitter:Emit(50)
	task.delay(2, function()
		emitter:Destroy()
	end)
end

task.spawn(function()
	local character = player.Character or player.CharacterAdded:Wait()
	local root = character:WaitForChild("HumanoidRootPart", 10)
	if not root then
		return
	end

	-- Cinematic pan across the map, then hand control back
	local camera = Workspace.CurrentCamera
	camera.CameraType = Enum.CameraType.Scriptable
	local focus = root.Position
	camera.CFrame = CFrame.new(focus + Vector3.new(60, 110, 180), focus)
	local pan = TweenService:Create(camera, TweenInfo.new(3, Enum.EasingStyle.Quad, Enum.EasingDirection.Out), {
		CFrame = CFrame.new(focus + Vector3.new(0, 8, 16), focus),
	})
	pan:Play()
	pan.Completed:Wait()
	camera.CameraType = Enum.CameraType.Custom

	toast("Welcome to " .. GAME_TITLE .. "! Here's some " .. CURRENCY_NAME .. " to get you started!")

	-- Tutorial arrow at the nearest landmark; clears when the player moves off
	local landmark = findLandmark(root.Position)
	if landmark then
		local arrow = showArrow(landmark)
		local startPos = root.Position
		task.spawn(function()
			local elapsed = 0
			while elapsed < 15 do
				task.wait(0.5)
				elapsed += 0.5
				if root.Parent == nil or (root.Position - startPos).Magnitude > 16 then
					break
				end
			end
			arrow:Destroy()
			toast("Nice! Explore and start earning " .. CURRENCY_NAME .. ".")
			task.wait(0.5)
			burst()
		end)
	else
		task.wait(2)
		burst()
	end
end)
