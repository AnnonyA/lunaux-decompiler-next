from __future__ import annotations

from lunaux.backends.type_inference import (
    infer_function_return,
    infer_instruction_type,
    infer_method_return,
    infer_property_type,
    merge_types,
)


def test_opcode_types_are_known_before_source_emission() -> None:
    assert infer_instruction_type("LOADN") == "number"
    assert infer_instruction_type("LOADK", constant_kind="string") == "string"
    assert infer_instruction_type("CONCAT") == "string"
    assert infer_instruction_type("NEWTABLE") == "table"


def test_roblox_properties_and_methods_have_conservative_types() -> None:
    assert infer_property_type("Health") == "number"
    assert infer_property_type("PrimaryPart") == "BasePart?"
    assert infer_method_return("GetPlayers") == "{Player}"
    assert infer_method_return("Raycast") == "RaycastResult?"


def test_direct_constructor_and_builtin_types_are_inferred() -> None:
    assert infer_function_return("Vector3.new") == "Vector3"
    assert infer_function_return("Color3.fromRGB") == "Color3"
    assert infer_function_return("tonumber") == "number?"
    assert infer_function_return("math.floor") == "number"


def test_flow_merge_collapses_integer_into_number_and_optional_nil() -> None:
    assert merge_types({"integer", "number"}) == "number"
    assert merge_types({"Player", "nil"}) == "Player?"
    assert merge_types({"string", "number"}) == "number | string"
