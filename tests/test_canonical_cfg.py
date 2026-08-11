from __future__ import annotations

from lunaux.backends.advanced_loops import analyze_advanced_loops
from lunaux.backends.canonical_cfg import build_canonical_cfg_plan
from lunaux.backends.opcodes import DecodedInstruction, opcode_names
from lunaux.backends.ssa import build_ssa
from lunaux.backends.state_machine import StateMachinePlan
from lunaux.backends.structuring import build_structured_recovery


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
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
        c=0,
        d=d,
        e=0,
        aux=None,
    )


def _plan(instructions: tuple[DecodedInstruction, ...]):
    code_size = max(item.pc + item.size for item in instructions)
    program = build_ssa(instructions, code_size)
    structured = build_structured_recovery(program)
    loops = analyze_advanced_loops(program.analysis, instructions)
    return build_canonical_cfg_plan(
        program.analysis,
        instructions,
        structured,
        loops,
        StateMachinePlan.empty(),
    )


def test_canonical_cfg_owns_existing_short_circuit_region() -> None:
    instructions = (
        _instruction(0, "JUMPIF", a=0, d=2),
        _instruction(1, "JUMP", d=3),
        _instruction(2, "NOP"),
        _instruction(3, "JUMPIF", a=1, d=3),
        _instruction(4, "JUMP", d=0),
        _instruction(5, "LOADN", a=2, d=1),
        _instruction(6, "JUMP", d=1),
        _instruction(7, "LOADN", a=2, d=0),
        _instruction(8, "RETURN", a=2, b=2),
    )
    plan = _plan(instructions)

    assert plan.structured.boolean_chains
    assert any(region.kind == "short-circuit" for region in plan.regions)


def test_canonical_cfg_proves_shared_join_elseif_chain() -> None:
    instructions = (
        _instruction(0, "JUMPIFNOT", a=0, d=2),
        _instruction(1, "LOADN", a=2, d=1),
        _instruction(2, "JUMP", d=3),
        _instruction(3, "JUMPIFNOT", a=1, d=2),
        _instruction(4, "LOADN", a=3, d=2),
        _instruction(5, "JUMP", d=0),
        _instruction(6, "RETURN", a=0, b=1),
    )
    plan = _plan(instructions)

    outer = next(region for region in plan.at(0) if region.kind == "if-elseif-else")
    assert outer.exit == 6
    assert outer.children == (3,)
    assert "nested condition shares join" in outer.evidence


def test_canonical_cfg_keeps_loop_targets_from_existing_authority() -> None:
    instructions = (
        _instruction(0, "JUMPIF", a=0, d=5),
        _instruction(1, "LOADN", a=2, d=1),
        _instruction(2, "JUMPIF", a=1, d=3),
        _instruction(3, "JUMPIF", a=2, d=-4),
        _instruction(4, "LOADN", a=3, d=5),
        _instruction(5, "JUMPBACK", d=-6),
        _instruction(6, "RETURN", a=0, b=1),
    )
    plan = _plan(instructions)
    loop = next(region for region in plan.regions if region.kind == "while")

    assert loop.continue_target == 0
    assert loop.break_target == 6
    assert plan.advanced_loops.actions[2].kind == "break"
