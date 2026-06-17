--[[
	OnboardingClient — the first-time player guide UI.

	* Step card (bottom-center): current step title + description.
	* Arrow indicator: bobs above the step's target object (CollectionService tag
	  or named instance) when one exists in the world.
	* Progress dots: how far through the steps the player is.
	* Skip button: dismiss at any time.

	A step advances when the server reports its matching completion event, or
	after a per-step timeout fallback so onboarding never blocks gameplay or
	stalls on an event this template can't emit. Completion is reported to the
	server, which grants the reward and sends the notification (a client can't
	fire a notification to itself).
--]]

local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local TweenService = game:GetService("TweenService")
local RunService = game:GetService("RunService")
local CollectionService = game:GetService("CollectionService")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local DS = require(Shared:WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local steps = {}
local currentStep = 1
local isOnboarding = false
local stepToken = 0

-- Timeouts: short for the final "you're ready" card, generous for event steps
-- (the matching event should normally fire first).
local FINAL_TIMEOUT = 5
local EVENT_TIMEOUT = 30

-- Forward declarations so handlers can reference each other.
local showStep
local advanceStep
local completeOnboarding

-- ── GUI ──────────────────────────────────────────────────────────────────────
local onboardGui = Instance.new("ScreenGui")
onboardGui.Name = "OnboardingGui"
onboardGui.ResetOnSpawn = false
onboardGui.DisplayOrder = 15
onboardGui.Enabled = false
onboardGui.Parent = playerGui

local stepCard = DS.createPanel({
	size = UDim2.new(0, 380, 0, 110),
	position = UDim2.new(0.5, -190, 1, -130),
	color = DS.Colors.BgDark,
	shadow = true,
	parent = onboardGui,
})

local accent = Instance.new("Frame")
accent.Size = UDim2.new(0, 4, 1, 0)
accent.BackgroundColor3 = DS.Colors.Primary
accent.BorderSizePixel = 0
accent.Parent = stepCard
local accentCorner = Instance.new("UICorner")
accentCorner.CornerRadius = DS.CornerRadius.SM
accentCorner.Parent = accent

local stepTitle = DS.createLabel({
	text = "Welcome!",
	size = UDim2.new(1, -70, 0, 28),
	position = UDim2.new(0, 16, 0, 8),
	style = "subtitle",
	color = DS.Colors.Primary,
	parent = stepCard,
})

local stepDesc = Instance.new("TextLabel")
stepDesc.Size = UDim2.new(1, -28, 0, 44)
stepDesc.Position = UDim2.new(0, 16, 0, 38)
stepDesc.BackgroundTransparency = 1
stepDesc.Text = ""
stepDesc.TextColor3 = DS.Colors.TextSecondary
stepDesc.Font = DS.Fonts.Body
stepDesc.TextSize = 14
stepDesc.TextXAlignment = Enum.TextXAlignment.Left
stepDesc.TextYAlignment = Enum.TextYAlignment.Top
stepDesc.TextWrapped = true
stepDesc.Parent = stepCard

-- Progress dots
local dotsFrame = Instance.new("Frame")
dotsFrame.Size = UDim2.new(0, 200, 0, 12)
dotsFrame.Position = UDim2.new(0, 16, 1, -22)
dotsFrame.BackgroundTransparency = 1
dotsFrame.Parent = stepCard

local dotsLayout = Instance.new("UIListLayout")
dotsLayout.FillDirection = Enum.FillDirection.Horizontal
dotsLayout.Padding = UDim.new(0, 6)
dotsLayout.VerticalAlignment = Enum.VerticalAlignment.Center
dotsLayout.Parent = dotsFrame

local dots = {}
local function updateDots(total, currentIdx)
	for _, dot in dots do
		dot:Destroy()
	end
	dots = {}
	for i = 1, total do
		local dot = Instance.new("Frame")
		dot.Size = UDim2.new(0, i == currentIdx and 20 or 8, 0, 8)
		dot.BackgroundColor3 = i == currentIdx and DS.Colors.Primary or DS.Colors.BgLight
		dot.BorderSizePixel = 0
		dot.LayoutOrder = i
		dot.Parent = dotsFrame
		local dotCorner = Instance.new("UICorner")
		dotCorner.CornerRadius = UDim.new(1, 0)
		dotCorner.Parent = dot
		table.insert(dots, dot)
	end
end

local skipBtn = DS.createButton({
	text = "SKIP",
	size = UDim2.new(0, 52, 0, 24),
	position = UDim2.new(1, -62, 0, 8),
	style = "ghost",
	onClick = function()
		completeOnboarding()
	end,
	parent = stepCard,
})
skipBtn.TextSize = 12

-- ── Arrow indicator ──────────────────────────────────────────────────────────
local arrowGui = Instance.new("BillboardGui")
arrowGui.Name = "OnboardingArrow"
arrowGui.Size = UDim2.new(0, 60, 0, 80)
arrowGui.StudsOffset = Vector3.new(0, 8, 0)
arrowGui.AlwaysOnTop = true
arrowGui.Enabled = false
arrowGui.Parent = workspace

local arrowLabel = Instance.new("TextLabel")
arrowLabel.Size = UDim2.new(1, 0, 1, 0)
arrowLabel.BackgroundTransparency = 1
arrowLabel.Text = "⬇️"
arrowLabel.TextScaled = true
arrowLabel.Font = DS.Fonts.Body
arrowLabel.Parent = arrowGui

RunService.RenderStepped:Connect(function()
	if not arrowGui.Enabled then
		return
	end
	local offset = math.sin(os.clock() * 3) * 1.5
	arrowGui.StudsOffset = Vector3.new(0, 8 + offset, 0)
end)

local function findTarget(tag)
	if not tag then
		return nil
	end
	local tagged = CollectionService:GetTagged(tag)
	if #tagged > 0 then
		return tagged[1]
	end
	return workspace:FindFirstChild(tag, true)
end

-- ── Step flow ────────────────────────────────────────────────────────────────
function showStep(step)
	stepTitle.Text = step.title or ""
	stepDesc.Text = step.description or ""
	updateDots(#steps, currentStep)

	stepCard.Position = UDim2.new(0.5, -190, 1, 10)
	TweenService:Create(stepCard, TweenInfo.new(0.4, Enum.EasingStyle.Back, Enum.EasingDirection.Out), {
		Position = UDim2.new(0.5, -190, 1, -130),
	}):Play()

	local target = findTarget(step.arrow_target)
	if target and (target:IsA("BasePart") or target:IsA("Model")) then
		arrowGui.Adornee = target
		arrowGui.Enabled = true
	else
		arrowGui.Enabled = false
	end

	-- Timeout fallback so the guide always progresses.
	stepToken += 1
	local myToken = stepToken
	local timeout = step.complete_event == nil and FINAL_TIMEOUT or EVENT_TIMEOUT
	task.delay(timeout, function()
		if isOnboarding and stepToken == myToken then
			advanceStep()
		end
	end)
end

function advanceStep()
	currentStep += 1
	if currentStep > #steps then
		completeOnboarding()
		return
	end
	TweenService:Create(stepCard, TweenInfo.new(0.2), {
		Position = UDim2.new(0.5, -190, 1, 10),
	}):Play()
	task.wait(0.25)
	showStep(steps[currentStep])
end

function completeOnboarding()
	if not isOnboarding then
		return
	end
	isOnboarding = false
	stepToken += 1 -- invalidate any pending timeout
	arrowGui.Enabled = false

	TweenService:Create(stepCard, TweenInfo.new(0.3), {
		Position = UDim2.new(0.5, -190, 1, 10),
	}):Play()
	task.delay(0.3, function()
		onboardGui.Enabled = false
	end)

	-- Server grants the reward and sends the notification.
	local Remotes = ReplicatedStorage:FindFirstChild("Remotes")
	local complete = Remotes and Remotes:FindFirstChild("CompleteOnboarding")
	if complete then
		complete:FireServer()
	end
end

-- ── Server hooks ─────────────────────────────────────────────────────────────
local Remotes = ReplicatedStorage:WaitForChild("Remotes", 10)
if Remotes then
	local startOnboard = Remotes:FindFirstChild("StartOnboarding")
	if startOnboard then
		startOnboard.OnClientEvent:Connect(function(onboardingSteps)
			if isOnboarding or typeof(onboardingSteps) ~= "table" or #onboardingSteps == 0 then
				return
			end
			steps = onboardingSteps
			currentStep = 1
			isOnboarding = true
			onboardGui.Enabled = true
			task.wait(0.5)
			showStep(steps[1])
		end)
	end

	local stepComplete = Remotes:FindFirstChild("OnboardingStepComplete")
	if stepComplete then
		stepComplete.OnClientEvent:Connect(function(eventName)
			if not isOnboarding then
				return
			end
			local data = steps[currentStep]
			if data and data.complete_event == eventName then
				advanceStep()
			end
		end)
	end
end
