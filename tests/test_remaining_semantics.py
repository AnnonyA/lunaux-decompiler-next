from __future__ import annotations

from types import SimpleNamespace

from lunaux.backends.ast import NameExpr, render_expression
from lunaux.backends.opcodes import DecodedInstruction
from lunaux.backends.remaining_semantics import (
    _access_expression_for_value,
    _access_value_can_reconstruct,
    _fresh_lifetime_name,
    _nonconflicting_generated_name,
    _repair_access_definition_expression,
    _rewrite_short_circuit_boolean_ladders,
    _stable_value_expression,
)
from lunaux.backends.ssa import SSAValue


def _instruction(pc: int, name: str) -> DecodedInstruction:
    return DecodedInstruction(
        pc=pc,
        word=0,
        opcode=0,
        name=name,
        a=0,
        b=0,
        c=0,
        d=0,
        e=0,
        aux=None,
    )


def test_generated_name_respects_future_debug_binding() -> None:
    assert (
        _nonconflicting_generated_name(
            "value",
            frozenset({"value", "index"}),
            {"value2"},
        )
        == "value3"
    )


def test_reconstructs_elided_field_access_from_stable_ssa_base() -> None:
    base = SSAValue(register=0, version=1, origin_pc=0, kind="instruction")
    field = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    base_instruction = _instruction(0, "NEWTABLE")
    field_instruction = DecodedInstruction(
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
            self.instruction_by_pc = {
                0: base_instruction,
                1: field_instruction,
            }
            self.inline_expressions: dict[SSAValue, NameExpr] = {}
            self.declared = {"record"}
            self._remaining_materialized_value_names = {base: "record"}

        def _table_key(self, _instruction: DecodedInstruction) -> str:
            return "Stats"

    expression = _access_expression_for_value(  # type: ignore[arg-type]
        FakeLifter(),
        field,
    )
    assert expression is not None
    assert render_expression(expression) == "record.Stats"


def test_stable_value_expression_reconstructs_nested_table_access_chain() -> None:
    root = SSAValue(register=0, version=1, origin_pc=0, kind="instruction")
    stats = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    score = SSAValue(register=2, version=1, origin_pc=2, kind="instruction")

    root_instruction = _instruction(0, "NEWTABLE")
    stats_instruction = DecodedInstruction(
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
    score_instruction = DecodedInstruction(
        pc=2,
        word=15,
        opcode=15,
        name="GETTABLEKS",
        a=2,
        b=1,
        c=0,
        d=0,
        e=0,
        aux=1,
    )
    consumer = _instruction(3, "ADD")

    class FakeSSA:
        def value_at_use(self, pc: int, register: int) -> SSAValue | None:
            if (pc, register) == (1, 0):
                return root
            if (pc, register) == (2, 1):
                return stats
            return None

    class FakeLifter:
        def __init__(self) -> None:
            self.ssa = FakeSSA()
            self.proto = SimpleNamespace(locals=(), num_params=0)
            self.instruction_by_pc = {
                0: root_instruction,
                1: stats_instruction,
                2: score_instruction,
                3: consumer,
            }
            self.instructions = (
                root_instruction,
                stats_instruction,
                score_instruction,
                consumer,
            )
            self.analysis = SimpleNamespace(
                block_for_pc={0: 0, 1: 0, 2: 0, 3: 0},
            )
            self.inline_expressions: dict[SSAValue, NameExpr] = {}
            self.declared = {"data"}
            self._remaining_materialized_value_names = {root: "data"}

        def _forced_value_names(self) -> dict[SSAValue, str]:
            return {}

        def _table_key(self, instruction: DecodedInstruction) -> str:
            return "Stats" if instruction.pc == 1 else "Score"

    expression = _stable_value_expression(  # type: ignore[arg-type]
        FakeLifter(),
        score,
        3,
        frozenset(),
    )
    assert expression is not None
    assert render_expression(expression) == "data.Stats.Score"


def test_repairs_collapsed_gettable_definition_at_its_origin() -> None:
    base = SSAValue(register=0, version=1, origin_pc=0, kind="instruction")
    field = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    base_instruction = _instruction(0, "NEWTABLE")
    field_instruction = DecodedInstruction(
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
            self.instruction_by_pc = {
                0: base_instruction,
                1: field_instruction,
            }
            self.inline_expressions: dict[SSAValue, NameExpr] = {}
            self.declared = {"record"}
            self._remaining_materialized_value_names = {base: "record"}

        def _table_key(self, _instruction: DecodedInstruction) -> str:
            return "Stats"

    expression = _repair_access_definition_expression(  # type: ignore[arg-type]
        FakeLifter(),
        field,
        NameExpr("Stats"),
    )
    assert render_expression(expression) == "record.Stats"


def test_materialized_access_alias_wins_over_replaying_its_origin() -> None:
    field = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    lifter = SimpleNamespace(
        inline_expressions={},
        _remaining_materialized_value_names={field: "fieldAlias"},
    )

    expression = _stable_value_expression(  # type: ignore[arg-type]
        lifter,
        field,
        3,
        frozenset(),
    )
    assert expression == NameExpr("fieldAlias")


def test_table_access_replay_stays_in_one_unmutated_basic_block() -> None:
    value = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    definition = _instruction(1, "GETTABLEKS")
    harmless = _instruction(2, "ADD")
    consumer = _instruction(3, "GETTABLEKS")
    lifter = SimpleNamespace(
        instruction_by_pc={1: definition, 2: harmless, 3: consumer},
        instructions=(definition, harmless, consumer),
        analysis=SimpleNamespace(block_for_pc={1: 0, 2: 0, 3: 0}),
    )

    assert _access_value_can_reconstruct(lifter, value, 3)  # type: ignore[arg-type]


def test_move_is_not_a_top_level_table_replay_candidate() -> None:
    value = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    definition = _instruction(1, "MOVE")
    consumer = _instruction(2, "ADD")
    lifter = SimpleNamespace(
        instruction_by_pc={1: definition, 2: consumer},
        instructions=(definition, consumer),
        analysis=SimpleNamespace(block_for_pc={1: 0, 2: 0}),
    )

    assert not _access_value_can_reconstruct(lifter, value, 2)  # type: ignore[arg-type]


def test_table_access_replay_rejects_intervening_mutation() -> None:
    value = SSAValue(register=1, version=1, origin_pc=1, kind="instruction")
    definition = _instruction(1, "GETTABLEKS")
    mutation = _instruction(2, "SETTABLEKS")
    consumer = _instruction(3, "GETTABLEKS")
    lifter = SimpleNamespace(
        instruction_by_pc={1: definition, 2: mutation, 3: consumer},
        instructions=(definition, mutation, consumer),
        analysis=SimpleNamespace(block_for_pc={1: 0, 2: 0, 3: 0}),
    )

    assert not _access_value_can_reconstruct(lifter, value, 3)  # type: ignore[arg-type]


def test_boolean_ladder_rewrite_hoists_debug_local_and_restores_edges() -> None:
    source = """local flag7
if left then
    local selected = not right
    if not selected then
    end
    selected = right
    if selected then
        selected = 10 < value
    end
end
print(selected, left, right)
"""

    assert _rewrite_short_circuit_boolean_ladders(source) == """local flag7
local selected = (left and not (right)) or (right and (10 < value))
print(selected, left, right)
"""


def test_boolean_ladder_rewrite_reuses_predeclared_result() -> None:
    source = """local flag7
if flag then
    flag7 = not flag4
    if not flag7 then
    end
    flag7 = flag4
    if flag7 then
        flag7 = 10 < value
    end
end
"""

    assert _rewrite_short_circuit_boolean_ladders(source) == """local flag7
flag7 = (flag and not (flag4)) or (flag4 and (10 < value))
"""


def test_capture_lifetime_name_never_reuses_reference_identifier() -> None:
    class FakeLifter:
        def __init__(self) -> None:
            self.declared = {"capturedValue", "value4"}
            self.register_names = {3: "capturedValue"}
            self._remaining_materialized_value_names: dict[SSAValue, str] = {}

        def _forced_value_names(self) -> dict[SSAValue, str]:
            return {}

    name = _fresh_lifetime_name(  # type: ignore[arg-type]
        FakeLifter(),
        3,
        frozenset({"capturedValue"}),
    )
    assert name == "value4_2"
