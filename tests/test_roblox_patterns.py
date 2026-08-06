from __future__ import annotations

from lunaux.backends.roblox_patterns import match_function_call, match_method_call


def test_getservice_uses_literal_as_semantic_name_and_type() -> None:
    match = match_method_call("GetService", ("Players",))

    assert match is not None
    assert match.name == "Players"
    assert match.type_name == "Players"
    assert match.confidence >= 95


def test_collection_tag_result_gets_semantic_plural_name() -> None:
    match = match_method_call("GetTagged", ("Enemy",))

    assert match is not None
    assert match.name == "taggedEnemies"
    assert match.type_name == "{Instance}"


def test_property_changed_signal_uses_property_name() -> None:
    match = match_method_call("GetPropertyChangedSignal", ("Health",))

    assert match is not None
    assert match.name == "healthChanged"
    assert match.type_name == "RBXScriptSignal"


def test_instance_new_recovers_class_name_and_type() -> None:
    match = match_function_call("Instance.new", ("Part",))

    assert match is not None
    assert match.name == "part"
    assert match.type_name == "Part"


def test_constructor_registry_recovers_vector_type() -> None:
    match = match_function_call("Vector3.new", (None, None, None))

    assert match is not None
    assert match.name == "vector3"
    assert match.type_name == "Vector3"
