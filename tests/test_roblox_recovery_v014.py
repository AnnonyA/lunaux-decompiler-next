from __future__ import annotations

from lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto
from lunaux.backends.lifter import decompile_module
from lunaux.backends.opcodes import opcode_names


def _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | (b << 16) | (c << 24)


def _ad(name: str, *, a: int = 0, d: int = 0) -> int:
    opcode = opcode_names().index(name)
    return opcode | (a << 8) | ((d & 0xFFFF) << 16)


def _proto(
    proto_id: int,
    code: tuple[int, ...],
    constants: tuple[LuauConstant, ...] = (),
    *,
    children: tuple[int, ...] = (),
    params: int = 0,
    upvalues: int = 0,
    upvalue_names: tuple[str | None, ...] = (),
    stack: int = 8,
    name: str | None = None,
) -> LuauProto:
    return LuauProto(
        proto_id=proto_id,
        max_stack_size=stack,
        num_params=params,
        num_upvalues=upvalues,
        is_vararg=False,
        flags=0,
        type_info=b"",
        code=code,
        constants=constants,
        child_proto_ids=children,
        line_defined=1,
        debug_name=name or f"proto_{proto_id}",
        line_info=(),
        locals=(),
        upvalue_names=upvalue_names,
        feedback_pcs=(),
        cost=None,
    )


def _module(*protos: LuauProto, main: int) -> LuauBytecodeModule:
    return LuauBytecodeModule(
        version=13,
        types_version=3,
        strings=(),
        protos=protos,
        main_proto_id=main,
        bytes_consumed=0,
        trailing_bytes=0,
    )


def test_inlines_event_callback_and_recovers_connection() -> None:
    child_constants = (LuauConstant("string", "print", 3),)
    child = _proto(
        0,
        (
            _abc("GETGLOBAL", a=1),
            0,
            _abc("MOVE", a=2, b=0),
            _abc("CALL", a=1, b=2, c=1),
            _abc("RETURN", a=0, b=1),
        ),
        child_constants,
        params=1,
        stack=3,
        name="onActivated",
    )
    main_constants = (
        LuauConstant("string", "button", 3),
        LuauConstant("string", "Activated", 3),
        LuauConstant("string", "Connect", 3),
    )
    main = _proto(
        1,
        (
            _abc("GETGLOBAL", a=0),
            0,
            _abc("GETTABLEKS", a=1, b=0),
            1,
            _ad("NEWCLOSURE", a=3, d=0),
            _abc("NAMECALL", a=1, b=1),
            2,
            _abc("CALL", a=1, b=3, c=2),
            _abc("RETURN", a=0, b=1),
        ),
        main_constants,
        children=(0,),
        stack=4,
        name="main",
    )

    output = decompile_module(
        _module(child, main, main=1),
        {},
        "event.luau",
    )

    assert "-- Roblox events: button.Activated:Connect" in output
    assert ":Connect(function(input: InputObject)" in output
    assert "print(input)" in output
    assert "RBXScriptConnection" in output
    assert "local function onActivated" not in output


def test_inlines_task_delay_callback_in_its_callback_slot() -> None:
    child = _proto(
        0,
        (_abc("RETURN", a=0, b=1),),
        name="delayed",
    )
    constants = (
        LuauConstant("string", "task", 3),
        LuauConstant("string", "delay", 3),
    )
    main = _proto(
        1,
        (
            _abc("GETGLOBAL", a=0),
            0,
            _abc("GETTABLEKS", a=1, b=0),
            1,
            _ad("LOADN", a=2, d=2),
            _ad("NEWCLOSURE", a=3, d=0),
            _abc("CALL", a=1, b=3, c=1),
            _abc("RETURN", a=0, b=1),
        ),
        constants,
        children=(0,),
        stack=4,
    )

    output = decompile_module(_module(child, main, main=1), {}, "delay.luau")

    assert "delay(" in output
    assert ", function()" in output
    assert "local function delayed" not in output


def test_module_table_exports_inline_function_fields() -> None:
    child = _proto(
        0,
        (
            _ad("LOADN", a=0, d=1),
            _abc("RETURN", a=0, b=2),
        ),
        name="start",
    )
    constants = (LuauConstant("string", "Start", 3),)
    main = _proto(
        1,
        (
            _abc("NEWTABLE", a=0),
            0,
            _ad("NEWCLOSURE", a=1, d=0),
            _abc("SETTABLEKS", a=1, b=0),
            0,
            _abc("RETURN", a=0, b=2),
        ),
        constants,
        children=(0,),
        stack=2,
    )

    output = decompile_module(_module(child, main, main=1), {}, "module.luau")

    assert "-- Roblox ModuleScript export: table" in output
    assert "function module.Start(): number" in output
    assert "Start = function()" not in output
    assert "return 1" in output
    assert "local function start" not in output


def test_require_dependency_uses_module_path_for_name_and_report() -> None:
    constants = (
        LuauConstant("string", "require", 3),
        LuauConstant("string", "script", 3),
        LuauConstant("string", "Parent", 3),
        LuauConstant("string", "InventoryService", 3),
    )
    main = _proto(
        0,
        (
            _abc("GETGLOBAL", a=0),
            0,
            _abc("GETGLOBAL", a=1),
            1,
            _abc("GETTABLEKS", a=1, b=1),
            2,
            _abc("GETTABLEKS", a=1, b=1),
            3,
            _abc("CALL", a=0, b=2, c=2),
            _abc("RETURN", a=0, b=2),
        ),
        constants,
        stack=2,
        name="main",
    )

    output = decompile_module(_module(main, main=0), {}, "consumer.luau")

    assert "-- Roblox module dependencies: script.Parent.InventoryService" in output
    assert "return require(script.Parent.InventoryService)" in output
    assert "local inventoryService" not in output
    assert "-- Roblox ModuleScript export: module" in output


def test_shared_event_callback_keeps_named_function() -> None:
    child = _proto(
        0,
        (_abc("RETURN", a=0, b=1),),
        name="sharedCallback",
    )
    constants = (
        LuauConstant("string", "signalA", 3),
        LuauConstant("string", "signalB", 3),
        LuauConstant("string", "Connect", 3),
    )
    main = _proto(
        1,
        (
            _ad("NEWCLOSURE", a=4, d=0),
            _abc("GETGLOBAL", a=0),
            0,
            _abc("NAMECALL", a=0, b=0),
            2,
            _abc("MOVE", a=2, b=4),
            _abc("CALL", a=0, b=3, c=1),
            _abc("GETGLOBAL", a=0),
            1,
            _abc("NAMECALL", a=0, b=0),
            2,
            _abc("MOVE", a=2, b=4),
            _abc("CALL", a=0, b=3, c=1),
            _abc("RETURN", a=0, b=1),
        ),
        constants,
        children=(0,),
        stack=5,
    )

    output = decompile_module(_module(child, main, main=1), {}, "shared.luau")

    assert "local function sharedCallback()" in output
    assert output.count(":Connect(sharedCallback)") == 2
    assert ":Connect(function()" not in output


def test_callback_capture_is_bound_inside_anonymous_function() -> None:
    child = _proto(
        0,
        (
            _abc("GETUPVAL", a=0, b=0),
            _abc("RETURN", a=0, b=2),
        ),
        upvalues=1,
        upvalue_names=("amount",),
        name="captured",
    )
    constants = (
        LuauConstant("string", "task", 3),
        LuauConstant("string", "spawn", 3),
    )
    main = _proto(
        1,
        (
            _ad("LOADN", a=0, d=5),
            _abc("GETGLOBAL", a=1),
            0,
            _abc("GETTABLEKS", a=1, b=1),
            1,
            _ad("NEWCLOSURE", a=2, d=0),
            _abc("CAPTURE", a=0, b=0),
            _abc("CALL", a=1, b=2, c=1),
            _abc("RETURN", a=0, b=1),
        ),
        constants,
        children=(0,),
        stack=3,
    )

    output = decompile_module(_module(child, main, main=1), {}, "capture.luau")

    assert "spawn(function()" in output
    assert "-- upvalues: num1" in output
    assert "return num1" in output
    assert "-- capture" not in output


def test_callback_and_module_options_can_be_disabled() -> None:
    child = _proto(
        0,
        (_abc("RETURN", a=0, b=1),),
        name="callback",
    )
    constants = (
        LuauConstant("string", "signal", 3),
        LuauConstant("string", "Connect", 3),
    )
    main = _proto(
        1,
        (
            _abc("GETGLOBAL", a=0),
            0,
            _ad("NEWCLOSURE", a=2, d=0),
            _abc("NAMECALL", a=0, b=0),
            1,
            _abc("CALL", a=0, b=3, c=1),
            _abc("RETURN", a=0, b=1),
        ),
        constants,
        children=(0,),
        stack=3,
    )

    output = decompile_module(
        _module(child, main, main=1),
        {
            "RecoverRobloxEvents": False,
            "InlineRobloxCallbacks": False,
            "RecoverRobloxModules": False,
        },
        "disabled.luau",
    )

    assert "-- Roblox events:" not in output
    assert "local function callback()" in output
    assert ":Connect(callback)" in output
