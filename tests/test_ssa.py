from __future__ import annotations

from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import build_ssa, render_ssa


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
    aux: int | None = None,
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
        aux=aux,
    )


def test_renames_diamond_definitions_and_resolves_phi_operands() -> None:
    instructions = [
        _instruction(0, "JUMPIF", a=2, d=2),
        _instruction(1, "LOADN", a=0, d=1),
        _instruction(2, "JUMP", d=1),
        _instruction(3, "LOADN", a=0, d=2),
        _instruction(4, "RETURN", a=0, b=2),
    ]

    program = build_ssa(instructions, code_size=5)

    assert len(program.phis) == 1
    phi = program.phis[0]
    assert (phi.block, phi.register, phi.result.kind) == (4, 0, "phi")
    assert set(phi.operands) == {1, 3}
    assert {value.origin_pc for value in phi.operands.values()} == {1, 3}
    assert program.value_at_use(4, 0) == phi.result
    assert program.value_at_use(0, 2) == program.entry_values[2]

    left = program.value_defined_at(1, 0)
    right = program.value_defined_at(3, 0)
    assert left is not None and right is not None
    assert left != right
    assert left.version != right.version


def test_loop_phi_combines_preheader_and_latch_values() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=3),
        _instruction(1, "JUMPIFNOT", a=0, d=3),
        _instruction(2, "LOADN", a=1, d=1),
        _instruction(3, "SUB", a=0, b=0, c=1),
        _instruction(4, "JUMPBACK", d=-4),
        _instruction(5, "RETURN", a=0, b=2),
    ]

    program = build_ssa(instructions, code_size=6)

    phi = next(item for item in program.phis if item.block == 1 and item.register == 0)
    assert phi.operands[0] == program.value_defined_at(0, 0)
    assert phi.operands[2] == program.value_defined_at(3, 0)
    assert program.value_at_use(1, 0) == phi.result
    assert program.value_at_use(3, 0) == phi.result


def test_creates_entry_values_for_registers_used_before_definition() -> None:
    instructions = [
        _instruction(0, "MOVE", a=0, b=5),
        _instruction(1, "RETURN", a=0, b=2),
    ]

    program = build_ssa(instructions, code_size=2)

    entry = program.entry_values[5]
    assert (entry.register, entry.version, entry.origin_pc, entry.kind) == (
        5,
        0,
        None,
        "entry",
    )
    assert program.value_at_use(0, 5) == entry
    assert program.value_at_use(1, 0) == program.value_defined_at(0, 0)


def test_reports_single_use_instruction_values() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=42),
        _instruction(1, "RETURN", a=0, b=2),
    ]

    program = build_ssa(instructions, code_size=2)
    value = program.value_defined_at(0, 0)

    assert value is not None
    assert program.uses_of(value) == 1
    assert value in program.single_use_instruction_values()


def test_renders_versioned_values_and_phi_operands() -> None:
    instructions = [
        _instruction(0, "JUMPIF", a=2, d=2),
        _instruction(1, "LOADN", a=0, d=1),
        _instruction(2, "JUMP", d=1),
        _instruction(3, "LOADN", a=0, d=2),
        _instruction(4, "RETURN", a=0, b=2),
    ]

    rendered = render_ssa(build_ssa(instructions, code_size=5))

    assert "B4:" in rendered
    assert "phi(B1:" in rendered
    assert "B3:" in rendered
    assert "RETURN" in rendered
