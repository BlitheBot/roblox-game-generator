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

-- Genre overlay: idle_tycoon — warm orange/gold, productive and busy
Lighting.Brightness = 3
Lighting.ClockTime = 14
Lighting.ColorShift_Top = Color3.fromRGB(255, 200, 140)
Lighting.Ambient = Color3.fromRGB(120, 105, 85)
atmosphere.Color = Color3.fromRGB(225, 205, 170)
atmosphere.Decay = Color3.fromRGB(150, 120, 90)
cc.Saturation = 0.15
cc.TintColor = Color3.fromRGB(255, 240, 215)

-- Keep TweenService referenced for future timed lighting shifts (LiveOps hook)
local _ = TweenService
