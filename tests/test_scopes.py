from __future__ import annotations

from lunaux.backends.bytecode import LocalInfo, LuauProto, TypedLocalInfo
from lunaux.backends.scopes import build_scope_tree


def _proto(
    locals_: tuple[LocalInfo, ...],
    *,
    typed: tuple[TypedLocalInfo, ...] = (),
) -> LuauProto:
    return LuauProto(
        proto_id=0,
        max_stack_size=8,
        num_params=0,
        num_upvalues=0,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=(0,) * 12,
        constants=(),
        child_proto_ids=(),
        line_defined=0,
        debug_name=None,
        line_info=(),
        locals=locals_,
        upvalue_names=(),
        feedback_pcs=(),
        cost=None,
        typed_locals=typed,
    )


def test_builds_nested_scopes_from_local_ranges() -> None:
    tree = build_scope_tree(
        _proto(
            (
                LocalInfo("outer", 0, 12, 0),
                LocalInfo("inner", 3, 8, 1),
            )
        )
    )

    assert len(tree.scopes) == 2
    assert tree.scope_at(1).scope_id == tree.root_id
    assert tree.scope_at(4).parent_id == tree.root_id
    assert tree.resolve("outer", 4) is not None
    assert tree.resolve("inner", 4) is not None
    assert tree.resolve("inner", 9) is None


def test_resolves_shadowed_names_to_innermost_binding() -> None:
    tree = build_scope_tree(
        _proto(
            (
                LocalInfo("value", 0, 12, 0),
                LocalInfo("value", 4, 9, 2),
            )
        )
    )

    outer = tree.resolve("value", 2)
    inner = tree.resolve("value", 5)

    assert outer is not None and outer.register == 0
    assert inner is not None and inner.register == 2


def test_tracks_register_reuse_across_disjoint_ranges() -> None:
    tree = build_scope_tree(
        _proto(
            (
                LocalInfo("first", 0, 4, 0),
                LocalInfo("second", 4, 10, 0),
            )
        )
    )

    first = tree.binding_for_register(0, 2)
    second = tree.binding_for_register(0, 6)

    assert first is not None and first.name == "first"
    assert second is not None and second.name == "second"


def test_attaches_typed_local_metadata_to_binding() -> None:
    tree = build_scope_tree(
        _proto(
            (LocalInfo("message", 2, 10, 1),),
            typed=(TypedLocalInfo(3, 1, 2, 10),),
        )
    )

    binding = tree.resolve("message", 5)

    assert binding is not None
    assert binding.type_tag == 3


def test_visible_bindings_respect_shadowing() -> None:
    tree = build_scope_tree(
        _proto(
            (
                LocalInfo("shared", 0, 12, 0),
                LocalInfo("other", 0, 12, 1),
                LocalInfo("shared", 3, 8, 2),
            )
        )
    )

    visible = {binding.name: binding.register for binding in tree.visible_bindings(5)}

    assert visible == {"shared": 2, "other": 1}
