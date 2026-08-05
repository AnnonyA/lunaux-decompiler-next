from __future__ import annotations

from lunaux.backends.analysis import (
    analyze_control_flow,
    register_access,
    render_cfg_dot,
    reverse_postorder,
    strongly_connected_components,
)
from lunaux.backends.opcodes import DecodedInstruction, opcode_names


def _instruction(
    pc: int,
    name: str,
    *,
    a: int = 0,
    b: int = 0,
    c: int = 0,
    d: int = 0,
    e: int = 0,
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
        e=e,
        aux=aux,
    )


def test_builds_diamond_dominators_def_use_and_phi() -> None:
    instructions = [
        _instruction(0, "JUMPIF", a=2, d=2),
        _instruction(1, "LOADN", a=0, d=1),
        _instruction(2, "JUMP", d=1),
        _instruction(3, "LOADN", a=0, d=2),
        _instruction(4, "RETURN", a=0, b=2),
    ]

    analysis = analyze_control_flow(instructions, code_size=5)

    assert [block.start_pc for block in analysis.blocks] == [0, 1, 3, 4]
    assert analysis.block_by_start[0].successors == frozenset({1, 3})
    assert analysis.dominators[4] == frozenset({0, 4})
    assert analysis.immediate_dominators[4] == 0
    assert analysis.immediate_postdominators[0] == 4
    assert analysis.dominance_frontiers[1] == frozenset({4})
    assert analysis.dominance_frontiers[3] == frozenset({4})
    assert analysis.def_use.reaching_definitions[(4, 0)] == frozenset({1, 3})
    assert analysis.live_in[4] == frozenset({0})

    assert len(analysis.branches) == 1
    branch = analysis.branches[0]
    assert branch.header == 0
    assert branch.fallthrough == 1
    assert branch.taken == 3
    assert branch.join == 4

    assert len(analysis.phi_nodes) == 1
    phi = analysis.phi_nodes[0]
    assert phi.block == 4
    assert phi.register == 0
    assert phi.predecessors == frozenset({1, 3})


def test_finds_natural_loop_and_strongly_connected_component() -> None:
    instructions = [
        _instruction(0, "LOADN", a=0, d=3),
        _instruction(1, "JUMPIFNOT", a=0, d=3),
        _instruction(2, "LOADN", a=1, d=1),
        _instruction(3, "SUB", a=0, b=0, c=1),
        _instruction(4, "JUMPBACK", d=-4),
        _instruction(5, "RETURN", a=0, b=2),
    ]

    analysis = analyze_control_flow(instructions, code_size=6)

    assert reverse_postorder(analysis)[0] == 0
    assert len(analysis.loops) == 1
    loop = analysis.loops[0]
    assert (loop.header, loop.latch) == (1, 2)
    assert loop.body == frozenset({1, 2})
    assert loop.exits == frozenset({(1, 5)})
    assert frozenset({1, 2}) in strongly_connected_components(analysis)


def test_tracks_register_access_for_calls_namecalls_and_open_returns() -> None:
    call = register_access(_instruction(7, "CALL", a=3, b=4, c=3))
    assert call.uses == frozenset({3, 4, 5, 6})
    assert call.definitions == frozenset({3, 4})

    namecall = register_access(_instruction(8, "NAMECALL", a=5, b=2, aux=0))
    assert namecall.uses == frozenset({2})
    assert namecall.definitions == frozenset({5, 6})

    open_return = register_access(_instruction(10, "RETURN", a=4, b=0))
    assert open_return.uses == frozenset({4})


def test_preserves_aux_word_instruction_boundaries() -> None:
    instructions = [
        _instruction(0, "GETTABLEKS", a=0, b=1, aux=0),
        _instruction(2, "RETURN", a=0, b=2),
    ]

    analysis = analyze_control_flow(instructions, code_size=3)

    assert len(analysis.blocks) == 1
    assert [item.pc for item in analysis.blocks[0].instructions] == [0, 2]
    assert analysis.block_for_pc[2] == 0


def test_loadb_skip_has_only_the_jump_successor() -> None:
    instructions = [
        _instruction(0, "LOADB", a=0, b=1, c=1),
        _instruction(1, "LOADN", a=1, d=99),
        _instruction(2, "RETURN", a=0, b=2),
    ]

    analysis = analyze_control_flow(instructions, code_size=3)

    assert analysis.block_by_start[0].successors == frozenset({2})
    assert 1 not in analysis.reachable


def test_renders_graphviz_with_edges_loop_and_phi_annotations() -> None:
    instructions = [
        _instruction(0, "JUMPIF", a=2, d=2),
        _instruction(1, "LOADN", a=0, d=1),
        _instruction(2, "JUMP", d=1),
        _instruction(3, "LOADN", a=0, d=2),
        _instruction(4, "RETURN", a=0, b=2),
    ]

    rendered = render_cfg_dot(analyze_control_flow(instructions, code_size=5))

    assert rendered.startswith("digraph luau_cfg")
    assert "B0 -> B1;" in rendered
    assert "B0 -> B3;" in rendered
    assert "phi R0" in rendered
