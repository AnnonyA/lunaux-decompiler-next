from __future__ import annotations

from lunaux.backends.final_semantics import _rewrite_extended_boolean_ladders


def test_extended_boolean_ladder_inlines_scalar_temporary() -> None:
    source = """if left then
    local selected = not right
    if not selected then
    end
    selected = right
    if selected then
        value4 = 10
        selected = value4 < value
    end
end
print(selected, left, right)
"""

    assert _rewrite_extended_boolean_ladders(source) == """local selected = (left and not (right)) or (right and ((10) < value))
print(selected, left, right)
"""


def test_extended_boolean_ladder_rejects_effectful_temporary() -> None:
    source = """if left then
    local selected = not right
    if not selected then
    end
    selected = right
    if selected then
        value4 = nextLimit()
        selected = value4 < value
    end
end
"""

    assert _rewrite_extended_boolean_ladders(source) == source
