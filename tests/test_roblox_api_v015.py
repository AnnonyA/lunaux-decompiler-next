from __future__ import annotations

from lunaux.backends.roblox_api import (
    callback_parameter_types,
    catalog_summary,
    event_callback_types,
    method_return_type,
    property_type,
    service_type,
)


def test_owner_aware_properties_and_methods() -> None:
    assert service_type("Players") == "Players"
    assert property_type("BasePart", "Position") == "Vector3"
    assert property_type("Players", "LocalPlayer") == "Player"
    assert method_return_type("TweenService", "Create") == "Tween"
    assert method_return_type("Workspace", "Raycast") == "RaycastResult?"


def test_event_callback_types_require_owner_when_ambiguous() -> None:
    assert event_callback_types("InputBegan") == ("InputObject", "boolean")
    assert event_callback_types("Touched") == ()
    assert event_callback_types("Touched", "BasePart") == ("BasePart",)
    assert event_callback_types("Touched", "Humanoid") == ("BasePart", "BasePart")


def test_callback_contracts_cover_events_and_action_bindings() -> None:
    assert callback_parameter_types(
        method_name="Connect",
        receiver_path="UserInputService.InputBegan",
    ) == ("InputObject", "boolean")
    assert callback_parameter_types(method_name="BindToRenderStep") == ("number",)
    assert callback_parameter_types(method_name="BindAction") == (
        "string",
        "Enum.UserInputState",
        "InputObject",
    )


def test_catalog_has_nontrivial_coverage() -> None:
    summary = catalog_summary()
    assert summary["services"] >= 20
    assert summary["properties"] >= 40
    assert summary["methods"] >= 40
    assert summary["events"] >= 35
