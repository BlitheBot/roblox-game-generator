-- LightingService — applied to all generated games automatically.
-- Runs on server start and sets up proper visuals so no game ever ships
-- with default baseplate lighting.
local Lighting = game:GetService("Lighting")
local TweenService = game:GetService("TweenService")

-- Base lighting that makes every game look good
Lighting.GlobalShadows = true
Lighting.Brightness = 2.5
Lighting.Ambient = Color3.fromRGB(100, 100, 120)
Lighting.ColorShift_Top = Color3.fromRGB(255, 230, 200)
Lighting.ColorShift_Bottom = Color3.fromRGB(100, 120, 150)

-- Atmosphere
local atmosphere = Instance.new("Atmosphere")
atmosphere.Density = 0.2
atmosphere.Offset = 0.2
atmosphere.Color = Color3.fromRGB(180, 190, 210)
atmosphere.Decay = Color3.fromRGB(100, 110, 130)
atmosphere.Glare = 0.1
atmosphere.Haze = 0.5
atmosphere.Parent = Lighting

-- Bloom
local bloom = Instance.new("BloomEffect")
bloom.Intensity = 0.4
bloom.Size = 24
bloom.Threshold = 0.95
bloom.Parent = Lighting

-- Color correction
local cc = Instance.new("ColorCorrectionEffect")
cc.Brightness = 0.02
cc.Contrast = 0.08
cc.Saturation = 0.12
cc.TintColor = Color3.fromRGB(255, 250, 240)
cc.Parent = Lighting

-- Sun rays
local sunrays = Instance.new("SunRaysEffect")
sunrays.Intensity = 0.08
sunrays.Spread = 0.5
sunrays.Parent = Lighting

-- Genre overlay: survival_horror — dark blue/green, low brightness, tense fog
Lighting.Brightness = 1.5
Lighting.ClockTime = 0
Lighting.Ambient = Color3.fromRGB(28, 38, 42)
Lighting.OutdoorAmbient = Color3.fromRGB(18, 28, 32)
Lighting.ColorShift_Top = Color3.fromRGB(80, 110, 110)
Lighting.ColorShift_Bottom = Color3.fromRGB(20, 40, 45)
Lighting.FogEnd = 200
Lighting.FogStart = 20
Lighting.FogColor = Color3.fromRGB(12, 18, 20)
atmosphere.Density = 0.4
atmosphere.Color = Color3.fromRGB(60, 80, 80)
atmosphere.Decay = Color3.fromRGB(20, 35, 35)
atmosphere.Haze = 1.5
atmosphere.Glare = 0
cc.Saturation = -0.2
cc.Contrast = 0.15
cc.Brightness = -0.02
cc.TintColor = Color3.fromRGB(185, 210, 210)
bloom.Intensity = 0.2
sunrays.Intensity = 0

local _ = TweenService
