-- UIPolish — retroactively applies the UIKit polish bar to every GUI in
-- PlayerGui (rounded corners, Gotham font, button hover) so existing UI
-- scripts look consistent without each being rewritten. Conservative: it
-- only rounds corners, swaps the default font, and adds hover — it never
-- moves, resizes, or recolors existing elements.
local Players = game:GetService("Players")
local ReplicatedStorage = game:GetService("ReplicatedStorage")

local UIKit = require(ReplicatedStorage:WaitForChild("Shared"):WaitForChild("UIKit"))

local player = Players.LocalPlayer
local playerGui = player:WaitForChild("PlayerGui")

local function polish(inst: Instance)
	if inst:GetAttribute("UIPolished") then
		return
	end
	if inst:IsA("TextButton") or inst:IsA("TextLabel") or inst:IsA("TextBox") then
		if inst.Font == Enum.Font.SourceSans or inst.Font == Enum.Font.Legacy then
			inst.Font = Enum.Font.Gotham
		end
	end
	if (inst:IsA("Frame") or inst:IsA("TextButton") or inst:IsA("ImageButton") or inst:IsA("ImageLabel"))
		and not inst:FindFirstChildOfClass("UICorner")
	then
		UIKit.addCorner(inst, 8)
	end
	if inst:IsA("TextButton") then
		inst.AutoButtonColor = false
		UIKit.addHover(inst)
	end
	inst:SetAttribute("UIPolished", true)
end

local function polishTree(root: Instance)
	-- Leave the loading screen alone; it has its own styling and lifetime.
	if root:IsA("ScreenGui") and root.Name == "LoadingScreen" then
		return
	end
	polish(root)
	for _, descendant in root:GetDescendants() do
		polish(descendant)
	end
end

for _, gui in playerGui:GetChildren() do
	polishTree(gui)
end
playerGui.ChildAdded:Connect(function(child)
	task.defer(polishTree, child)
end)
playerGui.DescendantAdded:Connect(function(descendant)
	task.defer(polish, descendant)
end)
