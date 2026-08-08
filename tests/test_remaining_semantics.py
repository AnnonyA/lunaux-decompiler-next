from __future__ import annotations

from lunaux.backends.ast import NameExpr, render_expression
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.remaining_semantics import (
    _access_expression_for_value,
    _nonconflicting_generated_name,
)
from lunaux.backends.ssa import SSAValue


def test_generated_name_respects_future_debug_binding() -> None:
    assert (
        _nonconflicting_generated_name(
            "value",
            frozenset({"value", "index"}),
            {"value2"},
        )
        == "value3"
    )


def test_reconstructs_elided_field_access_from_ssa_origin() -> None:
    base = SSAValue(register=0, version=0, origin_pc=None, kind="entry")
    field = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    instruction = DecodedInstruction(
        pc=1,
        word=15,
        opcode=15,
        name="GETTABLEKS",
        a=1,
        b=0,
        c=0,
        d=0,
        e=0,
        aux=0,
    )

    class FakeSSA:
        def value_at_use(self, pc: int, register: int) -> SSAValue | None:
            if pc == 1 and register == 0:
                return base
            return None

    class FakeLifter:
        def __init__(self) -> None:
            self.ssa = FakeSSA()
            self.instruction_by_pc = {1: instruction}
            self.inline_expressions: dict[SSAValue, NameExpr] = {}
            self.declared = {"record"}

        def _table_key(self, _instruction: DecodedInstruction) -> str:
            return "Stats"

    def fallback(_lifter: object, register: int, _pc: int) -> NameExpr:
        assert register == 0
        return NameExpr("record")

    expression = _access_expression_for_value(  # type: ignore[arg-type]
        FakeLifter(),
        field,
        fallback,  # type: ignore[arg-type]
    )
    assert expression is not None
    assert render_expression(expression) == "record.Stats"
