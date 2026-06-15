-- GameFeel — client-side juice that makes every game feel alive: screen
-- shake on major events, green/red screen-edge flashes for purchase
-- success/failure, floating "+amount" pickup text, a level-up/prestige
-- particle burst, and a welcome message on join.
--
-- Other client scripts fire feedback without coupling by firing the
-- BindableEvents created in ReplicatedStorage (FeedbackSuccess,
-- FeedbackError, FeedbackFloat, FeedbackBurst).
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local RunService = game:GetService("RunService")
local TweenService = game:GetService("TweenService")
local Workspace = game:GetService("Workspace")

local WELCOME = "Welcome to {{GAME_TITLE}}! Survive each round, escape the threat, and earn {{CURRENCY_NAME}}!"
local ACCENT = Color3.fromRGB(220, 60, 60)

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local gui = Instance.new("ScreenGui")
gui.Name = "GameFeel"
gui.IgnoreGuiInset = true
gui.DisplayOrder = 900
gui.ResetOnSpawn = false
gui.Parent = playerGui

-- Full-screen flash used for purchase success / failure feedback
local flash = Instance.new("Frame")
flash.Size = UDim2.fromScale(1, 1)
flash.BackgroundColor3 = Color3.fromRGB(0, 200, 0)
flash.BackgroundTransparency = 1
flash.BorderSizePixel = 0
flash.ZIndex = 5
flash.Parent = gui

local function flashEdge(color: Color3)
	flash.BackgroundColor3 = color
	flash.BackgroundTransparency = 0.6
	TweenService:Create(flash, TweenInfo.new(0.45), { BackgroundTransparency = 1 }):Play()
end

local function notify(text: string, color: Color3)
	local toast = Instance.new("TextLabel")
	toast.Size = UDim2.fromScale(0.5, 0.07)
	toast.Position = UDim2.fromScale(0.25, -0.1)
	toast.BackgroundColor3 = Color3.fromRGB(18, 18, 26)
	toast.BackgroundTransparency = 0.15
	toast.TextColor3 = color
	toast.Font = Enum.Font.GothamMedium
	toast.TextScaled = true
	toast.Text = text
	toast.ZIndex = 6
	toast.Parent = gui
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, 8)
	corner.Parent = toast
	TweenService:Create(toast, TweenInfo.new(0.5, Enum.EasingStyle.Back, Enum.EasingDirection.Out), { Position = UDim2.fromScale(0.25, 0.04) }):Play()
	task.delay(4, function()
		TweenService:Create(toast, TweenInfo.new(0.5), { Position = UDim2.fromScale(0.25, -0.12) }):Play()
		task.wait(0.6)
		toast:Destroy()
	end)
end

local camera = Workspace.CurrentCamera
local function shake(intensity: number, duration: number)
	local elapsed = 0
	local conn
	conn = RunService.RenderStepped:Connect(function(dt)
		elapsed += dt
		if elapsed >= duration or not camera then
			if conn then
				conn:Disconnect()
			end
			return
		end
		local mag = intensity * (1 - elapsed / duration)
		camera.CFrame = camera.CFrame * CFrame.new((math.random() * 2 - 1) * mag, (math.random() * 2 - 1) * mag, 0)
	end)
end

local function floatText(worldPos: Vector3, amount: number)
	local part = Instance.new("Part")
	part.Anchored = true
	part.CanCollide = false
	part.Transparency = 1
	part.Size = Vector3.new(1, 1, 1)
	part.Position = worldPos
	part.Parent = Workspace
	local bb = Instance.new("BillboardGui")
	bb.Size = UDim2.fromScale(4, 1.5)
	bb.AlwaysOnTop = true
	bb.Adornee = part
	bb.Parent = part
	local lbl = Instance.new("TextLabel")
	lbl.Size = UDim2.fromScale(1, 1)
	lbl.BackgroundTransparency = 1
	lbl.Font = Enum.Font.GothamBlack
	lbl.TextScaled = true
	lbl.TextColor3 = ACCENT
	lbl.Text = "+" .. tostring(amount)
	lbl.Parent = bb
	TweenService:Create(part, TweenInfo.new(1.2), { Position = worldPos + Vector3.new(0, 6, 0) }):Play()
	TweenService:Create(lbl, TweenInfo.new(1.2), { TextTransparency = 1 }):Play()
	task.delay(1.3, function()
		part:Destroy()
	end)
end

local function burstAtCharacter()
	local char = player.Character
	local root = char and char:FindFirstChild("HumanoidRootPart")
	if not root then
		return
	end
	local emitter = Instance.new("ParticleEmitter")
	emitter.Texture = "rbxassetid://6101304403"
	emitter.Rate = 0
	emitter.Lifetime = NumberRange.new(0.6, 1.2)
	emitter.Speed = NumberRange.new(10, 20)
	emitter.SpreadAngle = Vector2.new(180, 180)
	emitter.LightEmission = 1
	emitter.Color = ColorSequence.new(ACCENT)
	emitter.Parent = root
	emitter:Emit(40)
	task.delay(2, function()
		emitter:Destroy()
	end)
end

local function bindable(name: string): BindableEvent
	local b = ReplicatedStorage:FindFirstChild(name)
	if not b then
		b = Instance.new("BindableEvent")
		b.Name = name
		b.Parent = ReplicatedStorage
	end
	return b
end

bindable("FeedbackSuccess").Event:Connect(function()
	flashEdge(Color3.fromRGB(0, 200, 0))
end)
bindable("FeedbackError").Event:Connect(function()
	flashEdge(Color3.fromRGB(200, 0, 0))
end)
bindable("FeedbackFloat").Event:Connect(function(pos, amount)
	if typeof(pos) == "Vector3" then
		floatText(pos, amount or 0)
	end
end)
bindable("FeedbackBurst").Event:Connect(function()
	shake(0.6, 0.4)
	burstAtCharacter()
end)

-- Welcome message once the loading screen has cleared
task.wait(2.6)
notify(WELCOME, ACCENT)
