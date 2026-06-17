--!strict
-- Tutorial (Bug 2) — first-time-only guided onboarding, in StarterGui.
--
-- Shows ONLY for first-time players (gated by the server-set "ShowTutorial"
-- attribute, persisted via TutorialGate's DataStore). Walks the new player
-- through their first action — moving and reaching a glowing objective — well
-- within 30 seconds of joining, then reports completion so it never shows again.

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local GAME_TITLE = "{{GAME_TITLE}}"
local CURRENCY_NAME = "{{CURRENCY_NAME}}"

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local TutorialComplete = Remotes:WaitForChild("TutorialComplete") :: RemoteEvent

-- ── first-time gate ─────────────────────────────────────────
-- Wait briefly for TutorialGate to publish the attribute; default to showing
-- (fail-open) so a slow/missing server still teaches new players.
local function shouldShow(): boolean
	local value = player:GetAttribute("ShowTutorial")
	if value == nil then
		local deadline = os.clock() + 5
		while value == nil and os.clock() < deadline do
			player:GetAttributeChangedSignal("ShowTutorial"):Wait()
			value = player:GetAttribute("ShowTutorial")
		end
	end
	if value == nil then
		return true
	end
	return value == true
end

if not shouldShow() then
	return
end

-- ── UI ──────────────────────────────────────────────────────
local gui = Instance.new("ScreenGui")
gui.Name = "TutorialGui"
gui.ResetOnSpawn = false
gui.IgnoreGuiInset = true
gui.DisplayOrder = 60
gui.Parent = playerGui

local card = Instance.new("Frame")
card.Size = UDim2.fromScale(0.5, 0.12)
card.Position = UDim2.fromScale(0.25, -0.16)
card.BackgroundColor3 = Color3.fromRGB(15, 20, 35)
card.BackgroundTransparency = 0.05
card.BorderSizePixel = 0
card.Parent = gui

local cardCorner = Instance.new("UICorner")
cardCorner.CornerRadius = UDim.new(0, 10)
cardCorner.Parent = card

local accent = Instance.new("Frame")
accent.Size = UDim2.new(0, 5, 1, 0)
accent.BackgroundColor3 = Color3.fromRGB(255, 215, 0)
accent.BorderSizePixel = 0
accent.Parent = card

local label = Instance.new("TextLabel")
label.Size = UDim2.fromScale(0.92, 0.78)
label.Position = UDim2.fromScale(0.05, 0.11)
label.BackgroundTransparency = 1
label.Font = Enum.Font.GothamBold
label.TextScaled = true
label.TextColor3 = Color3.fromRGB(255, 235, 170)
label.TextXAlignment = Enum.TextXAlignment.Left
label.Text = ""
label.Parent = card

local shown = false
local function showCard(text: string)
	label.Text = text
	if not shown then
		shown = true
		TweenService:Create(
			card,
			TweenInfo.new(0.45, Enum.EasingStyle.Back, Enum.EasingDirection.Out),
			{ Position = UDim2.fromScale(0.25, 0.04) }
		):Play()
	end
end

local function hideCard()
	TweenService:Create(card, TweenInfo.new(0.35), { Position = UDim2.fromScale(0.25, -0.16) }):Play()
	task.delay(0.4, function()
		gui:Destroy()
	end)
end

-- Bobbing world arrow over the nearest glowing objective (Neon parts are the
-- droppers/eggs/portals/signs placed by the map + decoration pass).
local function findLandmark(origin: Vector3): BasePart?
	local best, bestDist
	for _, obj in Workspace:GetDescendants() do
		if obj:IsA("BasePart") and obj.Material == Enum.Material.Neon then
			local d = (obj.Position - origin).Magnitude
			if d > 6 and (not bestDist or d < bestDist) then
				best, bestDist = obj, d
			end
		end
	end
	return best
end

local function showArrow(target: BasePart): Part
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
	local arrowLabel = Instance.new("TextLabel")
	arrowLabel.Size = UDim2.fromScale(1, 1)
	arrowLabel.BackgroundTransparency = 1
	arrowLabel.Font = Enum.Font.GothamBold
	arrowLabel.TextScaled = true
	arrowLabel.TextColor3 = Color3.fromRGB(255, 215, 0)
	arrowLabel.TextStrokeTransparency = 0
	arrowLabel.Text = "⬇"
	arrowLabel.Parent = bb
	TweenService:Create(
		holder,
		TweenInfo.new(0.6, Enum.EasingStyle.Sine, Enum.EasingDirection.InOut, -1, true),
		{ CFrame = holder.CFrame * CFrame.new(0, 2, 0) }
	):Play()
	return holder
end

local function finish()
	pcall(function()
		TutorialComplete:FireServer()
	end)
	hideCard()
end

-- ── guided flow (completes well within 30s) ─────────────────
task.spawn(function()
	local character = player.Character or player.CharacterAdded:Wait()
	local root = character:WaitForChild("HumanoidRootPart", 10)
	if not root then
		finish()
		return
	end

	-- Step 1: welcome (0-3s)
	showCard("👋 Welcome to " .. GAME_TITLE .. "! Let's learn the basics.")
	task.wait(3)

	-- Step 2: first action — move. Detect movement, or auto-advance at 10s.
	showCard("① Use WASD or the joystick to MOVE around.")
	local startPos = root.Position
	local moved = false
	local deadline = os.clock() + 10
	while os.clock() < deadline do
		task.wait(0.25)
		if root.Parent == nil then
			break
		end
		if (root.Position - startPos).Magnitude > 8 then
			moved = true
			break
		end
	end

	-- Step 3: point to the first objective (3-5s)
	showCard(
		(moved and "Nice! " or "")
		.. "② Head to the glowing spot to start earning " .. CURRENCY_NAME .. "!"
	)
	local landmark = findLandmark(root.Position)
	local arrow: Part? = nil
	if landmark then
		arrow = showArrow(landmark)
	end
	task.wait(if landmark then 6 else 3)
	if arrow then
		arrow:Destroy()
	end

	-- Step 4: done
	showCard("✅ You're all set — have fun and grow your " .. CURRENCY_NAME .. "!")
	task.wait(3)
	finish()
end)
