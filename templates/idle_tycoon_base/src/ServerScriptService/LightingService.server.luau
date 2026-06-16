-- LightingService — minimum visual-polish bar applied to every generated
-- game on server start.
local Lighting = game:GetService("Lighting")

-- Base setup (makes every game look immediately more polished)
Lighting.GlobalShadows = true
Lighting.Brightness = 2
Lighting.Ambient = Color3.fromRGB(80, 80, 100)
Lighting.OutdoorAmbient = Color3.fromRGB(120, 130, 150)
Lighting.FogEnd = 1000 -- removes ugly default fog

local bloom = Instance.new("BloomEffect")
bloom.Intensity = 0.3
bloom.Size = 20
bloom.Threshold = 0.95
bloom.Parent = Lighting

local cc = Instance.new("ColorCorrectionEffect")
cc.Brightness = 0.02
cc.Contrast = 0.1
cc.Saturation = 0.15
cc.Parent = Lighting

local sunrays = Instance.new("SunRaysEffect")
sunrays.Intensity = 0.05
sunrays.Spread = 0.4
sunrays.Parent = Lighting

-- Genre overlay: idle_tycoon — warm productive factory feel
Lighting.Ambient = Color3.fromRGB(100, 90, 80)
Lighting.ColorShift_Top = Color3.fromRGB(255, 220, 180)
Lighting.Brightness = 2.5
