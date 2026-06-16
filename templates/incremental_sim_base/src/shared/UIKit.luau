-- UIKit — shared UI styling kit so every generated game's interface meets a
-- consistent polish bar (rounded corners, Gotham, hover, drop shadows, a gold
-- primary palette). Used directly by new UI and applied retroactively to
-- existing UI by UIPolish.client.luau.
local TweenService = game:GetService("TweenService")

local UIKit = {}

UIKit.Colors = {
	Primary = Color3.fromRGB(255, 215, 0),    -- gold
	PanelBg = Color3.fromRGB(15, 20, 35),     -- dark navy
	Secondary = Color3.fromRGB(200, 200, 210), -- light grey text
	Success = Color3.fromRGB(100, 220, 100),
	Error = Color3.fromRGB(220, 80, 80),
	Dark = Color3.fromRGB(15, 15, 25),
}

function UIKit.addCorner(inst: Instance, radius: number?)
	local corner = Instance.new("UICorner")
	corner.CornerRadius = UDim.new(0, radius or 8)
	corner.Parent = inst
	return corner
end

-- A subtle dark frame offset 2px behind a panel
function UIKit.addShadow(frame: GuiObject)
	local shadow = Instance.new("Frame")
	shadow.Name = "DropShadow"
	shadow.AnchorPoint = frame.AnchorPoint
	shadow.Size = frame.Size
	shadow.Position = frame.Position + UDim2.fromOffset(2, 2)
	shadow.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
	shadow.BackgroundTransparency = 0.6
	shadow.BorderSizePixel = 0
	shadow.ZIndex = math.max(1, frame.ZIndex - 1)
	UIKit.addCorner(shadow, 8)
	shadow.Parent = frame.Parent
	return shadow
end

function UIKit.addHover(button: GuiButton, base: Color3?, hover: Color3?)
	local baseColor = base or button.BackgroundColor3
	local hoverColor = hover
		or Color3.new(baseColor.R * 0.85, baseColor.G * 0.85, baseColor.B * 0.85)
	button.MouseEnter:Connect(function()
		TweenService:Create(button, TweenInfo.new(0.1), { BackgroundColor3 = hoverColor }):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, TweenInfo.new(0.1), { BackgroundColor3 = baseColor }):Play()
	end)
end

-- The canonical button used by all templates.
function UIKit.createButton(parent: Instance, text: string, position: UDim2, size: UDim2, onClick)
	local button = Instance.new("TextButton")
	button.Size = size
	button.Position = position
	button.BackgroundColor3 = UIKit.Colors.Primary
	button.TextColor3 = UIKit.Colors.Dark
	button.Font = Enum.Font.GothamBold
	button.TextScaled = true
	button.Text = text
	button.BorderSizePixel = 0
	button.AutoButtonColor = false
	button.Parent = parent
	UIKit.addCorner(button, 8)
	UIKit.addHover(button, UIKit.Colors.Primary, Color3.fromRGB(220, 185, 0))
	if onClick then
		button.MouseButton1Click:Connect(onClick)
	end
	return button
end

return UIKit
