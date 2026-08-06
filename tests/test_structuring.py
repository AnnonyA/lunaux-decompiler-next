from __future__ import annotations

from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import build_ssa
from lunaux.backends.structuring import build_structured_recovery


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
) -> DecodedInstruction:
    opcode = opcode_names().index(name)
    return DecodedInstruction(
        pc=pc,
        word=opcode,
        opcode=opcode,
        name=name,
        a=a,
        b=b,
        c=c,
        d=d,
        e=0,
        aux=None,
    )


def test_recovers_simple_phi_diamond_as_if_expression_region() -> None:
    instructions = [
        _instruction(0, "JUMPIFNOT", a=0, d=2),
        _instruction(1, "LOADN", a=1, d=10),
        _instruction(2, "JUMP", d=1),
        _instruction(3, "LOADN", a=1, d=20),
        _instruction(4, "RETURN", a=1, b=2),
    ]
    program = build_ssa(instructions, code_size=5)
    plan = build_structured_recovery(program)

    assert len(plan.phi_regions) == 1
    region = plan.phi_regions[0]
    assert region.condition_pc == 0
    assert region.join_pc == 4
    assert len(region.assignments) == 1
    assert region.assignments[0].result.kind == "phi"
    assert {value.origin_pc for value in region.captured_values} == {1, 3}
    assert region.skipped_pcs == frozenset({1, 2, 3})


def test_combines_consecutive_failure_edges_with_and() -> None:
    instructions = [
        _instruction(0, "JUMPIFNOT", a=0, d=3),
        _instruction(1, "JUMPIFNOT", a=1, d=2),
        _instruction(2, "LOADN", a=2, d=1),
        _instruction(3, "JUMP", d=1),
        _instruction(4, "LOADN", a=2, d=0),
        _instruction(5, "RETURN", a=2, b=2),
    ]
    program = build_ssa(instructions, code_size=6)
    plan = build_structured_recovery(program)

    assert len(plan.boolean_chains) == 1
    chain = plan.boolean_chains[0]
    assert chain.operator == "and"
    assert chain.condition_pcs == (0, 1)
    assert chain.body_start == 2
    assert chain.false_start == 4
    assert chain.join == 5
    assert chain.has_else


def test_combines_trivial_success_jumps_with_or() -> None:
    instructions = [
        _instruction(0, "JUMPIF", a=0, d=2),
        _instruction(1, "JUMP", d=3),
        _instruction(2, "NOP"),
        _instruction(3, "JUMPIF", a=1, d=2),
        _instruction(4, "JUMP", d=0),
        _instruction(5, "LOADN", a=2, d=1),
        _instruction(6, "LOADN", a=2, d=0),
        _instruction(7, "RETURN", a=2, b=2),
    ]
    program = build_ssa(instructions, code_size=8)
    plan = build_structured_recovery(program)

    assert len(plan.boolean_chains) == 1
    chain = plan.boolean_chains[0]
    assert chain.operator == "or"
    assert chain.condition_pcs == (0, 3)
    assert chain.body_start == 5
    assert chain.false_start == 6
    assert chain.join == 7
    assert {1, 3, 4}.issubset(chain.skipped_pcs)
