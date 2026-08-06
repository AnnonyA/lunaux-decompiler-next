from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class RobloxPatternMatch:
    """Semantic evidence recovered from a recognized Roblox call pattern."""

    name: str | None
    type_name: str | None
    confidence: int
    evidence: str


def _identifier(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", value.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return None
    if cleaned[0].isdigit():
        cleaned = "value_" + cleaned
    return cleaned if _IDENTIFIER.fullmatch(cleaned) else None


def _lower_camel(value: str | None) -> str | None:
    identifier = _identifier(value)
    if not identifier:
        return None
    if identifier.isupper():
        return identifier.lower()
    return identifier[0].lower() + identifier[1:]


def _upper_camel(value: str | None) -> str | None:
    identifier = _identifier(value)
    if not identifier:
        return None
    return identifier[0].upper() + identifier[1:]


def _pluralize(value: str) -> str:
    lower = value.lower()
    if lower.endswith(("s", "x", "z", "ch", "sh")):
        return value + "es"
    if lower.endswith("y") and len(value) > 1 and lower[-2] not in "aeiou":
        return value[:-1] + "ies"
    return value + "s"


def _first_literal(arguments: tuple[str | None, ...]) -> str | None:
    return arguments[0] if arguments else None


def match_method_call(
    method: str | None,
    arguments: tuple[str | None, ...],
) -> RobloxPatternMatch | None:
    """Recognize common NAMECALL sequences without guessing beyond evidence."""

    if not method:
        return None
    literal = _first_literal(arguments)

    if method == "GetService" and literal:
        service = _identifier(literal)
        return RobloxPatternMatch(
            service,
            service,
            98,
            "Roblox GetService literal pattern",
        )

    if method in {"WaitForChild", "FindFirstChild"} and literal:
        return RobloxPatternMatch(
            _identifier(literal),
            "Instance" if method == "WaitForChild" else "Instance?",
            92,
            f"Roblox {method} literal pattern",
        )

    if method in {"FindFirstChildOfClass", "FindFirstChildWhichIsA"} and literal:
        class_name = _identifier(literal)
        return RobloxPatternMatch(
            _lower_camel(class_name),
            f"{class_name}?" if class_name else "Instance?",
            94,
            f"Roblox {method} class pattern",
        )

    if method == "FindFirstAncestor" and literal:
        suffix = _upper_camel(literal)
        return RobloxPatternMatch(
            f"ancestor{suffix}" if suffix else "ancestor",
            "Instance?",
            86,
            "Roblox FindFirstAncestor literal pattern",
        )

    if method in {"FindFirstAncestorOfClass", "FindFirstAncestorWhichIsA"} and literal:
        class_name = _identifier(literal)
        return RobloxPatternMatch(
            _lower_camel(class_name),
            f"{class_name}?" if class_name else "Instance?",
            91,
            f"Roblox {method} class pattern",
        )

    if method == "GetAttribute" and literal:
        base = _lower_camel(literal)
        return RobloxPatternMatch(
            f"{base}Attribute" if base else "attributeValue",
            "any",
            78,
            "Roblox GetAttribute literal pattern",
        )

    if method == "GetPropertyChangedSignal" and literal:
        base = _lower_camel(literal)
        return RobloxPatternMatch(
            f"{base}Changed" if base else "propertyChanged",
            "RBXScriptSignal",
            88,
            "Roblox property changed signal pattern",
        )

    if method == "GetAttributeChangedSignal" and literal:
        base = _lower_camel(literal)
        return RobloxPatternMatch(
            f"{base}Changed" if base else "attributeChanged",
            "RBXScriptSignal",
            88,
            "Roblox attribute changed signal pattern",
        )

    if method == "GetTagged" and literal:
        tag = _upper_camel(literal)
        plural = _pluralize(tag) if tag else "Instances"
        return RobloxPatternMatch(
            f"tagged{plural}",
            "{Instance}",
            90,
            "CollectionService GetTagged literal pattern",
        )

    fixed: Final[dict[str, tuple[str, str, int]]] = {
        "GetPlayers": ("players", "{Player}", 84),
        "GetChildren": ("children", "{Instance}", 82),
        "GetDescendants": ("descendants", "{Instance}", 82),
        "GetTouchingParts": ("touchingParts", "{BasePart}", 82),
        "GetConnectedParts": ("connectedParts", "{BasePart}", 82),
        "GetPartsInPart": ("overlappingParts", "{BasePart}", 82),
        "GetPartBoundsInBox": ("boundedParts", "{BasePart}", 80),
        "GetPartBoundsInRadius": ("nearbyParts", "{BasePart}", 80),
        "GetPlayerFromCharacter": ("player", "Player?", 86),
        "GetMouse": ("mouse", "Mouse", 84),
        "Raycast": ("raycastResult", "RaycastResult?", 88),
        "Clone": ("clone", None, 62),
    }
    fixed_match = fixed.get(method)
    if fixed_match is None:
        return None
    name, type_name, confidence = fixed_match
    return RobloxPatternMatch(
        name,
        type_name,
        confidence,
        f"Roblox {method} result pattern",
    )


def match_function_call(
    path: str | None,
    arguments: tuple[str | None, ...],
) -> RobloxPatternMatch | None:
    """Recognize semantic results of common direct Roblox constructor calls."""

    if not path:
        return None
    literal = _first_literal(arguments)

    if path == "Instance.new" and literal:
        class_name = _identifier(literal)
        return RobloxPatternMatch(
            _lower_camel(class_name),
            class_name or "Instance",
            96,
            "Roblox Instance.new class literal pattern",
        )

    constructors: Final[dict[str, tuple[str, str]]] = {
        "BrickColor.new": ("brickColor", "BrickColor"),
        "CFrame.new": ("cframe", "CFrame"),
        "CFrame.Angles": ("rotation", "CFrame"),
        "CFrame.lookAt": ("lookAt", "CFrame"),
        "Color3.new": ("color", "Color3"),
        "Color3.fromRGB": ("color", "Color3"),
        "Color3.fromHSV": ("color", "Color3"),
        "Color3.fromHex": ("color", "Color3"),
        "NumberRange.new": ("numberRange", "NumberRange"),
        "NumberSequence.new": ("numberSequence", "NumberSequence"),
        "Ray.new": ("ray", "Ray"),
        "Rect.new": ("rect", "Rect"),
        "Region3.new": ("region", "Region3"),
        "TweenInfo.new": ("tweenInfo", "TweenInfo"),
        "UDim.new": ("udim", "UDim"),
        "UDim2.new": ("udim2", "UDim2"),
        "UDim2.fromScale": ("udim2", "UDim2"),
        "UDim2.fromOffset": ("udim2", "UDim2"),
        "Vector2.new": ("vector2", "Vector2"),
        "Vector3.new": ("vector3", "Vector3"),
    }
    constructor = constructors.get(path)
    if constructor is not None:
        name, type_name = constructor
        return RobloxPatternMatch(
            name,
            type_name,
            88,
            f"Roblox constructor pattern {path}",
        )

    direct_results: Final[dict[str, tuple[str, str, int]]] = {
        "workspace.Raycast": ("raycastResult", "RaycastResult?", 88),
        "Players.GetPlayerFromCharacter": ("player", "Player?", 84),
    }
    direct = direct_results.get(path)
    if direct is None:
        return None
    name, type_name, confidence = direct
    return RobloxPatternMatch(
        name,
        type_name,
        confidence,
        f"Roblox direct call pattern {path}",
    )
