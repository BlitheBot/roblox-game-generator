--[[
	DesignSystem — Universal UI standards for all generated games.

	Every UI element in every template should be built through these values and
	factory functions so each game ships with a single, consistent, professional
	visual identity instead of ad-hoc per-script styling.

	Lives at ReplicatedStorage.Shared.DesignSystem; require it at the top of any
	UI script:

		local DS = require(game:GetService("ReplicatedStorage").Shared.DesignSystem)

	Genre palettes are applied at runtime with DS.applyGenrePalette(tag). Because
	ModuleScripts are cached per-environment, calling it from any one client
	script recolours the shared palette for every other UI script on that client.
--]]

local TweenService = game:GetService("TweenService")
local UserInputService = game:GetService("UserInputService")

local DesignSystem = {}

-- ═══════════════════════════════════════
-- DEVICE / RESPONSIVENESS
-- ═══════════════════════════════════════
function DesignSystem.isMobile()
	return UserInputService.TouchEnabled and not UserInputService.MouseEnabled
end

function DesignSystem.isSmallScreen()
	local camera = workspace.CurrentCamera
	if not camera then
		return DesignSystem.isMobile()
	end
	local viewport = camera.ViewportSize
	return viewport.X < 600 or viewport.Y < 400
end

-- Scale a desktop size down for small screens (keeps Scale components, shrinks
-- the Offset components by mobileScale).
function DesignSystem.getResponsiveSize(desktopSize, mobileScale)
	if DesignSystem.isSmallScreen() then
		local s = mobileScale or 0.85
		return UDim2.new(
			desktopSize.X.Scale,
			math.floor(desktopSize.X.Offset * s),
			desktopSize.Y.Scale,
			math.floor(desktopSize.Y.Offset * s)
		)
	end
	return desktopSize
end

-- ═══════════════════════════════════════
-- TYPOGRAPHY
-- ═══════════════════════════════════════
DesignSystem.Fonts = {
	Title = Enum.Font.GothamBold,
	Subtitle = Enum.Font.GothamMedium,
	Body = Enum.Font.Gotham,
	Button = Enum.Font.GothamBold,
	Number = Enum.Font.GothamBold,
	Small = Enum.Font.Gotham,
}

DesignSystem.TextSizes = {
	Title = 28,
	Subtitle = 20,
	Body = 16,
	Button = 16,
	Number = 22,
	Small = 12,
	HUD = 18,
}

-- ═══════════════════════════════════════
-- COLORS — safe defaults, overridden per genre at runtime
-- ═══════════════════════════════════════
DesignSystem.Colors = {
	-- Backgrounds
	BgDark = Color3.fromRGB(12, 14, 22),
	BgMedium = Color3.fromRGB(22, 26, 40),
	BgLight = Color3.fromRGB(35, 40, 58),
	BgHover = Color3.fromRGB(45, 52, 75),

	-- Primary action color (overridden per genre)
	Primary = Color3.fromRGB(255, 215, 0),
	PrimaryHover = Color3.fromRGB(220, 185, 0),
	PrimaryText = Color3.fromRGB(15, 15, 25),

	-- Secondary
	Secondary = Color3.fromRGB(80, 120, 255),
	SecondaryHover = Color3.fromRGB(60, 100, 220),
	Accent = Color3.fromRGB(255, 170, 0),

	-- Semantic
	Success = Color3.fromRGB(80, 200, 120),
	Warning = Color3.fromRGB(255, 160, 0),
	Error = Color3.fromRGB(220, 70, 70),
	Info = Color3.fromRGB(80, 160, 255),

	-- Text
	TextPrimary = Color3.fromRGB(240, 240, 250),
	TextSecondary = Color3.fromRGB(160, 165, 190),
	TextMuted = Color3.fromRGB(100, 105, 130),
	TextOnPrimary = Color3.fromRGB(15, 15, 25),

	-- Rarity (universal)
	RarityCommon = Color3.fromRGB(160, 165, 175),
	RarityUncommon = Color3.fromRGB(80, 200, 100),
	RarityRare = Color3.fromRGB(80, 130, 255),
	RarityEpic = Color3.fromRGB(170, 70, 230),
	RarityLegendary = Color3.fromRGB(255, 170, 0),
	RarityMythic = Color3.fromRGB(255, 60, 60),

	-- Currency
	CurrencyGold = Color3.fromRGB(255, 215, 0),
	CurrencyIcon = Color3.fromRGB(255, 200, 50),
}

-- ═══════════════════════════════════════
-- GENRE PALETTES
-- ═══════════════════════════════════════
local GenrePalettes = {
	idle_tycoon = {
		Primary = Color3.fromRGB(255, 180, 0),
		PrimaryHover = Color3.fromRGB(220, 150, 0),
		Secondary = Color3.fromRGB(0, 200, 100),
		BgDark = Color3.fromRGB(15, 15, 20),
		BgMedium = Color3.fromRGB(25, 28, 38),
		BgLight = Color3.fromRGB(40, 44, 58),
		Accent = Color3.fromRGB(255, 100, 0),
	},
	pet_collect = {
		Primary = Color3.fromRGB(255, 100, 180),
		PrimaryHover = Color3.fromRGB(220, 80, 150),
		Secondary = Color3.fromRGB(150, 80, 255),
		BgDark = Color3.fromRGB(18, 12, 30),
		BgMedium = Color3.fromRGB(30, 20, 50),
		BgLight = Color3.fromRGB(46, 34, 70),
		Accent = Color3.fromRGB(255, 220, 0),
	},
	survival_horror = {
		Primary = Color3.fromRGB(200, 30, 30),
		PrimaryHover = Color3.fromRGB(170, 20, 20),
		Secondary = Color3.fromRGB(0, 180, 180),
		BgDark = Color3.fromRGB(8, 8, 12),
		BgMedium = Color3.fromRGB(15, 15, 22),
		BgLight = Color3.fromRGB(28, 28, 38),
		Accent = Color3.fromRGB(180, 0, 0),
	},
	incremental_sim = {
		Primary = Color3.fromRGB(0, 160, 255),
		PrimaryHover = Color3.fromRGB(0, 130, 220),
		Secondary = Color3.fromRGB(0, 220, 180),
		BgDark = Color3.fromRGB(20, 28, 44),
		BgMedium = Color3.fromRGB(30, 40, 60),
		BgLight = Color3.fromRGB(44, 56, 80),
		Accent = Color3.fromRGB(0, 100, 255),
	},
}

function DesignSystem.applyGenrePalette(genre)
	local palette = GenrePalettes[genre]
	if not palette then
		return
	end
	for key, value in pairs(palette) do
		DesignSystem.Colors[key] = value
	end
end

-- ═══════════════════════════════════════
-- SPACING AND SIZING
-- ═══════════════════════════════════════
DesignSystem.Spacing = {
	XS = 4,
	SM = 8,
	MD = 12,
	LG = 16,
	XL = 24,
	XXL = 32,
}

DesignSystem.CornerRadius = {
	SM = UDim.new(0, 6),
	MD = UDim.new(0, 10),
	LG = UDim.new(0, 16),
	Full = UDim.new(1, 0),
}

DesignSystem.ButtonSizes = {
	SM = UDim2.new(0, 100, 0, 36),
	MD = UDim2.new(0, 160, 0, 44),
	LG = UDim2.new(0, 220, 0, 52),
	Full = UDim2.new(1, 0, 0, 48),
}

-- Minimum touch target size (mobile friendly)
DesignSystem.MinTouchSize = 44

-- ═══════════════════════════════════════
-- ANIMATION PRESETS
-- ═══════════════════════════════════════
DesignSystem.Animations = {
	Fast = TweenInfo.new(0.15, Enum.EasingStyle.Quad, Enum.EasingDirection.Out),
	Normal = TweenInfo.new(0.25, Enum.EasingStyle.Quad, Enum.EasingDirection.Out),
	Slow = TweenInfo.new(0.4, Enum.EasingStyle.Quad, Enum.EasingDirection.Out),
	Spring = TweenInfo.new(0.5, Enum.EasingStyle.Back, Enum.EasingDirection.Out),
	Bounce = TweenInfo.new(0.6, Enum.EasingStyle.Bounce, Enum.EasingDirection.Out),
}

-- ═══════════════════════════════════════
-- COMPONENT FACTORY
-- ═══════════════════════════════════════

function DesignSystem.createPanel(options)
	options = options or {}
	local frame = Instance.new("Frame")
	frame.Size = options.size or UDim2.new(1, 0, 1, 0)
	frame.Position = options.position or UDim2.new(0, 0, 0, 0)
	frame.BackgroundColor3 = options.color or DesignSystem.Colors.BgMedium
	frame.BackgroundTransparency = options.transparency or 0
	frame.BorderSizePixel = 0

	local corner = Instance.new("UICorner")
	corner.CornerRadius = options.corner or DesignSystem.CornerRadius.MD
	corner.Parent = frame

	if options.shadow then
		local shadow = Instance.new("Frame")
		shadow.Name = "DropShadow"
		shadow.Size = UDim2.new(1, 6, 1, 6)
		shadow.Position = UDim2.new(0, -3, 0, 4)
		shadow.BackgroundColor3 = Color3.fromRGB(0, 0, 0)
		shadow.BackgroundTransparency = 0.7
		shadow.BorderSizePixel = 0
		shadow.ZIndex = math.max(1, frame.ZIndex - 1)
		local shadowCorner = Instance.new("UICorner")
		shadowCorner.CornerRadius = options.corner or DesignSystem.CornerRadius.MD
		shadowCorner.Parent = shadow
		-- Parent the shadow to the panel itself so it follows it and never
		-- floats over sibling UI (ZIndex keeps it visually behind the content).
		shadow.Parent = frame
	end

	if options.parent then
		frame.Parent = options.parent
	end

	return frame
end

function DesignSystem.createButton(options)
	options = options or {}
	local style = options.style or "primary"

	local colors = {
		primary = {
			bg = DesignSystem.Colors.Primary,
			hover = DesignSystem.Colors.PrimaryHover,
			text = DesignSystem.Colors.PrimaryText,
		},
		secondary = {
			bg = DesignSystem.Colors.BgLight,
			hover = DesignSystem.Colors.BgHover,
			text = DesignSystem.Colors.TextPrimary,
		},
		danger = {
			bg = DesignSystem.Colors.Error,
			hover = Color3.fromRGB(190, 50, 50),
			text = Color3.fromRGB(255, 255, 255),
		},
		ghost = {
			bg = Color3.fromRGB(0, 0, 0),
			hover = DesignSystem.Colors.BgLight,
			text = DesignSystem.Colors.TextPrimary,
		},
	}

	local c = colors[style] or colors.primary

	-- Enforce a minimum touch target (48px on mobile, 40px desktop) so buttons
	-- are always tappable, regardless of the requested size.
	local size = options.size or DesignSystem.ButtonSizes.MD
	local minSize = DesignSystem.isMobile() and 48 or 40
	if size.Y.Scale == 0 and size.Y.Offset < minSize then
		size = UDim2.new(size.X.Scale, size.X.Offset, 0, minSize)
	end

	local button = Instance.new("TextButton")
	button.Size = size
	button.Position = options.position or UDim2.new(0, 0, 0, 0)
	button.BackgroundColor3 = c.bg
	button.BackgroundTransparency = style == "ghost" and 1 or 0
	button.TextColor3 = c.text
	button.Font = DesignSystem.Fonts.Button
	button.TextSize = DesignSystem.TextSizes.Button
	button.Text = (options.icon and options.icon .. "  " or "") .. (options.text or "Button")
	button.BorderSizePixel = 0
	button.AutoButtonColor = false

	local corner = Instance.new("UICorner")
	corner.CornerRadius = options.corner or DesignSystem.CornerRadius.MD
	corner.Parent = button

	-- Press/hover feedback uses a child UIScale so it works for any Size
	-- (Scale- or Offset-based) without recomputing UDim2 offsets.
	local scale = Instance.new("UIScale")
	scale.Scale = 1
	scale.Parent = button

	button.MouseEnter:Connect(function()
		TweenService:Create(button, DesignSystem.Animations.Fast, { BackgroundColor3 = c.hover }):Play()
		TweenService:Create(scale, DesignSystem.Animations.Fast, { Scale = 1.04 }):Play()
	end)
	button.MouseLeave:Connect(function()
		TweenService:Create(button, DesignSystem.Animations.Fast, { BackgroundColor3 = c.bg }):Play()
		TweenService:Create(scale, DesignSystem.Animations.Fast, { Scale = 1 }):Play()
	end)
	button.MouseButton1Down:Connect(function()
		TweenService:Create(scale, DesignSystem.Animations.Fast, { Scale = 0.95 }):Play()
	end)
	button.MouseButton1Up:Connect(function()
		TweenService:Create(scale, DesignSystem.Animations.Fast, { Scale = 1.04 }):Play()
	end)

	if options.onClick then
		button.MouseButton1Click:Connect(options.onClick)
	end

	if options.parent then
		button.Parent = options.parent
	end

	return button
end

function DesignSystem.createLabel(options)
	options = options or {}
	local styleMap = {
		title = { font = DesignSystem.Fonts.Title, size = DesignSystem.TextSizes.Title, color = DesignSystem.Colors.TextPrimary },
		subtitle = { font = DesignSystem.Fonts.Subtitle, size = DesignSystem.TextSizes.Subtitle, color = DesignSystem.Colors.TextPrimary },
		body = { font = DesignSystem.Fonts.Body, size = DesignSystem.TextSizes.Body, color = DesignSystem.Colors.TextSecondary },
		small = { font = DesignSystem.Fonts.Small, size = DesignSystem.TextSizes.Small, color = DesignSystem.Colors.TextMuted },
		number = { font = DesignSystem.Fonts.Number, size = DesignSystem.TextSizes.Number, color = DesignSystem.Colors.CurrencyGold },
		muted = { font = DesignSystem.Fonts.Body, size = DesignSystem.TextSizes.Body, color = DesignSystem.Colors.TextMuted },
	}

	local s = styleMap[options.style or "body"]

	local label = Instance.new("TextLabel")
	label.Size = options.size or UDim2.new(1, 0, 0, 30)
	label.Position = options.position or UDim2.new(0, 0, 0, 0)
	label.BackgroundTransparency = 1
	label.Text = options.text or ""
	label.TextColor3 = options.color or s.color
	label.Font = s.font
	label.TextSize = s.size
	label.TextXAlignment = options.align and Enum.TextXAlignment[options.align] or Enum.TextXAlignment.Left
	label.TextYAlignment = Enum.TextYAlignment.Center
	label.TextTruncate = Enum.TextTruncate.AtEnd
	label.BorderSizePixel = 0

	if options.parent then
		label.Parent = options.parent
	end

	return label
end

function DesignSystem.createDivider(parent, position)
	local divider = Instance.new("Frame")
	divider.Size = UDim2.new(1, -32, 0, 1)
	divider.Position = position or UDim2.new(0, 16, 0, 0)
	divider.BackgroundColor3 = DesignSystem.Colors.BgLight
	divider.BorderSizePixel = 0
	divider.Parent = parent
	return divider
end

function DesignSystem.createBadge(text, color, parent)
	local badge = Instance.new("Frame")
	badge.Size = UDim2.new(0, 0, 0, 22)
	badge.BackgroundColor3 = color or DesignSystem.Colors.Primary
	badge.BorderSizePixel = 0
	badge.AutomaticSize = Enum.AutomaticSize.X
	badge.Parent = parent

	local corner = Instance.new("UICorner")
	corner.CornerRadius = DesignSystem.CornerRadius.Full
	corner.Parent = badge

	local padding = Instance.new("UIPadding")
	padding.PaddingLeft = UDim.new(0, 8)
	padding.PaddingRight = UDim.new(0, 8)
	padding.Parent = badge

	local label = Instance.new("TextLabel")
	label.Size = UDim2.new(1, 0, 1, 0)
	label.AutomaticSize = Enum.AutomaticSize.X
	label.BackgroundTransparency = 1
	label.Text = text
	label.TextColor3 = Color3.fromRGB(255, 255, 255)
	label.Font = DesignSystem.Fonts.Button
	label.TextSize = 11
	label.Parent = badge

	return badge
end

function DesignSystem.animateIn(frame, direction)
	local originalPos = frame.Position
	local originalSize = frame.Size

	if direction == "scale" then
		frame.AnchorPoint = Vector2.new(0.5, 0.5)
		frame.Size = UDim2.new(0, 0, 0, 0)
		TweenService:Create(frame, DesignSystem.Animations.Spring, { Size = originalSize }):Play()
	elseif direction == "top" then
		frame.Position = UDim2.new(originalPos.X.Scale, originalPos.X.Offset, 0, -frame.AbsoluteSize.Y - 20)
		TweenService:Create(frame, DesignSystem.Animations.Spring, { Position = originalPos }):Play()
	elseif direction == "bottom" then
		frame.Position = UDim2.new(originalPos.X.Scale, originalPos.X.Offset, 1, 20)
		TweenService:Create(frame, DesignSystem.Animations.Spring, { Position = originalPos }):Play()
	end
end

function DesignSystem.animateOut(frame, direction, callback)
	local tween
	if direction == "scale" then
		tween = TweenService:Create(frame, DesignSystem.Animations.Fast, { Size = UDim2.new(0, 0, 0, 0) })
	elseif direction == "top" then
		tween = TweenService:Create(frame, DesignSystem.Animations.Normal, {
			Position = UDim2.new(frame.Position.X.Scale, frame.Position.X.Offset, 0, -frame.AbsoluteSize.Y - 20),
		})
	end

	if tween then
		tween:Play()
		if callback then
			tween.Completed:Connect(callback)
		end
	end
end

return DesignSystem
