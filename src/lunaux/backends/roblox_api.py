from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class RobloxPropertySignature:
    owner: str
    name: str
    type_name: str


@dataclass(frozen=True, slots=True)
class RobloxMethodSignature:
    owner: str
    name: str
    return_type: str | None
    parameter_types: tuple[str, ...] = ()
    callback_parameter_types: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RobloxEventSignature:
    owner: str
    name: str
    parameter_types: tuple[str, ...]


_INHERITANCE: Final[dict[str, tuple[str, ...]]] = {
    "DataModel": ("Instance",),
    "Workspace": ("WorldRoot", "Model", "PVInstance", "Instance"),
    "WorldRoot": ("Model", "PVInstance", "Instance"),
    "Model": ("PVInstance", "Instance"),
    "BasePart": ("PVInstance", "Instance"),
    "Part": ("BasePart", "PVInstance", "Instance"),
    "MeshPart": ("BasePart", "PVInstance", "Instance"),
    "HumanoidRootPart": ("BasePart", "PVInstance", "Instance"),
    "GuiButton": ("GuiObject", "GuiBase2d", "Instance"),
    "TextButton": ("GuiButton", "GuiObject", "GuiBase2d", "Instance"),
    "ImageButton": ("GuiButton", "GuiObject", "GuiBase2d", "Instance"),
    "Player": ("Instance",),
    "Humanoid": ("Instance",),
    "Camera": ("Instance",),
    "RemoteEvent": ("BaseRemoteEvent", "Instance"),
    "UnreliableRemoteEvent": ("BaseRemoteEvent", "Instance"),
    "BindableEvent": ("Instance",),
    "ProximityPrompt": ("Instance",),
    "Tween": ("TweenBase", "Instance"),
    "NumberValue": ("ValueBase", "Instance"),
    "IntValue": ("ValueBase", "Instance"),
    "StringValue": ("ValueBase", "Instance"),
    "BoolValue": ("ValueBase", "Instance"),
    "ObjectValue": ("ValueBase", "Instance"),
}

_SERVICE_TYPES: Final[dict[str, str]] = {
    "CollectionService": "CollectionService",
    "ContextActionService": "ContextActionService",
    "DataStoreService": "DataStoreService",
    "HttpService": "HttpService",
    "Lighting": "Lighting",
    "MarketplaceService": "MarketplaceService",
    "PathfindingService": "PathfindingService",
    "Players": "Players",
    "ReplicatedFirst": "ReplicatedFirst",
    "ReplicatedStorage": "ReplicatedStorage",
    "RunService": "RunService",
    "ServerScriptService": "ServerScriptService",
    "ServerStorage": "ServerStorage",
    "SoundService": "SoundService",
    "StarterGui": "StarterGui",
    "StarterPlayer": "StarterPlayer",
    "Teams": "Teams",
    "TeleportService": "TeleportService",
    "TextChatService": "TextChatService",
    "TweenService": "TweenService",
    "UserInputService": "UserInputService",
    "Workspace": "Workspace",
}

_PROPERTIES: Final[tuple[RobloxPropertySignature, ...]] = (
    RobloxPropertySignature("Instance", "Archivable", "boolean"),
    RobloxPropertySignature("Instance", "ClassName", "string"),
    RobloxPropertySignature("Instance", "Name", "string"),
    RobloxPropertySignature("Instance", "Parent", "Instance?"),
    RobloxPropertySignature("Workspace", "CurrentCamera", "Camera?"),
    RobloxPropertySignature("Workspace", "Gravity", "number"),
    RobloxPropertySignature("BasePart", "Anchored", "boolean"),
    RobloxPropertySignature("BasePart", "AssemblyAngularVelocity", "Vector3"),
    RobloxPropertySignature("BasePart", "AssemblyLinearVelocity", "Vector3"),
    RobloxPropertySignature("BasePart", "AssemblyMass", "number"),
    RobloxPropertySignature("BasePart", "CanCollide", "boolean"),
    RobloxPropertySignature("BasePart", "CanQuery", "boolean"),
    RobloxPropertySignature("BasePart", "CanTouch", "boolean"),
    RobloxPropertySignature("BasePart", "CFrame", "CFrame"),
    RobloxPropertySignature("BasePart", "Color", "Color3"),
    RobloxPropertySignature("BasePart", "Massless", "boolean"),
    RobloxPropertySignature("BasePart", "Material", "Enum.Material"),
    RobloxPropertySignature("BasePart", "Orientation", "Vector3"),
    RobloxPropertySignature("BasePart", "Position", "Vector3"),
    RobloxPropertySignature("BasePart", "Size", "Vector3"),
    RobloxPropertySignature("BasePart", "Transparency", "number"),
    RobloxPropertySignature("Humanoid", "Health", "number"),
    RobloxPropertySignature("Humanoid", "MaxHealth", "number"),
    RobloxPropertySignature("Humanoid", "WalkSpeed", "number"),
    RobloxPropertySignature("Humanoid", "JumpPower", "number"),
    RobloxPropertySignature("Humanoid", "MoveDirection", "Vector3"),
    RobloxPropertySignature("Player", "Character", "Model?"),
    RobloxPropertySignature("Player", "DisplayName", "string"),
    RobloxPropertySignature("Player", "Name", "string"),
    RobloxPropertySignature("Player", "UserId", "number"),
    RobloxPropertySignature("Player", "Team", "Team?"),
    RobloxPropertySignature("Players", "LocalPlayer", "Player"),
    RobloxPropertySignature("GuiObject", "AbsolutePosition", "Vector2"),
    RobloxPropertySignature("GuiObject", "AbsoluteSize", "Vector2"),
    RobloxPropertySignature("GuiObject", "Active", "boolean"),
    RobloxPropertySignature("GuiObject", "Visible", "boolean"),
    RobloxPropertySignature("TextLabel", "Text", "string"),
    RobloxPropertySignature("TextButton", "Text", "string"),
    RobloxPropertySignature("TextBox", "Text", "string"),
    RobloxPropertySignature("UserInputService", "KeyboardEnabled", "boolean"),
    RobloxPropertySignature("UserInputService", "MouseEnabled", "boolean"),
    RobloxPropertySignature("UserInputService", "TouchEnabled", "boolean"),
    RobloxPropertySignature("UserInputService", "PreferredInput", "Enum.PreferredInput"),
    RobloxPropertySignature("Camera", "CFrame", "CFrame"),
    RobloxPropertySignature("Camera", "FieldOfView", "number"),
    RobloxPropertySignature("TweenBase", "PlaybackState", "Enum.PlaybackState"),
    RobloxPropertySignature("NumberValue", "Value", "number"),
    RobloxPropertySignature("IntValue", "Value", "number"),
    RobloxPropertySignature("StringValue", "Value", "string"),
    RobloxPropertySignature("BoolValue", "Value", "boolean"),
    RobloxPropertySignature("ObjectValue", "Value", "Instance?"),
)

_METHODS: Final[tuple[RobloxMethodSignature, ...]] = (
    RobloxMethodSignature("Instance", "Clone", "Instance"),
    RobloxMethodSignature("Instance", "FindFirstAncestor", "Instance?", ("string",)),
    RobloxMethodSignature("Instance", "FindFirstAncestorOfClass", "Instance?", ("string",)),
    RobloxMethodSignature("Instance", "FindFirstAncestorWhichIsA", "Instance?", ("string",)),
    RobloxMethodSignature("Instance", "FindFirstChild", "Instance?", ("string", "boolean?")),
    RobloxMethodSignature("Instance", "FindFirstChildOfClass", "Instance?", ("string",)),
    RobloxMethodSignature(
        "Instance", "FindFirstChildWhichIsA", "Instance?", ("string", "boolean?")
    ),
    RobloxMethodSignature("Instance", "GetAttribute", "any", ("string",)),
    RobloxMethodSignature("Instance", "GetAttributeChangedSignal", "RBXScriptSignal", ("string",)),
    RobloxMethodSignature("Instance", "GetChildren", "{Instance}"),
    RobloxMethodSignature("Instance", "GetDescendants", "{Instance}"),
    RobloxMethodSignature("Instance", "GetFullName", "string"),
    RobloxMethodSignature("Instance", "GetPropertyChangedSignal", "RBXScriptSignal", ("string",)),
    RobloxMethodSignature("Instance", "IsA", "boolean", ("string",)),
    RobloxMethodSignature("Instance", "IsAncestorOf", "boolean", ("Instance",)),
    RobloxMethodSignature("Instance", "IsDescendantOf", "boolean", ("Instance",)),
    RobloxMethodSignature("Instance", "WaitForChild", "Instance", ("string", "number?")),
    RobloxMethodSignature("BasePart", "GetConnectedParts", "{BasePart}", ("boolean?",)),
    RobloxMethodSignature("BasePart", "GetMass", "number"),
    RobloxMethodSignature("BasePart", "GetTouchingParts", "{BasePart}"),
    RobloxMethodSignature("BasePart", "GetVelocityAtPosition", "Vector3", ("Vector3",)),
    RobloxMethodSignature("BasePart", "IsGrounded", "boolean"),
    RobloxMethodSignature("Players", "GetPlayerFromCharacter", "Player?", ("Model",)),
    RobloxMethodSignature("Players", "GetPlayers", "{Player}"),
    RobloxMethodSignature("Player", "GetMouse", "Mouse"),
    RobloxMethodSignature("Player", "GetRankInGroup", "number", ("number",)),
    RobloxMethodSignature("Player", "GetRoleInGroup", "string", ("number",)),
    RobloxMethodSignature(
        "Workspace", "Raycast", "RaycastResult?", ("Vector3", "Vector3", "RaycastParams?")
    ),
    RobloxMethodSignature("CollectionService", "GetTagged", "{Instance}", ("string",)),
    RobloxMethodSignature(
        "CollectionService", "GetInstanceAddedSignal", "RBXScriptSignal", ("string",)
    ),
    RobloxMethodSignature(
        "CollectionService", "GetInstanceRemovedSignal", "RBXScriptSignal", ("string",)
    ),
    RobloxMethodSignature("TweenService", "Create", "Tween", ("Instance", "TweenInfo", "table")),
    RobloxMethodSignature("PathfindingService", "CreatePath", "Path", ("table?",)),
    RobloxMethodSignature(
        "DataStoreService",
        "GetDataStore",
        "GlobalDataStore",
        (
            "string",
            "string?",
        ),
    ),
    RobloxMethodSignature(
        "DataStoreService",
        "GetOrderedDataStore",
        "OrderedDataStore",
        (
            "string",
            "string?",
        ),
    ),
    RobloxMethodSignature("HttpService", "JSONDecode", "any", ("string",)),
    RobloxMethodSignature("HttpService", "JSONEncode", "string", ("any",)),
    RobloxMethodSignature("HttpService", "GenerateGUID", "string", ("boolean?",)),
    RobloxMethodSignature("UserInputService", "GetMouseLocation", "Vector2"),
    RobloxMethodSignature("UserInputService", "GetMouseDelta", "Vector2"),
    RobloxMethodSignature("UserInputService", "GetLastInputType", "Enum.UserInputType"),
    RobloxMethodSignature("UserInputService", "IsKeyDown", "boolean", ("Enum.KeyCode",)),
    RobloxMethodSignature("RunService", "IsClient", "boolean"),
    RobloxMethodSignature("RunService", "IsServer", "boolean"),
    RobloxMethodSignature("RunService", "IsStudio", "boolean"),
    RobloxMethodSignature(
        "RunService",
        "BindToRenderStep",
        "nil",
        ("string", "number", "function"),
        ("number",),
    ),
    RobloxMethodSignature(
        "ContextActionService",
        "BindAction",
        "nil",
        ("string", "function", "boolean", "...Enum.UserInputType | Enum.KeyCode"),
        ("string", "Enum.UserInputState", "InputObject"),
    ),
    RobloxMethodSignature(
        "ContextActionService",
        "BindActionAtPriority",
        "nil",
        ("string", "function", "boolean", "number", "...Enum.UserInputType | Enum.KeyCode"),
        ("string", "Enum.UserInputState", "InputObject"),
    ),
    RobloxMethodSignature("RemoteEvent", "FireClient", "nil", ("Player", "...any")),
    RobloxMethodSignature("RemoteEvent", "FireAllClients", "nil", ("...any",)),
    RobloxMethodSignature("RemoteEvent", "FireServer", "nil", ("...any",)),
    RobloxMethodSignature("BindableEvent", "Fire", "nil", ("...any",)),
)

_EVENTS: Final[tuple[RobloxEventSignature, ...]] = (
    RobloxEventSignature("Instance", "AncestryChanged", ("Instance", "Instance?")),
    RobloxEventSignature("Instance", "AttributeChanged", ("string",)),
    RobloxEventSignature("Instance", "ChildAdded", ("Instance",)),
    RobloxEventSignature("Instance", "ChildRemoved", ("Instance",)),
    RobloxEventSignature("Instance", "DescendantAdded", ("Instance",)),
    RobloxEventSignature("Instance", "DescendantRemoving", ("Instance",)),
    RobloxEventSignature("Instance", "Destroying", ()),
    RobloxEventSignature("BasePart", "Touched", ("BasePart",)),
    RobloxEventSignature("BasePart", "TouchEnded", ("BasePart",)),
    RobloxEventSignature("Players", "PlayerAdded", ("Player",)),
    RobloxEventSignature("Players", "PlayerRemoving", ("Player",)),
    RobloxEventSignature("Player", "CharacterAdded", ("Model",)),
    RobloxEventSignature("Player", "CharacterRemoving", ("Model",)),
    RobloxEventSignature("Player", "Chatted", ("string", "Player?")),
    RobloxEventSignature("Humanoid", "Died", ()),
    RobloxEventSignature("Humanoid", "HealthChanged", ("number",)),
    RobloxEventSignature("Humanoid", "MoveToFinished", ("boolean",)),
    RobloxEventSignature("Humanoid", "Running", ("number",)),
    RobloxEventSignature(
        "Humanoid",
        "StateChanged",
        ("Enum.HumanoidStateType", "Enum.HumanoidStateType"),
    ),
    RobloxEventSignature("Humanoid", "Touched", ("BasePart", "BasePart")),
    RobloxEventSignature("UserInputService", "InputBegan", ("InputObject", "boolean")),
    RobloxEventSignature("UserInputService", "InputChanged", ("InputObject", "boolean")),
    RobloxEventSignature("UserInputService", "InputEnded", ("InputObject", "boolean")),
    RobloxEventSignature("UserInputService", "JumpRequest", ()),
    RobloxEventSignature("UserInputService", "LastInputTypeChanged", ("Enum.UserInputType",)),
    RobloxEventSignature("RunService", "Heartbeat", ("number",)),
    RobloxEventSignature("RunService", "RenderStepped", ("number",)),
    RobloxEventSignature("RunService", "Stepped", ("number", "number")),
    RobloxEventSignature("RunService", "PreSimulation", ("number",)),
    RobloxEventSignature("RunService", "PostSimulation", ("number",)),
    RobloxEventSignature("GuiButton", "Activated", ("InputObject", "number")),
    RobloxEventSignature("GuiButton", "MouseButton1Click", ()),
    RobloxEventSignature("GuiButton", "MouseButton2Click", ()),
    RobloxEventSignature("RemoteEvent", "OnClientEvent", ("...any",)),
    RobloxEventSignature("RemoteEvent", "OnServerEvent", ("Player", "...any")),
    RobloxEventSignature("BindableEvent", "Event", ("...any",)),
    RobloxEventSignature("ProximityPrompt", "Triggered", ("Player",)),
    RobloxEventSignature("ProximityPrompt", "TriggerEnded", ("Player",)),
    RobloxEventSignature("TweenBase", "Completed", ("Enum.PlaybackState",)),
    RobloxEventSignature("NumberValue", "Changed", ("number",)),
    RobloxEventSignature("IntValue", "Changed", ("number",)),
    RobloxEventSignature("StringValue", "Changed", ("string",)),
    RobloxEventSignature("BoolValue", "Changed", ("boolean",)),
    RobloxEventSignature("ObjectValue", "Changed", ("Instance?",)),
)

_PROPERTY_INDEX: Final[dict[tuple[str, str], str]] = {
    (item.owner, item.name): item.type_name for item in _PROPERTIES
}
_METHOD_INDEX: Final[dict[tuple[str, str], RobloxMethodSignature]] = {
    (item.owner, item.name): item for item in _METHODS
}
_EVENT_INDEX: Final[dict[tuple[str, str], RobloxEventSignature]] = {
    (item.owner, item.name): item for item in _EVENTS
}


def _owner_candidates(owner_type: str | None) -> tuple[str, ...]:
    if not owner_type:
        return ()
    candidates: list[str] = []
    for union_part in owner_type.split(" | "):
        base = union_part.strip().removesuffix("?")
        if not base or base in candidates:
            continue
        candidates.append(base)
        candidates.extend(
            parent for parent in _INHERITANCE.get(base, ()) if parent not in candidates
        )
    return tuple(candidates)


def service_type(service_name: str | None) -> str | None:
    return _SERVICE_TYPES.get(service_name or "")


def property_type(owner_type: str | None, property_name: str | None) -> str | None:
    if not property_name:
        return None
    for owner in _owner_candidates(owner_type):
        result = _PROPERTY_INDEX.get((owner, property_name))
        if result is not None:
            return result
    event = event_signature(owner_type, property_name)
    if event is not None:
        return "RBXScriptSignal"
    matches = {value for (_owner, name), value in _PROPERTY_INDEX.items() if name == property_name}
    return next(iter(matches)) if len(matches) == 1 else None


def method_signature(
    owner_type: str | None,
    method_name: str | None,
) -> RobloxMethodSignature | None:
    if not method_name:
        return None
    for owner in _owner_candidates(owner_type):
        result = _METHOD_INDEX.get((owner, method_name))
        if result is not None:
            return result
    matches = [item for item in _METHODS if item.name == method_name]
    return matches[0] if len(matches) == 1 else None


def method_return_type(owner_type: str | None, method_name: str | None) -> str | None:
    signature = method_signature(owner_type, method_name)
    return signature.return_type if signature is not None else None


def event_signature(
    owner_type: str | None,
    event_name: str | None,
) -> RobloxEventSignature | None:
    if not event_name:
        return None
    for owner in _owner_candidates(owner_type):
        result = _EVENT_INDEX.get((owner, event_name))
        if result is not None:
            return result
    matches = [item for item in _EVENTS if item.name == event_name]
    parameter_sets = {item.parameter_types for item in matches}
    return matches[0] if len(parameter_sets) == 1 and matches else None


def event_callback_types(
    event_name: str | None,
    owner_type: str | None = None,
) -> tuple[str, ...]:
    signature = event_signature(owner_type, event_name)
    return signature.parameter_types if signature is not None else ()


def callback_parameter_types(
    *,
    method_name: str | None = None,
    receiver_path: str | None = None,
    owner_type: str | None = None,
    function_path: str | None = None,
) -> tuple[str, ...]:
    if method_name in {"Connect", "ConnectParallel", "Once"}:
        event_name = receiver_path.rsplit(".", 1)[-1] if receiver_path else None
        return event_callback_types(event_name, owner_type)
    signature = method_signature(owner_type, method_name)
    if signature is not None and signature.callback_parameter_types:
        return signature.callback_parameter_types
    fixed_methods: Final[dict[str, tuple[str, ...]]] = {
        "BindAction": ("string", "Enum.UserInputState", "InputObject"),
        "BindActionAtPriority": ("string", "Enum.UserInputState", "InputObject"),
        "BindToRenderStep": ("number",),
    }
    if method_name in fixed_methods:
        return fixed_methods[method_name]
    fixed_functions: Final[dict[str, tuple[str, ...]]] = {
        "table.sort": ("any", "any"),
    }
    return fixed_functions.get(function_path or "", ())


def catalog_summary() -> dict[str, int]:
    return {
        "services": len(_SERVICE_TYPES),
        "properties": len(_PROPERTIES),
        "methods": len(_METHODS),
        "events": len(_EVENTS),
    }
