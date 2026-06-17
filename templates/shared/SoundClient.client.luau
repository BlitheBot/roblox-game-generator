--[[
	SoundClient — all client-side audio.

	* Plays looping ambient music on join (volume-controlled, gated on a real id).
	* Plays a click on every button and a soft tick on hover, for instant,
	  network-free UI feedback (hooks existing and future GUIs).
	* Plays server-requested SFX (PlaySound remote) — gameplay/economy/rarity.
	* Provides a settings menu (gear button, top-right) with Music + SFX sliders
	  that apply live and persist across sessions via the Volume remote.

	Ids resolve through ReplicatedStorage.Shared.SoundConfig.
--]]

local SoundService = game:GetService("SoundService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players = game:GetService("Players")
local UserInputService = game:GetService("UserInputService")
local Debris = game:GetService("Debris")

local Shared = ReplicatedStorage:WaitForChild("Shared")
local SoundConfig = require(Shared:WaitForChild("SoundConfig"))
local DS = require(Shared:WaitForChild("DesignSystem"))
DS.applyGenrePalette("{{MECHANIC_TAG}}")

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local MECHANIC = "{{MECHANIC_TAG}}"

-- Current volumes (0–1). MUSIC_BASE/SFX_BASE keep music quietly under SFX.
local MUSIC_BASE = 0.15
local SFX_BASE = 0.5
local volume = { music = 0.5, sfx = 0.5 }

-- ── Ambient music ───────────────────────────────────────────────────────────
-- Prefer a permissioned track from Config.AmbientSoundId (Roblox audio privacy
-- means a random music id would never play); fall back to SoundConfig, else stay
-- silent but keep the Sound wired so the volume slider still governs it.
local ambient = Instance.new("Sound")
ambient.Name = "AmbientMusic"
ambient.Looped = true
ambient.Volume = volume.music * MUSIC_BASE
ambient.Parent = SoundService

do
	local ambientId = SoundConfig.resolve("ambient_" .. MECHANIC) or 0
	local okCfg, Config = pcall(function()
		return require(Shared:WaitForChild("Config", 5))
	end)
	if okCfg and Config and tonumber(Config.AmbientSoundId) and tonumber(Config.AmbientSoundId) > 0 then
		ambientId = tonumber(Config.AmbientSoundId)
	end
	if ambientId and ambientId > 0 then
		ambient.SoundId = "rbxassetid://" .. tostring(ambientId)
		ambient:Play()
	end
end

-- ── SFX playback ─────────────────────────────────────────────────────────────
local function playSound(name, volumeScale)
	local id = SoundConfig.resolve(name)
	if not id or id <= 0 then
		return
	end
	local sound = Instance.new("Sound")
	sound.SoundId = "rbxassetid://" .. tostring(id)
	sound.Volume = volume.sfx * SFX_BASE * (volumeScale or 1)
	sound.Parent = SoundService
	sound:Play()
	Debris:AddItem(sound, sound.TimeLength > 0 and sound.TimeLength + 0.5 or 3)
end

-- ── UI button sounds ─────────────────────────────────────────────────────────
local hooked = setmetatable({}, { __mode = "k" })
local function hookButton(inst)
	if hooked[inst] then
		return
	end
	if inst:IsA("TextButton") or inst:IsA("ImageButton") then
		hooked[inst] = true
		inst.MouseButton1Click:Connect(function()
			playSound("button_click")
		end)
		inst.MouseEnter:Connect(function()
			playSound("button_hover", 0.5)
		end)
	end
end

local function hookGui(gui)
	for _, desc in gui:GetDescendants() do
		hookButton(desc)
	end
	gui.DescendantAdded:Connect(hookButton)
end

for _, gui in playerGui:GetChildren() do
	if gui:IsA("ScreenGui") then
		hookGui(gui)
	end
end
playerGui.ChildAdded:Connect(function(child)
	if child:IsA("ScreenGui") then
		task.defer(hookGui, child)
	end
end)

-- ── Volume application + persistence ─────────────────────────────────────────
local function applyVolume()
	ambient.Volume = volume.music * MUSIC_BASE
end

local Remotes = ReplicatedStorage:WaitForChild("Remotes", 10)
local volumeRemote = Remotes and Remotes:FindFirstChild("Volume")

local function saveVolume()
	if volumeRemote then
		volumeRemote:FireServer("save", volume.music, volume.sfx)
	end
end

local function setMusicVolume(v)
	volume.music = math.clamp(v, 0, 1)
	applyVolume()
	saveVolume()
end

local function setSFXVolume(v)
	volume.sfx = math.clamp(v, 0, 1)
	saveVolume()
end

-- Load persisted settings from the server, then ask for them.
if volumeRemote then
	volumeRemote.OnClientEvent:Connect(function(kind, music, sfx)
		if kind == "settings" then
			if typeof(music) == "number" then
				volume.music = math.clamp(music, 0, 1)
			end
			if typeof(sfx) == "number" then
				volume.sfx = math.clamp(sfx, 0, 1)
			end
			applyVolume()
		end
	end)
	volumeRemote:FireServer("load")
end

-- Server-requested SFX (gameplay / economy / rarity / feedback).
if Remotes then
	local playSoundRemote = Remotes:FindFirstChild("PlaySound")
	if playSoundRemote then
		playSoundRemote.OnClientEvent:Connect(function(name)
			playSound(name)
		end)
	end
end

-- ── Settings menu (gear → panel with two sliders) ────────────────────────────
local settingsGui = Instance.new("ScreenGui")
settingsGui.Name = "SettingsGui"
settingsGui.ResetOnSpawn = false
settingsGui.DisplayOrder = 18
settingsGui.Parent = playerGui

local gearBtn = DS.createButton({
	text = "⚙",
	size = UDim2.new(0, 44, 0, 44),
	position = UDim2.new(1, -56, 0, 64),
	style = "secondary",
	parent = settingsGui,
})

local panel = DS.createPanel({
	size = UDim2.new(0, 300, 0, 180),
	position = UDim2.new(0.5, -150, 0.5, -90),
	color = DS.Colors.BgDark,
	shadow = true,
	parent = settingsGui,
})
panel.Visible = false

DS.createLabel({
	text = "⚙  Settings",
	size = UDim2.new(1, -24, 0, 32),
	position = UDim2.new(0, 16, 0, 8),
	style = "title",
	parent = panel,
})

DS.createButton({
	text = "✕",
	size = UDim2.new(0, 36, 0, 36),
	position = UDim2.new(1, -44, 0, 6),
	style = "ghost",
	onClick = function()
		panel.Visible = false
	end,
	parent = panel,
})

local function createSlider(yOffset, labelText, initial, onChange)
	DS.createLabel({
		text = labelText,
		size = UDim2.new(1, -32, 0, 20),
		position = UDim2.new(0, 16, 0, yOffset),
		style = "body",
		parent = panel,
	})

	local track = Instance.new("Frame")
	track.Size = UDim2.new(1, -32, 0, 10)
	track.Position = UDim2.new(0, 16, 0, yOffset + 24)
	track.BackgroundColor3 = DS.Colors.BgLight
	track.BorderSizePixel = 0
	track.Parent = panel
	local trackCorner = Instance.new("UICorner")
	trackCorner.CornerRadius = UDim.new(1, 0)
	trackCorner.Parent = track

	local fill = Instance.new("Frame")
	fill.Size = UDim2.new(initial, 0, 1, 0)
	fill.BackgroundColor3 = DS.Colors.Primary
	fill.BorderSizePixel = 0
	fill.Parent = track
	local fillCorner = Instance.new("UICorner")
	fillCorner.CornerRadius = UDim.new(1, 0)
	fillCorner.Parent = fill

	local knob = Instance.new("Frame")
	knob.AnchorPoint = Vector2.new(0.5, 0.5)
	knob.Size = UDim2.new(0, 18, 0, 18)
	knob.Position = UDim2.new(initial, 0, 0.5, 0)
	knob.BackgroundColor3 = DS.Colors.Primary
	knob.BorderSizePixel = 0
	knob.ZIndex = 2
	knob.Parent = track
	local knobCorner = Instance.new("UICorner")
	knobCorner.CornerRadius = UDim.new(1, 0)
	knobCorner.Parent = knob

	local function setFromX(px)
		local width = track.AbsoluteSize.X
		if width <= 0 then
			return
		end
		local rel = math.clamp((px - track.AbsolutePosition.X) / width, 0, 1)
		fill.Size = UDim2.new(rel, 0, 1, 0)
		knob.Position = UDim2.new(rel, 0, 0.5, 0)
		onChange(rel)
	end

	local dragging = false
	track.InputBegan:Connect(function(input)
		if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
			dragging = true
			setFromX(input.Position.X)
		end
	end)
	UserInputService.InputChanged:Connect(function(input)
		if dragging and (input.UserInputType == Enum.UserInputType.MouseMovement or input.UserInputType == Enum.UserInputType.Touch) then
			setFromX(input.Position.X)
		end
	end)
	UserInputService.InputEnded:Connect(function(input)
		if input.UserInputType == Enum.UserInputType.MouseButton1 or input.UserInputType == Enum.UserInputType.Touch then
			dragging = false
		end
	end)

	return function(rel)
		fill.Size = UDim2.new(rel, 0, 1, 0)
		knob.Position = UDim2.new(rel, 0, 0.5, 0)
	end
end

local setMusicKnob = createSlider(52, "Music", volume.music, setMusicVolume)
local setSFXKnob = createSlider(112, "Sound Effects", volume.sfx, setSFXVolume)

-- Reflect server-loaded settings on the sliders too.
if volumeRemote then
	volumeRemote.OnClientEvent:Connect(function(kind)
		if kind == "settings" then
			setMusicKnob(volume.music)
			setSFXKnob(volume.sfx)
		end
	end)
end

gearBtn.MouseButton1Click:Connect(function()
	panel.Visible = not panel.Visible
end)

return {
	playSound = playSound,
	setMusicVolume = setMusicVolume,
	setSFXVolume = setSFXVolume,
}
