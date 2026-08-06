from __future__ import annotations

from lunaux.backends import SSAMultiUse, SSAMultiValue, SSAMultiValuePlan
from lunaux.backends.opcodes import decode_words, opcode_names
from lunaux.backends.ssa import build_ssa, render_ssa


def _opcode(name: str) -> int:
    return opcode_names().index(name)


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    return _opcode(name) | (a << 8) | (b << 16) | (c << 24)


def _program(*words: int):
    instructions = tuple(decode_words(tuple(words)))
    return build_ssa(instructions, len(words))


def test_multret_call_flows_into_return_with_fixed_prefix() -> None:
    program = _program(
        _abc("CALL", a=2, b=1, c=0),
        _abc("RETURN", a=0, b=0),
    )

    value = program.multi_value_at(0)
    use = program.multi_use_at(1)

    assert isinstance(value, SSAMultiValue)
    assert value.kind == "call"
    assert value.base_register == 2
    assert isinstance(use, SSAMultiUse)
    assert use.kind == "return"
    assert use.value == value
    assert use.prefix_registers == (0, 1)
    assert program.multi_values.unresolved_values == ()

    rendered = render_ssa(program)
    assert "T0=MULTRET<call> R2..top" in rendered
    assert "MULTRET return consumes T0 after [R0, R1]" in rendered


def test_multret_varargs_feed_open_call_and_chained_return() -> None:
    program = _program(
        _abc("GETVARARGS", a=2, b=0),
        _abc("CALL", a=0, b=0, c=0),
        _abc("RETURN", a=0, b=0),
    )

    varargs = program.multi_value_at(0)
    argument_use = program.multi_use_at(1)
    call_result = program.multi_value_at(1)
    return_use = program.multi_use_at(2)

    assert varargs is not None and varargs.kind == "varargs"
    assert argument_use is not None and argument_use.kind == "arguments"
    assert argument_use.value == varargs
    assert argument_use.prefix_registers == (1,)
    assert call_result is not None and call_result.kind == "call"
    assert return_use is not None and return_use.kind == "return"
    assert return_use.value == call_result
    assert return_use.prefix_registers == ()
    assert program.multi_values.unresolved_values == ()


def test_multret_survives_only_explicit_passthrough_instructions() -> None:
    passthrough = _program(
        _abc("CALL", a=0, b=1, c=0),
        _abc("NOP"),
        _abc("RETURN", a=0, b=0),
    )
    clobbered = _program(
        _abc("CALL", a=0, b=1, c=0),
        _abc("LOADN", a=1),
        _abc("RETURN", a=0, b=0),
    )

    assert passthrough.multi_use_at(2) is not None
    assert clobbered.multi_use_at(2) is None
    unresolved = clobbered.multi_values.unresolved_values
    assert len(unresolved) == 1
    assert unresolved[0].origin_pc == 0


def test_multret_public_empty_plan_is_immutable_and_empty() -> None:
    plan = SSAMultiValuePlan.empty()

    assert plan.values == ()
    assert plan.uses == ()
    assert plan.value_at(0) is None
    assert plan.use_at(0) is None
    assert plan.unresolved_values == ()
