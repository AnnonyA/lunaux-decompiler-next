from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from lunaux.backends.roblox_api import (
    method_return_type as roblox_method_return_type,
)
from lunaux.backends.roblox_api import (
    property_type as roblox_property_type,
)

_PROPERTY_TYPES: Final[dict[str, str]] = {
    "AbsolutePosition": "Vector2",
    "AbsoluteSize": "Vector2",
    "Active": "boolean",
    "Anchored": "boolean",
    "AssemblyAngularVelocity": "Vector3",
    "AssemblyLinearVelocity": "Vector3",
    "CanCollide": "boolean",
    "CanQuery": "boolean",
    "CanTouch": "boolean",
    "Character": "Model?",
    "ClassName": "string",
    "CFrame": "CFrame",
    "Disabled": "boolean",
    "DisplayName": "string",
    "Enabled": "boolean",
    "Health": "number",
    "LocalPlayer": "Player",
    "MaxHealth": "number",
    "Name": "string",
    "Parent": "Instance?",
    "Position": "Vector3",
    "PrimaryPart": "BasePart?",
    "Size": "Vector3",
    "Text": "string",
    "TextBounds": "Vector2",
    "Transparency": "number",
    "Value": "any",
    "Velocity": "Vector3",
    "Visible": "boolean",
    "WalkSpeed": "number",
    "WorldPosition": "Vector3",
}

_METHOD_RETURN_TYPES: Final[dict[str, str]] = {
    "Clone": "Instance",
    "DistanceFromCharacter": "number",
    "FindFirstAncestor": "Instance?",
    "FindFirstChild": "Instance?",
    "GetAttribute": "any",
    "GetAttributeChangedSignal": "RBXScriptSignal",
    "GetChildren": "{Instance}",
    "GetConnectedParts": "{BasePart}",
    "GetDebugId": "string",
    "GetDescendants": "{Instance}",
    "GetFullName": "string",
    "GetMass": "number",
    "GetMouse": "Mouse",
    "GetPlayerFromCharacter": "Player?",
    "GetPlayers": "{Player}",
    "GetPropertyChangedSignal": "RBXScriptSignal",
    "GetRankInGroup": "number",
    "GetRoleInGroup": "string",
    "GetServerTimeNow": "number",
    "GetTagged": "{Instance}",
    "GetTouchingParts": "{BasePart}",
    "IsA": "boolean",
    "IsAncestorOf": "boolean",
    "IsDescendantOf": "boolean",
    "IsFriendsWith": "boolean",
    "IsLoaded": "boolean",
    "Raycast": "RaycastResult?",
    "WaitForChild": "Instance",
}

_NUMERIC_OPCODES: Final[frozenset[str]] = frozenset(
    {
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "MOD",
        "POW",
        "IDIV",
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "SUBRK",
        "DIVRK",
        "MINUS",
        "LENGTH",
    }
)

_CONSTANT_TYPES: Final[dict[str, str]] = {
    "boolean": "boolean",
    "closure": "function",
    "integer": "integer",
    "nil": "nil",
    "number": "number",
    "string": "string",
    "table": "table",
    "table_with_constants": "table",
    "vector": "vector",
    "vectord": "vector",
}

_CONSTRUCTOR_TYPES: Final[dict[str, str]] = {
    "BrickColor.new": "BrickColor",
    "CFrame.new": "CFrame",
    "CFrame.Angles": "CFrame",
    "CFrame.lookAt": "CFrame",
    "Color3.new": "Color3",
    "Color3.fromRGB": "Color3",
    "Color3.fromHSV": "Color3",
    "Color3.fromHex": "Color3",
    "Instance.new": "Instance",
    "NumberRange.new": "NumberRange",
    "NumberSequence.new": "NumberSequence",
    "Ray.new": "Ray",
    "Rect.new": "Rect",
    "Region3.new": "Region3",
    "TweenInfo.new": "TweenInfo",
    "UDim.new": "UDim",
    "UDim2.new": "UDim2",
    "UDim2.fromScale": "UDim2",
    "UDim2.fromOffset": "UDim2",
    "Vector2.new": "Vector2",
    "Vector3.new": "Vector3",
}


def infer_constant_type(kind: str | None) -> str | None:
    return _CONSTANT_TYPES.get(kind or "")


def infer_instruction_type(
    opcode: str,
    *,
    constant_kind: str | None = None,
) -> str | None:
    """Infer the result type of a value-producing opcode before source emission."""

    if opcode == "LOADNIL":
        return "nil"
    if opcode == "LOADB":
        return "boolean"
    if opcode == "LOADN":
        return "number"
    if opcode in {"LOADK", "LOADKX"}:
        return infer_constant_type(constant_kind)
    if opcode in _NUMERIC_OPCODES:
        return "number"
    if opcode == "CONCAT":
        return "string"
    if opcode == "NOT":
        return "boolean"
    if opcode in {"NEWTABLE", "DUPTABLE"}:
        return "table"
    if opcode in {"NEWCLOSURE", "DUPCLOSURE"}:
        return "function"
    if opcode == "NEWCLASS":
        return "class"
    return None


def infer_property_type(
    property_name: str | None,
    *,
    owner_type: str | None = None,
    use_roblox_api: bool = True,
) -> str | None:
    if use_roblox_api:
        api_type = roblox_property_type(owner_type, property_name)
        if api_type is not None:
            return api_type
    return _PROPERTY_TYPES.get(property_name or "")


def infer_method_return(
    method: str | None,
    *,
    owner_type: str | None = None,
    use_roblox_api: bool = True,
) -> str | None:
    if not method:
        return None
    if use_roblox_api:
        api_type = roblox_method_return_type(owner_type, method)
        if api_type is not None:
            return api_type
    if method in {"FindFirstChildOfClass", "FindFirstChildWhichIsA"}:
        return "Instance?"
    if method in {"FindFirstAncestorOfClass", "FindFirstAncestorWhichIsA"}:
        return "Instance?"
    return _METHOD_RETURN_TYPES.get(method)


def infer_function_return(path: str | None) -> str | None:
    if not path:
        return None
    constructor = _CONSTRUCTOR_TYPES.get(path)
    if constructor is not None:
        return constructor
    if path in {"type", "typeof", "tostring"}:
        return "string"
    if path == "tonumber":
        return "number?"
    if path == "require":
        return "any"
    if path.startswith("math."):
        return "number"
    if path.startswith("string."):
        tail = path.rsplit(".", 1)[-1]
        if tail in {"byte", "find", "len"}:
            return "number"
        if tail == "match":
            return "string?"
        if tail == "gmatch":
            return "function"
        return "string"
    if path.startswith("bit32."):
        return "number"
    if path.startswith("buffer.read"):
        tail = path.rsplit(".", 1)[-1]
        return "string" if tail == "string" else "number"
    if path == "rawget":
        return "any"
    if path == "workspace.Raycast":
        return "RaycastResult?"
    if path == "Players.GetPlayerFromCharacter":
        return "Player?"
    return None


def merge_types(types: Iterable[str]) -> str | None:
    """Merge compatible flow facts without producing unbounded union annotations."""

    values = {value for value in types if value and value != "any"}
    if not values:
        return None
    if "number" in values and "integer" in values:
        values.discard("integer")
    if "nil" in values and len(values) == 2:
        values.remove("nil")
        return next(iter(values)).removesuffix("?") + "?"
    if len(values) == 1:
        return next(iter(values))
    if len(values) <= 3:
        return " | ".join(sorted(values))
    return None
