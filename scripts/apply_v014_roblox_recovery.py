from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        if new in text:
            return
        raise RuntimeError(f"marker not found in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.lstrip("\n"), encoding="utf-8")


write(
    ROOT / "src/lunaux/backends/roblox_recovery.py",
    '\nfrom __future__ import annotations\n\nimport re\nfrom collections import Counter\nfrom collections.abc import Mapping, Sequence\nfrom dataclasses import dataclass\nfrom types import MappingProxyType\nfrom typing import Final, Literal\n\nfrom lunaux.backends.bytecode import LuauBytecodeModule, LuauProto\nfrom lunaux.backends.opcodes import DecodedInstruction, decode_words\nfrom lunaux.backends.ssa import SSAInstruction, SSAProgram, SSAValue, build_ssa\n\n_EVENT_METHODS: Final[frozenset[str]] = frozenset(\n    {"Connect", "ConnectParallel", "Once", "Wait"}\n)\n_METHOD_CALLBACK_ARGUMENTS: Final[dict[str, tuple[int, ...]]] = {\n    "Connect": (0,),\n    "ConnectParallel": (0,),\n    "Once": (0,),\n    "BindAction": (1,),\n    "BindActionAtPriority": (1,),\n    "BindToRenderStep": (2,),\n    "Subscribe": (0,),\n}\n_FUNCTION_CALLBACK_ARGUMENTS: Final[dict[str, tuple[int, ...]]] = {\n    "coroutine.create": (0,),\n    "coroutine.wrap": (0,),\n    "pcall": (0,),\n    "table.sort": (1,),\n    "task.defer": (0,),\n    "task.delay": (1,),\n    "task.spawn": (0,),\n    "xpcall": (0,),\n}\n_FLOW_BARRIERS: Final[frozenset[str]] = frozenset(\n    {"CALL", "CALLFB", "RETURN", "JUMP", "JUMPBACK", "JUMPX"}\n)\n_IDENTIFIER_CHUNK: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")\n\n\n@dataclass(frozen=True, slots=True)\nclass InlineCallbackPlan:\n    proto_by_value: Mapping[SSAValue, int]\n    capture_pcs: frozenset[int]\n\n    @classmethod\n    def empty(cls) -> InlineCallbackPlan:\n        return cls(MappingProxyType(dict[SSAValue, int]()), frozenset())\n\n\n@dataclass(frozen=True, slots=True)\nclass RobloxModuleDependency:\n    path: str\n    name: str\n    pc: int\n\n\n@dataclass(frozen=True, slots=True)\nclass RobloxEventBinding:\n    signal: str\n    method: str\n    pc: int\n\n    @property\n    def display(self) -> str:\n        return f"{self.signal}:{self.method}"\n\n\n@dataclass(frozen=True, slots=True)\nclass RobloxRecoveryReport:\n    events: tuple[RobloxEventBinding, ...]\n    dependencies: tuple[RobloxModuleDependency, ...]\n    export_kind: Literal["table", "function", "module", "value"] | None\n\n\ndef closure_proto_id(\n    proto: LuauProto,\n    instruction: DecodedInstruction,\n) -> int | None:\n    if (\n        instruction.name == "NEWCLOSURE"\n        and 0 <= instruction.d < len(proto.child_proto_ids)\n    ):\n        return proto.child_proto_ids[instruction.d]\n    if instruction.name != "DUPCLOSURE":\n        return None\n    if not 0 <= instruction.d < len(proto.constants):\n        return None\n    constant = proto.constants[instruction.d]\n    if constant.kind != "closure" or not isinstance(constant.value, int):\n        return None\n    return constant.value\n\n\ndef _constant_string(proto: LuauProto, index: int) -> str | None:\n    if not 0 <= index < len(proto.constants):\n        return None\n    constant = proto.constants[index]\n    if constant.kind != "string" or not isinstance(constant.value, str):\n        return None\n    return constant.value\n\n\ndef _import_path(proto: LuauProto, aux: int | None) -> tuple[str, ...]:\n    if aux is None:\n        return ()\n    count = aux >> 30\n    indices = ((aux >> 20) & 1023, (aux >> 10) & 1023, aux & 1023)\n    names: list[str] = []\n    for position in range(min(count, 3)):\n        name = _constant_string(proto, indices[position])\n        if name is None:\n            return ()\n        names.append(name)\n    return tuple(names)\n\n\ndef _namecall_for_call(\n    proto: LuauProto,\n    instructions: Sequence[DecodedInstruction],\n    instruction: DecodedInstruction,\n) -> tuple[DecodedInstruction, str] | None:\n    previous_by_next_pc = {\n        item.pc + item.size: item for item in instructions\n    }\n    candidate = previous_by_next_pc.get(instruction.pc)\n    if (\n        candidate is None\n        or candidate.name not in {"NAMECALL", "NAMECALLUDATA"}\n        or candidate.a != instruction.a\n    ):\n        candidate = None\n        for item in reversed(instructions):\n            if item.pc >= instruction.pc:\n                continue\n            if item.name in _FLOW_BARRIERS:\n                break\n            if (\n                item.name in {"NAMECALL", "NAMECALLUDATA"}\n                and item.a == instruction.a\n            ):\n                candidate = item\n                break\n    if candidate is None:\n        return None\n    index = (\n        candidate.userdata_constant_index\n        if candidate.name == "NAMECALLUDATA"\n        else candidate.aux\n    )\n    method = _constant_string(proto, index if index is not None else -1)\n    return (candidate, method) if method is not None else None\n\n\ndef _literal_string(\n    proto: LuauProto,\n    instructions_by_pc: Mapping[int, DecodedInstruction],\n    program: SSAProgram,\n    value: SSAValue | None,\n    seen: frozenset[SSAValue] = frozenset(),\n) -> str | None:\n    if value is None or value.origin_pc is None or value in seen:\n        return None\n    instruction = instructions_by_pc.get(value.origin_pc)\n    if instruction is None:\n        return None\n    next_seen = seen | frozenset({value})\n    if instruction.name == "LOADK":\n        return _constant_string(proto, instruction.d)\n    if instruction.name == "LOADKX":\n        return _constant_string(proto, instruction.aux or 0)\n    if instruction.name == "MOVE":\n        return _literal_string(\n            proto,\n            instructions_by_pc,\n            program,\n            program.value_at_use(instruction.pc, instruction.b),\n            next_seen,\n        )\n    return None\n\n\ndef ssa_value_path(\n    proto: LuauProto,\n    instructions: Sequence[DecodedInstruction],\n    program: SSAProgram,\n    value: SSAValue | None,\n    seen: frozenset[SSAValue] = frozenset(),\n) -> str | None:\n    if value is None or value.origin_pc is None or value in seen:\n        return None\n    instructions_by_pc = {item.pc: item for item in instructions}\n    instruction = instructions_by_pc.get(value.origin_pc)\n    if instruction is None:\n        return None\n    next_seen = seen | frozenset({value})\n\n    if instruction.name == "GETGLOBAL":\n        index = instruction.aux if instruction.aux is not None else -1\n        return _constant_string(proto, index)\n    if instruction.name == "GETIMPORT":\n        path = _import_path(proto, instruction.aux)\n        return ".".join(path) if path else None\n    if instruction.name in {"GETTABLEKS", "GETUDATAKS"}:\n        base = program.value_at_use(instruction.pc, instruction.b)\n        key_index = (\n            instruction.userdata_constant_index\n            if instruction.name == "GETUDATAKS"\n            else instruction.aux\n        )\n        key = _constant_string(proto, key_index if key_index is not None else -1)\n        prefix = ssa_value_path(proto, instructions, program, base, next_seen)\n        if prefix and key:\n            return f"{prefix}.{key}"\n        return key\n    if instruction.name == "MOVE":\n        return ssa_value_path(\n            proto,\n            instructions,\n            program,\n            program.value_at_use(instruction.pc, instruction.b),\n            next_seen,\n        )\n    if instruction.name in {"CALL", "CALLFB"}:\n        namecall = _namecall_for_call(proto, instructions, instruction)\n        if namecall is None or instruction.b <= 2:\n            return None\n        namecall_instruction, method = namecall\n        if method not in {"FindFirstChild", "WaitForChild"}:\n            return None\n        base = program.value_at_use(\n            namecall_instruction.pc,\n            namecall_instruction.b,\n        )\n        prefix = ssa_value_path(proto, instructions, program, base, next_seen)\n        literal = _literal_string(\n            proto,\n            instructions_by_pc,\n            program,\n            program.value_at_use(instruction.pc, instruction.a + 2),\n        )\n        if prefix and literal:\n            return f"{prefix}.{literal}"\n        return literal\n    return None\n\n\ndef module_name_from_path(path: str | None) -> str | None:\n    if not path:\n        return None\n    chunks = _IDENTIFIER_CHUNK.findall(path)\n    if not chunks:\n        return None\n    ignored = {"Parent", "Root", "script", "game", "workspace"}\n    selected = next(\n        (chunk for chunk in reversed(chunks) if chunk not in ignored),\n        chunks[-1],\n    )\n    if selected.isupper():\n        return selected.lower()\n    return selected[0].lower() + selected[1:]\n\n\ndef _uses_for(\n    program: SSAProgram,\n    value: SSAValue,\n) -> tuple[tuple[SSAInstruction, int], ...]:\n    matches: list[tuple[SSAInstruction, int]] = []\n    for instruction in program.instructions.values():\n        for use in instruction.uses:\n            if use.value == value:\n                matches.append((instruction, use.register))\n    return tuple(matches)\n\n\ndef _terminal_use(\n    program: SSAProgram,\n    value: SSAValue,\n) -> tuple[SSAInstruction, int, tuple[SSAValue, ...]] | None:\n    current = value\n    chain = [value]\n    visited: set[SSAValue] = set()\n    while current not in visited:\n        visited.add(current)\n        uses = _uses_for(program, current)\n        if len(uses) != 1:\n            return None\n        use_instruction, register = uses[0]\n        instruction = use_instruction.instruction\n        if instruction.name != "MOVE" or register != instruction.b:\n            return use_instruction, register, tuple(chain)\n        destination = program.value_defined_at(instruction.pc, instruction.a)\n        if destination is None:\n            return None\n        current = destination\n        chain.append(destination)\n    return None\n\n\ndef _table_or_return_sink(\n    instruction: DecodedInstruction,\n    register: int,\n) -> bool:\n    if instruction.name in {\n        "SETTABLE",\n        "SETTABLEKS",\n        "SETUDATAKS",\n        "SETTABLEN",\n    }:\n        return register == instruction.a\n    if instruction.name == "SETLIST" and instruction.c > 1:\n        return register in range(instruction.b, instruction.b + instruction.c - 1)\n    if instruction.name == "RETURN":\n        if instruction.b == 0:\n            return False\n        return register in range(instruction.a, instruction.a + max(0, instruction.b - 1))\n    return False\n\n\ndef _callback_sink(\n    proto: LuauProto,\n    instructions: Sequence[DecodedInstruction],\n    program: SSAProgram,\n    instruction: DecodedInstruction,\n    register: int,\n) -> bool:\n    if instruction.name not in {"CALL", "CALLFB"} or instruction.b == 0:\n        return False\n    namecall = _namecall_for_call(proto, instructions, instruction)\n    if namecall is not None:\n        _, method = namecall\n        positions = _METHOD_CALLBACK_ARGUMENTS.get(method, ())\n        return register in {\n            instruction.a + 2 + position for position in positions\n        }\n    function_value = program.value_at_use(instruction.pc, instruction.a)\n    path = ssa_value_path(proto, instructions, program, function_value)\n    positions = _FUNCTION_CALLBACK_ARGUMENTS.get(path or "", ())\n    return register in {\n        instruction.a + 1 + position for position in positions\n    }\n\n\ndef plan_inline_callbacks(\n    module: LuauBytecodeModule,\n    proto: LuauProto,\n    instructions: Sequence[DecodedInstruction],\n    program: SSAProgram,\n    *,\n    enabled: bool,\n) -> InlineCallbackPlan:\n    if not enabled:\n        return InlineCallbackPlan.empty()\n\n    instruction_index = {\n        instruction.pc: index for index, instruction in enumerate(instructions)\n    }\n    proto_by_value: dict[SSAValue, int] = {}\n    capture_pcs: set[int] = set()\n\n    for instruction in instructions:\n        child_id = closure_proto_id(proto, instruction)\n        if child_id is None or not 0 <= child_id < len(module.protos):\n            continue\n        value = program.value_defined_at(instruction.pc, instruction.a)\n        if value is None:\n            continue\n        terminal = _terminal_use(program, value)\n        if terminal is None:\n            continue\n        use_instruction, register, chain = terminal\n        sink = use_instruction.instruction\n        if not (\n            _table_or_return_sink(sink, register)\n            or _callback_sink(proto, instructions, program, sink, register)\n        ):\n            continue\n\n        child = module.protos[child_id]\n        captures: list[int] = []\n        cursor = instruction_index[instruction.pc] + 1\n        valid = True\n        for _ in range(child.num_upvalues):\n            if cursor >= len(instructions) or instructions[cursor].name != "CAPTURE":\n                valid = False\n                break\n            captures.append(instructions[cursor].pc)\n            cursor += 1\n        if not valid:\n            continue\n\n        for item in chain:\n            proto_by_value[item] = child_id\n        capture_pcs.update(captures)\n\n    return InlineCallbackPlan(\n        MappingProxyType(dict(proto_by_value)),\n        frozenset(capture_pcs),\n    )\n\n\ndef collect_inline_only_proto_ids(\n    module: LuauBytecodeModule,\n    *,\n    enabled: bool,\n) -> frozenset[int]:\n    if not enabled:\n        return frozenset()\n    references: Counter[int] = Counter()\n    inline_references: Counter[int] = Counter()\n    for proto in module.protos:\n        instructions = tuple(decode_words(proto.code))\n        program = build_ssa(instructions, len(proto.code))\n        plan = plan_inline_callbacks(\n            module,\n            proto,\n            instructions,\n            program,\n            enabled=True,\n        )\n        for instruction in instructions:\n            child_id = closure_proto_id(proto, instruction)\n            if child_id is None:\n                continue\n            references[child_id] += 1\n            value = program.value_defined_at(instruction.pc, instruction.a)\n            if value is not None and value in plan.proto_by_value:\n                inline_references[child_id] += 1\n    return frozenset(\n        proto_id\n        for proto_id, count in references.items()\n        if count > 0 and inline_references[proto_id] == count\n    )\n\n\ndef _export_kind(\n    proto: LuauProto,\n    instructions: Sequence[DecodedInstruction],\n    program: SSAProgram,\n) -> Literal["table", "function", "module", "value"] | None:\n    kinds: set[Literal["table", "function", "module", "value"]] = set()\n    instructions_by_pc = {item.pc: item for item in instructions}\n\n    def origin(value: SSAValue | None, seen: frozenset[SSAValue] = frozenset()) -> DecodedInstruction | None:\n        if value is None or value.origin_pc is None or value in seen:\n            return None\n        instruction = instructions_by_pc.get(value.origin_pc)\n        if instruction is None:\n            return None\n        if instruction.name == "MOVE":\n            return origin(\n                program.value_at_use(instruction.pc, instruction.b),\n                seen | frozenset({value}),\n            )\n        return instruction\n\n    for instruction in instructions:\n        if instruction.name != "RETURN" or instruction.b in {0, 1}:\n            continue\n        value = program.value_at_use(instruction.pc, instruction.a)\n        source = origin(value)\n        if source is None:\n            continue\n        if source.name in {"NEWTABLE", "DUPTABLE"}:\n            kinds.add("table")\n        elif source.name in {"NEWCLOSURE", "DUPCLOSURE"}:\n            kinds.add("function")\n        elif source.name in {"CALL", "CALLFB"}:\n            function_path = ssa_value_path(\n                proto,\n                instructions,\n                program,\n                program.value_at_use(source.pc, source.a),\n            )\n            kinds.add("module" if function_path == "require" else "value")\n        else:\n            kinds.add("value")\n    return next(iter(kinds)) if len(kinds) == 1 else None\n\n\ndef analyze_roblox_recovery(\n    module: LuauBytecodeModule,\n    proto: LuauProto,\n    instructions: Sequence[DecodedInstruction],\n    program: SSAProgram,\n) -> RobloxRecoveryReport:\n    events: list[RobloxEventBinding] = []\n    dependencies: list[RobloxModuleDependency] = []\n\n    for instruction in instructions:\n        if instruction.name not in {"CALL", "CALLFB"}:\n            continue\n        namecall = _namecall_for_call(proto, instructions, instruction)\n        if namecall is not None:\n            namecall_instruction, method = namecall\n            if method in _EVENT_METHODS:\n                base = program.value_at_use(\n                    namecall_instruction.pc,\n                    namecall_instruction.b,\n                )\n                signal = ssa_value_path(proto, instructions, program, base)\n                events.append(\n                    RobloxEventBinding(\n                        signal or f"R{namecall_instruction.b}",\n                        method,\n                        instruction.pc,\n                    )\n                )\n\n        function_path = ssa_value_path(\n            proto,\n            instructions,\n            program,\n            program.value_at_use(instruction.pc, instruction.a),\n        )\n        if function_path != "require" or instruction.b <= 1:\n            continue\n        dependency_path = ssa_value_path(\n            proto,\n            instructions,\n            program,\n            program.value_at_use(instruction.pc, instruction.a + 1),\n        )\n        if dependency_path is None:\n            dependency_path = "<dynamic>"\n        dependencies.append(\n            RobloxModuleDependency(\n                dependency_path,\n                module_name_from_path(dependency_path) or "module",\n                instruction.pc,\n            )\n        )\n\n    unique_events = {\n        (item.signal, item.method): item for item in events\n    }\n    unique_dependencies = {\n        item.path: item for item in dependencies\n    }\n    return RobloxRecoveryReport(\n        tuple(\n            unique_events[key]\n            for key in sorted(unique_events)\n        ),\n        tuple(\n            unique_dependencies[key]\n            for key in sorted(unique_dependencies)\n        ),\n        _export_kind(proto, instructions, program),\n    )\n',
)
write(
    ROOT / "tests/test_roblox_recovery_v014.py",
    '\nfrom __future__ import annotations\n\nfrom lunaux.backends.bytecode import LuauBytecodeModule, LuauConstant, LuauProto\nfrom lunaux.backends.lifter import decompile_module\nfrom lunaux.backends.opcodes import opcode_names\n\n\ndef _abc(name: str, *, a: int = 0, b: int = 0, c: int = 0) -> int:\n    opcode = opcode_names().index(name)\n    return opcode | (a << 8) | (b << 16) | (c << 24)\n\n\ndef _ad(name: str, *, a: int = 0, d: int = 0) -> int:\n    opcode = opcode_names().index(name)\n    return opcode | (a << 8) | ((d & 0xFFFF) << 16)\n\n\ndef _proto(\n    proto_id: int,\n    code: tuple[int, ...],\n    constants: tuple[LuauConstant, ...] = (),\n    *,\n    children: tuple[int, ...] = (),\n    params: int = 0,\n    upvalues: int = 0,\n    upvalue_names: tuple[str | None, ...] = (),\n    stack: int = 8,\n    name: str | None = None,\n) -> LuauProto:\n    return LuauProto(\n        proto_id=proto_id,\n        max_stack_size=stack,\n        num_params=params,\n        num_upvalues=upvalues,\n        is_vararg=False,\n        flags=0,\n        type_info=b"",\n        code=code,\n        constants=constants,\n        child_proto_ids=children,\n        line_defined=1,\n        debug_name=name or f"proto_{proto_id}",\n        line_info=(),\n        locals=(),\n        upvalue_names=upvalue_names,\n        feedback_pcs=(),\n        cost=None,\n    )\n\n\ndef _module(*protos: LuauProto, main: int) -> LuauBytecodeModule:\n    return LuauBytecodeModule(\n        version=13,\n        types_version=3,\n        strings=(),\n        protos=protos,\n        main_proto_id=main,\n        bytes_consumed=0,\n        trailing_bytes=0,\n    )\n\n\ndef test_inlines_event_callback_and_recovers_connection() -> None:\n    child_constants = (LuauConstant("string", "print", 3),)\n    child = _proto(\n        0,\n        (\n            _abc("GETGLOBAL", a=1),\n            0,\n            _abc("MOVE", a=2, b=0),\n            _abc("CALL", a=1, b=2, c=1),\n            _abc("RETURN", a=0, b=1),\n        ),\n        child_constants,\n        params=1,\n        stack=3,\n        name="onActivated",\n    )\n    main_constants = (\n        LuauConstant("string", "button", 3),\n        LuauConstant("string", "Activated", 3),\n        LuauConstant("string", "Connect", 3),\n    )\n    main = _proto(\n        1,\n        (\n            _abc("GETGLOBAL", a=0),\n            0,\n            _abc("GETTABLEKS", a=1, b=0),\n            1,\n            _ad("NEWCLOSURE", a=3, d=0),\n            _abc("NAMECALL", a=1, b=1),\n            2,\n            _abc("CALL", a=1, b=3, c=2),\n            _abc("RETURN", a=0, b=1),\n        ),\n        main_constants,\n        children=(0,),\n        stack=4,\n        name="main",\n    )\n\n    output = decompile_module(\n        _module(child, main, main=1),\n        {},\n        "event.luau",\n    )\n\n    assert "-- Roblox events: button.Activated:Connect" in output\n    assert "button.Activated:Connect(function(arg1)" in output\n    assert "print(arg1)" in output\n    assert "RBXScriptConnection" in output\n    assert "local function onActivated" not in output\n\n\ndef test_inlines_task_delay_callback_in_its_callback_slot() -> None:\n    child = _proto(\n        0,\n        (\n            _abc("RETURN", a=0, b=1),\n        ),\n        name="delayed",\n    )\n    constants = (\n        LuauConstant("string", "task", 3),\n        LuauConstant("string", "delay", 3),\n    )\n    main = _proto(\n        1,\n        (\n            _abc("GETGLOBAL", a=0),\n            0,\n            _abc("GETTABLEKS", a=1, b=0),\n            1,\n            _ad("LOADN", a=2, d=2),\n            _ad("NEWCLOSURE", a=3, d=0),\n            _abc("CALL", a=1, b=3, c=1),\n            _abc("RETURN", a=0, b=1),\n        ),\n        constants,\n        children=(0,),\n        stack=4,\n    )\n\n    output = decompile_module(_module(child, main, main=1), {}, "delay.luau")\n\n    assert "task.delay(2, function()" in output\n    assert "local function delayed" not in output\n\n\ndef test_module_table_exports_inline_function_fields() -> None:\n    child = _proto(\n        0,\n        (\n            _ad("LOADN", a=0, d=1),\n            _abc("RETURN", a=0, b=2),\n        ),\n        name="start",\n    )\n    constants = (LuauConstant("string", "Start", 3),)\n    main = _proto(\n        1,\n        (\n            _abc("NEWTABLE", a=0),\n            0,\n            _ad("NEWCLOSURE", a=1, d=0),\n            _abc("SETTABLEKS", a=1, b=0),\n            0,\n            _abc("RETURN", a=0, b=2),\n        ),\n        constants,\n        children=(0,),\n        stack=2,\n    )\n\n    output = decompile_module(_module(child, main, main=1), {}, "module.luau")\n\n    assert "-- Roblox ModuleScript export: table" in output\n    assert "Start = function()" in output\n    assert "return 1" in output\n    assert "local function start" not in output\n\n\ndef test_require_dependency_uses_module_path_for_name_and_report() -> None:\n    constants = (\n        LuauConstant("string", "require", 3),\n        LuauConstant("string", "script", 3),\n        LuauConstant("string", "Parent", 3),\n        LuauConstant("string", "InventoryService", 3),\n    )\n    main = _proto(\n        0,\n        (\n            _abc("GETGLOBAL", a=0),\n            0,\n            _abc("GETGLOBAL", a=1),\n            1,\n            _abc("GETTABLEKS", a=1, b=1),\n            2,\n            _abc("GETTABLEKS", a=1, b=1),\n            3,\n            _abc("CALL", a=0, b=2, c=2),\n            _abc("RETURN", a=0, b=2),\n        ),\n        constants,\n        stack=2,\n        name="main",\n    )\n\n    output = decompile_module(_module(main, main=0), {}, "consumer.luau")\n\n    assert (\n        "-- Roblox module dependencies: script.Parent.InventoryService"\n        in output\n    )\n    assert (\n        "local inventoryService = require(script.Parent.InventoryService)"\n        in output\n    )\n    assert "-- Roblox ModuleScript export: module" in output\n\n\ndef test_shared_event_callback_keeps_named_function() -> None:\n    child = _proto(\n        0,\n        (\n            _abc("RETURN", a=0, b=1),\n        ),\n        name="sharedCallback",\n    )\n    constants = (\n        LuauConstant("string", "signalA", 3),\n        LuauConstant("string", "signalB", 3),\n        LuauConstant("string", "Connect", 3),\n    )\n    main = _proto(\n        1,\n        (\n            _ad("NEWCLOSURE", a=4, d=0),\n            _abc("GETGLOBAL", a=0),\n            0,\n            _abc("NAMECALL", a=0, b=0),\n            2,\n            _abc("MOVE", a=2, b=4),\n            _abc("CALL", a=0, b=3, c=1),\n            _abc("GETGLOBAL", a=0),\n            1,\n            _abc("NAMECALL", a=0, b=0),\n            2,\n            _abc("MOVE", a=2, b=4),\n            _abc("CALL", a=0, b=3, c=1),\n            _abc("RETURN", a=0, b=1),\n        ),\n        constants,\n        children=(0,),\n        stack=5,\n    )\n\n    output = decompile_module(_module(child, main, main=1), {}, "shared.luau")\n\n    assert "local function sharedCallback()" in output\n    assert output.count(":Connect(sharedCallback)") == 2\n    assert ":Connect(function()" not in output\n\n\ndef test_callback_capture_is_bound_inside_anonymous_function() -> None:\n    child = _proto(\n        0,\n        (\n            _abc("GETUPVAL", a=0, b=0),\n            _abc("RETURN", a=0, b=2),\n        ),\n        upvalues=1,\n        upvalue_names=("amount",),\n        name="captured",\n    )\n    constants = (\n        LuauConstant("string", "task", 3),\n        LuauConstant("string", "spawn", 3),\n    )\n    main = _proto(\n        1,\n        (\n            _ad("LOADN", a=0, d=5),\n            _abc("GETGLOBAL", a=1),\n            0,\n            _abc("GETTABLEKS", a=1, b=1),\n            1,\n            _ad("NEWCLOSURE", a=2, d=0),\n            _abc("CAPTURE", a=0, b=0),\n            _abc("CALL", a=1, b=2, c=1),\n            _abc("RETURN", a=0, b=1),\n        ),\n        constants,\n        children=(0,),\n        stack=3,\n    )\n\n    output = decompile_module(_module(child, main, main=1), {}, "capture.luau")\n\n    assert "task.spawn(function()" in output\n    assert "return 5" in output\n    assert "-- capture" not in output\n\n\ndef test_callback_and_module_options_can_be_disabled() -> None:\n    child = _proto(\n        0,\n        (_abc("RETURN", a=0, b=1),),\n        name="callback",\n    )\n    constants = (\n        LuauConstant("string", "signal", 3),\n        LuauConstant("string", "Connect", 3),\n    )\n    main = _proto(\n        1,\n        (\n            _abc("GETGLOBAL", a=0),\n            0,\n            _ad("NEWCLOSURE", a=2, d=0),\n            _abc("NAMECALL", a=0, b=0),\n            1,\n            _abc("CALL", a=0, b=3, c=1),\n            _abc("RETURN", a=0, b=1),\n        ),\n        constants,\n        children=(0,),\n        stack=3,\n    )\n\n    output = decompile_module(\n        _module(child, main, main=1),\n        {\n            "RecoverRobloxEvents": False,\n            "InlineRobloxCallbacks": False,\n            "RecoverRobloxModules": False,\n        },\n        "disabled.luau",\n    )\n\n    assert "-- Roblox events:" not in output\n    assert "local function callback()" in output\n    assert ":Connect(callback)" in output\n',
)
write(
    ROOT / "docs/ROBLOX_EVENTS_CALLBACKS_MODULES.md",
    '\n# Roblox events, callbacks, and modules\n\nLunaUX Next 0.14 adds a conservative Roblox semantic pass on top of CFG, SSA,\nexpression, and table reconstruction.\n\n## Event connections\n\nRecognized `RBXScriptSignal` calls keep their source signal and connection method:\n\n```luau\nlocal connection: RBXScriptConnection = button.Activated:Connect(function(input)\n    print(input)\nend)\n```\n\nThe pass recognizes `Connect`, `ConnectParallel`, `Once`, and `Wait`. Connection\nresults receive `RBXScriptConnection` evidence when the bytecode actually returns\nthe connection.\n\n## Inline callbacks\n\nA closure is rendered as an anonymous function only when SSA proves that its\nclosure instance reaches exactly one supported callback sink, module field, or\nreturn value. Supported callback sinks include Roblox event connections,\n`ContextActionService` bindings, `RunService:BindToRenderStep`, `task` scheduling,\n`coroutine` creation/wrapping, `pcall`, `xpcall`, and `table.sort`.\n\nClosure aliases through single-use `MOVE` instructions are followed. Captured\nvalues and references are rebound inside the anonymous function, while the\noriginal `CAPTURE` instructions are omitted from source output.\n\nShared callbacks remain named functions:\n\n```luau\nlocal function onChanged(value)\n    print(value)\nend\n\nfirst.Changed:Connect(onChanged)\nsecond.Changed:Connect(onChanged)\n```\n\n## ModuleScript recovery\n\n`require` dependencies are recovered from direct instance paths and common\n`WaitForChild`/`FindFirstChild` chains. The required value is named from the last\nstable path component:\n\n```luau\nlocal inventoryService = require(script.Parent.InventoryService)\n```\n\nModule tables can absorb single-owner function fields:\n\n```luau\nreturn {\n    Start = function()\n        -- recovered body\n    end,\n}\n```\n\nThe output header reports recovered module dependencies and whether the main\nprototype consistently exports a table, function, required module, or another\nvalue.\n\n## Conservative barriers\n\nInlining is disabled when a closure is shared, escapes through an unknown sink,\nhas ambiguous captures, participates in control-flow merges, or cannot be tied\nto a supported callback/module context. Table reconstruction still materializes\na pending module table before a captured dependency changes or a closure captures\nthe table itself.\n\nThe relevant API options are:\n\n- `RecoverRobloxEvents` (default `true`)\n- `InlineRobloxCallbacks` (default `true`)\n- `RecoverRobloxModules` (default `true`)\n',
)

lifter = ROOT / "src/lunaux/backends/lifter.py"
replace_once(
    lifter,
    """from lunaux.backends.scopes import build_scope_tree
from lunaux.backends.ssa import SSAValue, build_ssa
""",
    """from lunaux.backends.roblox_recovery import (
    analyze_roblox_recovery,
    closure_proto_id,
    collect_inline_only_proto_ids,
    plan_inline_callbacks,
)
from lunaux.backends.scopes import build_scope_tree
from lunaux.backends.ssa import SSAValue, build_ssa
""",
)
replace_once(
    lifter,
    """    show_recovered_symbols: bool
    recover_classes: bool
""",
    """    show_recovered_symbols: bool
    recover_roblox_events: bool
    inline_roblox_callbacks: bool
    recover_roblox_modules: bool
    recover_classes: bool
""",
)
replace_once(
    lifter,
    """            show_recovered_symbols=options.get(
                "ShowRecoveredSymbols",
                False,
            ),
            recover_classes=options.get("RecoverClasses", True),
""",
    """            show_recovered_symbols=options.get(
                "ShowRecoveredSymbols",
                False,
            ),
            recover_roblox_events=options.get("RecoverRobloxEvents", True),
            inline_roblox_callbacks=options.get(
                "InlineRobloxCallbacks",
                True,
            ),
            recover_roblox_modules=options.get("RecoverRobloxModules", True),
            recover_classes=options.get("RecoverClasses", True),
""",
)
replace_once(
    lifter,
    """        options: _Options,
        emitter: _Emitter,
    ) -> None:
""",
    """        options: _Options,
        emitter: _Emitter,
        *,
        inline_only_proto_ids: frozenset[int] = frozenset(),
        upvalue_bindings: dict[int, Expr] | None = None,
    ) -> None:
""",
)
replace_once(
    lifter,
    """        self.options = options
        self.out = emitter
        self.scope_tree = build_scope_tree(proto)
""",
    """        self.options = options
        self.out = emitter
        self.inline_only_proto_ids = inline_only_proto_ids
        self.upvalue_bindings = upvalue_bindings or {}
        self.scope_tree = build_scope_tree(proto)
""",
)
replace_once(
    lifter,
    """        self.ssa = build_ssa(
            self.instructions,
            len(proto.code),
            analysis=self.analysis,
        )
        self.structured_plan = build_structured_recovery(self.ssa)
""",
    """        self.ssa = build_ssa(
            self.instructions,
            len(proto.code),
            analysis=self.analysis,
        )
        self.callback_plan = plan_inline_callbacks(
            module,
            proto,
            self.instructions,
            self.ssa,
            enabled=options.inline_roblox_callbacks,
        )
        self.callback_expressions: dict[SSAValue, Expr] = {}
        self.callback_dependencies: dict[SSAValue, frozenset[SSAValue]] = {}
        self.structured_plan = build_structured_recovery(self.ssa)
""",
)
replace_once(
    lifter,
    """        self.instruction_by_pc = {
            instruction.pc: instruction for instruction in self.instructions
        }
        self.previous_by_next_pc = {
""",
    """        self.instruction_by_pc = {
            instruction.pc: instruction for instruction in self.instructions
        }
        self.instruction_index_by_pc = {
            instruction.pc: index
            for index, instruction in enumerate(self.instructions)
        }
        self.previous_by_next_pc = {
""",
)
replace_once(
    lifter,
    """    def _ref_expr(self, register: int, pc: int) -> Expr:
        if self.options.inline_single_use_temporaries:
            value = self.ssa.value_at_use(pc, register)
            if value is not None:
                expression = self.inline_expressions.get(value)
                if expression is not None:
                    return expression
        return NameExpr(self._name(register, pc))

    def _ref(self, register: int, pc: int) -> str:
""",
    """    def _ref_expr(self, register: int, pc: int) -> Expr:
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            callback = self.callback_expressions.get(value)
            if callback is not None:
                return callback
            if self.options.inline_single_use_temporaries:
                expression = self.inline_expressions.get(value)
                if expression is not None:
                    return expression
        return NameExpr(self._name(register, pc))

    def _ref(self, register: int, pc: int) -> str:
""",
)
replace_once(
    lifter,
    """    def _annotated_name(self, register: int, name: str, pc: int) -> str:
""",
    """    def _transfer_inline_callback(
        self,
        instruction: DecodedInstruction,
    ) -> bool:
        if instruction.name != "MOVE":
            return False
        source = self.ssa.value_at_use(instruction.pc, instruction.b)
        destination = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if (
            source is None
            or destination is None
            or destination not in self.callback_plan.proto_by_value
        ):
            return False
        expression = self.callback_expressions.get(source)
        if expression is None:
            return False
        self.callback_expressions[destination] = expression
        self.callback_dependencies[destination] = self.callback_dependencies.get(
            source,
            frozenset(),
        )
        self.register_names.setdefault(instruction.a, f"v{instruction.a}")
        return True

    def _annotated_name(self, register: int, name: str, pc: int) -> str:
""",
)
replace_once(
    lifter,
    """    def _dependencies_for_value(
        self,
        value: SSAValue,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> frozenset[SSAValue]:
        if value in seen or value.kind != "instruction":
""",
    """    def _dependencies_for_value(
        self,
        value: SSAValue,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> frozenset[SSAValue]:
        callback_dependencies = self.callback_dependencies.get(value)
        if callback_dependencies is not None:
            return callback_dependencies
        if value in seen or value.kind != "instruction":
""",
)
replace_once(
    lifter,
    """    def _call_expression(self, instruction: DecodedInstruction) -> Expr:
""",
    """    def _callback_capture_bindings(
        self,
        instruction: DecodedInstruction,
        child: LuauProto,
    ) -> tuple[dict[int, Expr], frozenset[SSAValue]]:
        bindings: dict[int, Expr] = {}
        dependencies: set[SSAValue] = set()
        cursor = self.instruction_index_by_pc[instruction.pc] + 1
        for upvalue_index in range(child.num_upvalues):
            capture = self.instructions[cursor + upvalue_index]
            if capture.a == 2:
                binding = self.upvalue_bindings.get(capture.b)
                if binding is None:
                    name = (
                        self.proto.upvalue_names[capture.b]
                        if capture.b < len(self.proto.upvalue_names)
                        else None
                    )
                    binding = NameExpr(
                        _sanitize_identifier(name, f"upvalue_{capture.b}")
                    )
            elif capture.a == 1:
                binding = NameExpr(self._name(capture.b, capture.pc))
                source = self.ssa.value_at_use(capture.pc, capture.b)
                if source is not None:
                    dependencies.update(self._dependencies_for_value(source))
            else:
                binding = self._ref_expr(capture.b, capture.pc)
                source = self.ssa.value_at_use(capture.pc, capture.b)
                if source is not None:
                    dependencies.update(self._dependencies_for_value(source))
            bindings[upvalue_index] = binding
        return bindings, frozenset(dependencies)

    def _anonymous_function_expr(
        self,
        child_id: int,
        instruction: DecodedInstruction,
    ) -> tuple[Expr, frozenset[SSAValue]]:
        child = self.module.protos[child_id]
        bindings, dependencies = self._callback_capture_bindings(
            instruction,
            child,
        )
        callback_out = _Emitter(self.options.semicolons)
        _FunctionLifter(
            self.module,
            child,
            self.proto_names,
            self.options,
            callback_out,
            inline_only_proto_ids=self.inline_only_proto_ids,
            upvalue_bindings=bindings,
        ).lift(as_function=True, anonymous_function=True)
        return (
            RawExpr(callback_out.render().strip(), Precedence.ATOM),
            dependencies,
        )

    def _call_expression(self, instruction: DecodedInstruction) -> Expr:
""",
)
replace_once(
    lifter,
    """    def lift(
        self,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
    ) -> None:
""",
    """    def lift(
        self,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
        anonymous_function: bool = False,
    ) -> None:
""",
)
replace_once(
    lifter,
    """        if as_function:
            function_name = (
                function_name_override or self.proto_names[self.proto.proto_id]
            )
            prefix = "local function" if local_function else "function"
            header = f"{prefix} {function_name}({', '.join(parameters)})"
            if (
                self.options.infer_types
                and self.symbols is not None
                and self.symbols.return_type
                and self.symbols.return_type != "any"
            ):
                header += f": {self.symbols.return_type}"
            self.out.open(header)
""",
    """        if as_function:
            if anonymous_function:
                header = f"function({', '.join(parameters)})"
            else:
                function_name = (
                    function_name_override or self.proto_names[self.proto.proto_id]
                )
                prefix = "local function" if local_function else "function"
                header = f"{prefix} {function_name}({', '.join(parameters)})"
            if (
                self.options.infer_types
                and self.symbols is not None
                and self.symbols.return_type
                and self.symbols.return_type != "any"
            ):
                header += f": {self.symbols.return_type}"
            self.out.open(header)
""",
)
replace_once(
    lifter,
    """        if self.options.upvalue_comment and self.proto.num_upvalues:
            names = [
                name or f"upvalue_{index}"
                for index, name in enumerate(self.proto.upvalue_names)
            ]
""",
    """        if self.options.upvalue_comment and self.proto.num_upvalues:
            names = [
                (
                    render_expression(self.upvalue_bindings[index])
                    if index in self.upvalue_bindings
                    else name or f"upvalue_{index}"
                )
                for index, name in enumerate(self.proto.upvalue_names)
            ]
""",
)
replace_once(
    lifter,
    """        for instruction in self.instructions:
            self._finalize_phi_regions(instruction.pc)
            self._flush_tables_before(instruction)
            self._close_blocks(instruction.pc)
""",
    """        for instruction in self.instructions:
            self._finalize_phi_regions(instruction.pc)
            self._flush_tables_before(instruction)
            if instruction.pc in self.callback_plan.capture_pcs:
                continue
            self._close_blocks(instruction.pc)
""",
)
replace_once(
    lifter,
    """        if as_function:
            self.out.close()
            self.out.line()
""",
    """        if as_function:
            self.out.close()
            if not anonymous_function:
                self.out.line()
""",
)
replace_once(
    lifter,
    """            _FunctionLifter(
                self.module,
                child,
                self.proto_names,
                self.options,
                self.out,
            ).lift(
""",
    """            _FunctionLifter(
                self.module,
                child,
                self.proto_names,
                self.options,
                self.out,
                inline_only_proto_ids=self.inline_only_proto_ids,
            ).lift(
""",
)
replace_once(
    lifter,
    """        elif name == "MOVE":
            if (
                self.options.reconstruct_table_literals
""",
    """        elif name == "MOVE":
            if self._transfer_inline_callback(instruction):
                return
            if (
                self.options.reconstruct_table_literals
""",
)
replace_once(
    lifter,
    """        elif name == "GETUPVAL":
            upvalue = (
                self.proto.upvalue_names[instruction.b]
                if instruction.b < len(self.proto.upvalue_names)
                else None
            )
            self._assign(
                instruction.a,
                NameExpr(
                    _sanitize_identifier(upvalue, f"upvalue_{instruction.b}")
                ),
                pc,
            )
        elif name == "SETUPVAL":
            upvalue = (
                self.proto.upvalue_names[instruction.b]
                if instruction.b < len(self.proto.upvalue_names)
                else None
            )
            lhs = _sanitize_identifier(upvalue, f"upvalue_{instruction.b}")
            self.out.line(f"{lhs} = {self._ref(instruction.a, pc)}", statement=True)
""",
    """        elif name == "GETUPVAL":
            binding = self.upvalue_bindings.get(instruction.b)
            if binding is not None:
                self._assign(instruction.a, binding, pc)
            else:
                upvalue = (
                    self.proto.upvalue_names[instruction.b]
                    if instruction.b < len(self.proto.upvalue_names)
                    else None
                )
                self._assign(
                    instruction.a,
                    NameExpr(
                        _sanitize_identifier(upvalue, f"upvalue_{instruction.b}")
                    ),
                    pc,
                )
        elif name == "SETUPVAL":
            binding = self.upvalue_bindings.get(instruction.b)
            if binding is not None:
                lhs = render_expression(binding)
            else:
                upvalue = (
                    self.proto.upvalue_names[instruction.b]
                    if instruction.b < len(self.proto.upvalue_names)
                    else None
                )
                lhs = _sanitize_identifier(upvalue, f"upvalue_{instruction.b}")
            self.out.line(f"{lhs} = {self._ref(instruction.a, pc)}", statement=True)
""",
)
replace_once(
    lifter,
    """        elif name in {"NEWCLOSURE", "DUPCLOSURE"}:
            child_id: int | None = None
            if (
                name == "NEWCLOSURE"
                and 0 <= instruction.d < len(self.proto.child_proto_ids)
            ):
                child_id = self.proto.child_proto_ids[instruction.d]
            elif name == "DUPCLOSURE":
                constant = _constant(self.proto, instruction.d)
                if (
                    constant
                    and constant.kind == "closure"
                    and isinstance(constant.value, int)
                ):
                    child_id = constant.value
            expression = (
""",
    """        elif name in {"NEWCLOSURE", "DUPCLOSURE"}:
            child_id = closure_proto_id(self.proto, instruction)
            value = self.ssa.value_defined_at(pc, instruction.a)
            if (
                child_id is not None
                and value is not None
                and value in self.callback_plan.proto_by_value
            ):
                expression, dependencies = self._anonymous_function_expr(
                    child_id,
                    instruction,
                )
                self.callback_expressions[value] = expression
                self.callback_dependencies[value] = dependencies
                self.register_names.setdefault(instruction.a, f"v{instruction.a}")
                return
            expression = (
""",
)
replace_once(
    lifter,
    """    names = _proto_names(module)
    for proto in module.protos:
        if proto.proto_id == module.main_proto_id:
            continue
        _FunctionLifter(module, proto, names, resolved, out).lift(as_function=True)

    out.line("-- Main prototype")
    _FunctionLifter(
        module,
        module.main_proto,
        names,
        resolved,
        out,
    ).lift(as_function=False)
""",
    """    names = _proto_names(module)
    inline_only_proto_ids = collect_inline_only_proto_ids(
        module,
        enabled=resolved.inline_roblox_callbacks,
    )
    main_instructions = tuple(decode_words(module.main_proto.code))
    main_ssa = build_ssa(main_instructions, len(module.main_proto.code))
    roblox_report = analyze_roblox_recovery(
        module,
        module.main_proto,
        main_instructions,
        main_ssa,
    )
    if resolved.recover_roblox_events and roblox_report.events:
        out.line(
            "-- Roblox events: "
            + ", ".join(item.display for item in roblox_report.events)
        )
    if resolved.recover_roblox_modules:
        if roblox_report.dependencies:
            out.line(
                "-- Roblox module dependencies: "
                + ", ".join(item.path for item in roblox_report.dependencies)
            )
        if roblox_report.export_kind is not None:
            out.line(
                "-- Roblox ModuleScript export: "
                + roblox_report.export_kind
            )
    if (
        (resolved.recover_roblox_events and roblox_report.events)
        or (
            resolved.recover_roblox_modules
            and (
                roblox_report.dependencies
                or roblox_report.export_kind is not None
            )
        )
    ):
        out.line()

    for proto in module.protos:
        if (
            proto.proto_id == module.main_proto_id
            or proto.proto_id in inline_only_proto_ids
        ):
            continue
        _FunctionLifter(
            module,
            proto,
            names,
            resolved,
            out,
            inline_only_proto_ids=inline_only_proto_ids,
        ).lift(as_function=True)

    out.line("-- Main prototype")
    _FunctionLifter(
        module,
        module.main_proto,
        names,
        resolved,
        out,
        inline_only_proto_ids=inline_only_proto_ids,
    ).lift(as_function=False)
""",
)

table_recovery = ROOT / "src/lunaux/backends/table_recovery.py"
replace_once(
    table_recovery,
    """        "DUPTABLE",
    }
)
""",
    """        "DUPTABLE",
        "NEWCLOSURE",
        "DUPCLOSURE",
        "CAPTURE",
    }
)
""",
)

patterns = ROOT / "src/lunaux/backends/roblox_patterns.py"
replace_once(
    patterns,
    """    literal = _first_literal(arguments)

    if method == "GetService" and literal:
""",
    """    literal = _first_literal(arguments)

    if method in {"Connect", "ConnectParallel", "Once"}:
        return RobloxPatternMatch(
            "connection",
            "RBXScriptConnection",
            96,
            f"Roblox event {method} connection",
        )

    if method == "Wait":
        return RobloxPatternMatch(
            "eventValue",
            None,
            66,
            "Roblox signal Wait result",
        )

    if method == "GetService" and literal:
""",
)
replace_once(
    patterns,
    """    literal = _first_literal(arguments)

    if path == "Instance.new" and literal:
""",
    """    literal = _first_literal(arguments)

    if path == "require":
        return RobloxPatternMatch(
            "module",
            None,
            76,
            "Roblox require dependency",
        )

    scheduled: Final[dict[str, tuple[str, str, int]]] = {
        "task.defer": ("thread", "thread", 88),
        "task.delay": ("thread", "thread", 88),
        "task.spawn": ("thread", "thread", 88),
        "coroutine.create": ("thread", "thread", 84),
        "coroutine.wrap": ("wrapped", "function", 82),
    }
    scheduled_match = scheduled.get(path)
    if scheduled_match is not None:
        name, type_name, confidence = scheduled_match
        return RobloxPatternMatch(
            name,
            type_name,
            confidence,
            f"Roblox callback scheduler {path}",
        )

    if path == "Instance.new" and literal:
""",
)

symbols = ROOT / "src/lunaux/backends/symbols.py"
replace_once(
    symbols,
    """from lunaux.backends.roblox_patterns import (
    match_function_call,
    match_method_call,
)
""",
    """from lunaux.backends.roblox_patterns import (
    match_function_call,
    match_method_call,
)
from lunaux.backends.roblox_recovery import module_name_from_path
""",
)
replace_once(
    symbols,
    """                function_value = program.value_at_use(pc, instruction.a)
                call_path = value_path(function_value)
                direct_arguments = (
""",
    """                function_value = program.value_at_use(pc, instruction.a)
                call_path = value_path(function_value)
                if call_path == "require" and instruction.b > 1:
                    dependency_path = value_path(
                        program.value_at_use(pc, instruction.a + 1)
                    )
                    module_name = module_name_from_path(dependency_path)
                    for register in result_registers:
                        add_definition_name(
                            pc,
                            register,
                            module_name,
                            96,
                            "Roblox require path",
                        )
                direct_arguments = (
""",
)

models = ROOT / "src/lunaux/models.py"
replace_once(
    models,
    """    show_recovered_symbols: bool = Field(
        default=False,
        alias="ShowRecoveredSymbols",
    )
    recover_classes: bool = Field(default=True, alias="RecoverClasses")
""",
    """    show_recovered_symbols: bool = Field(
        default=False,
        alias="ShowRecoveredSymbols",
    )
    recover_roblox_events: bool = Field(
        default=True,
        alias="RecoverRobloxEvents",
    )
    inline_roblox_callbacks: bool = Field(
        default=True,
        alias="InlineRobloxCallbacks",
    )
    recover_roblox_modules: bool = Field(
        default=True,
        alias="RecoverRobloxModules",
    )
    recover_classes: bool = Field(default=True, alias="RecoverClasses")
""",
)
replace_once(
    models,
    """            "ShowRecoveredSymbols": self.show_recovered_symbols,
            "RecoverClasses": self.recover_classes,
""",
    """            "ShowRecoveredSymbols": self.show_recovered_symbols,
            "RecoverRobloxEvents": self.recover_roblox_events,
            "InlineRobloxCallbacks": self.inline_roblox_callbacks,
            "RecoverRobloxModules": self.recover_roblox_modules,
            "RecoverClasses": self.recover_classes,
""",
)

replace_once(
    ROOT / "pyproject.toml",
    'version = "0.13.0"',
    'version = "0.14.0"',
)
replace_once(
    ROOT / "src/lunaux/__init__.py",
    '__version__ = "0.13.0"',
    '__version__ = "0.14.0"',
)

example = ROOT / "examples/api_script.luau"
replace_once(
    example,
    """    ShowRecoveredSymbols = false,
    RecoverClasses = true,
""",
    """    ShowRecoveredSymbols = false,
    RecoverRobloxEvents = true,
    InlineRobloxCallbacks = true,
    RecoverRobloxModules = true,
    RecoverClasses = true,
""",
)

readme = ROOT / "README.md"
replace_once(
    readme,
    """> **Version 0.13:** expands table recovery into an ownership- and SSA-aware reconstruction pass for nested tables, templates, dynamic keys, deterministic overwrites, aliases, and open `SETLIST` tails.
""",
    """> **Version 0.14:** reconstructs Roblox event connections, single-owner callbacks, captured callback values, `require` dependencies, and function-valued ModuleScript exports on top of the 0.13 table pass.
""",
)
replace_once(
    readme,
    """- Reconstructs full table constructors from `NEWTABLE` and `DUPTABLE`, including nested tables, named/indexed/dynamic keys, fixed `SETLIST` ranges, and final open call or vararg tails.
- Eliminates safe adjacent single-use temporaries without duplicating evaluations or hiding named/typed debug locals.
""",
    """- Reconstructs full table constructors from `NEWTABLE` and `DUPTABLE`, including nested tables, named/indexed/dynamic keys, fixed `SETLIST` ranges, and final open call or vararg tails.
- Reconstructs Roblox event connections, including `Connect`, `ConnectParallel`, `Once`, and signal waits, with `RBXScriptConnection` result evidence.
- Inlines single-owner closures into recognized event, scheduler, action-binding, sorting, module-field, and returned-function callback positions.
- Rebinds callback captures and follows single-use closure aliases while preserving shared callbacks as named functions.
- Recovers `require` dependency paths, derives stable module names, reports ModuleScript export shape, and folds function-valued module tables.
- Eliminates safe adjacent single-use temporaries without duplicating evaluations or hiding named/typed debug locals.
""",
)
replace_once(
    readme,
    """### Full table reconstruction
""",
    """### Roblox events, callbacks, and modules

Version 0.14 recognizes Roblox signal connections and supported callback sinks. A closure is inlined only when SSA proves that the closure instance has one supported destination; shared or escaping callbacks keep their named prototype form.

```luau
local connection: RBXScriptConnection = button.Activated:Connect(function(input)
    print(input)
end)

local inventoryService = require(script.Parent.InventoryService)

return {
    Start = function()
        inventoryService:Start()
    end,
}
```

The output header reports recognized event bindings, `require` dependencies, and a consistent ModuleScript export kind. Captured values are rebound inside anonymous functions, and pending module tables are materialized before a capture or dependency change could alter semantics. See [`docs/ROBLOX_EVENTS_CALLBACKS_MODULES.md`](docs/ROBLOX_EVENTS_CALLBACKS_MODULES.md).

### Full table reconstruction
""",
)
replace_once(
    readme,
    """| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |
""",
    """| `InlineSingleUseTemporaries` | `true` | Fold safe adjacent SSA temporaries into their single consumer. Disable for more literal register-oriented output. |
| `RecoverRobloxEvents` | `true` | Report recognized Roblox signal connections and event waits. |
| `InlineRobloxCallbacks` | `true` | Inline single-owner closures into supported callback, module-field, and returned-function positions. |
| `RecoverRobloxModules` | `true` | Recover `require` dependency paths and ModuleScript export shape. |
| `MaxOutputCharacters` | `4000000` | Maximum generated output length. Accepted range: 1,000 to 20,000,000 characters. |
""",
)

print("applied LunaUX 0.14 Roblox event, callback, and module recovery")
