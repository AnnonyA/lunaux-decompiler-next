from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal, cast

from lunaux.backends.advanced_loops import (
    LoopJumpAction,
    analyze_advanced_loops,
)
from lunaux.backends.analysis import analyze_control_flow
from lunaux.backends.ast import (
    BinaryExpr,
    CallExpr,
    CompoundAssignment,
    Expr,
    FieldExpr,
    IfExpr,
    IndexExpr,
    LiteralExpr,
    MethodCallExpr,
    NameExpr,
    Precedence,
    RawExpr,
    TableExpr,
    UnaryExpr,
    ensure_expr,
    referenced_names,
    render_expression,
    render_statement,
    source_expr,
)
from lunaux.backends.bytecode import (
    ClassShapeConstant,
    LuauBytecodeModule,
    LuauConstant,
    LuauProto,
    format_type_tag,
    function_parameter_types,
)
from lunaux.backends.callframe import CallResultShape
from lunaux.backends.canonical_cfg import build_canonical_cfg_plan
from lunaux.backends.classes import (
    ClassRecoveryPlan,
    collect_class_method_proto_ids,
    recover_classes,
)
from lunaux.backends.contextual_functions import (
    collect_module_function_contexts,
    plan_contextual_functions,
)
from lunaux.backends.inlining import plan_expression_inlining
from lunaux.backends.module_analysis import (
    ModuleAnalysis,
    SymbolAnalysisConfig,
    build_module_analysis,
)
from lunaux.backends.opcodes import (
    DecodedInstruction,
    builtin_name,
    decode_words,
    get_jump_target,
    setlist_semantics,
)
from lunaux.backends.proto_emission import (
    ParentProtoEmissionPlan,
    ProtoEmissionPlan,
    ProtoInstancePlan,
    build_proto_emission_plan,
)
from lunaux.backends.read_modify_write import (
    ReadModifyWrite,
    StorageKind,
    plan_read_modify_write,
)
from lunaux.backends.roblox_recovery import (
    analyze_roblox_recovery,
    closure_proto_id,
    collect_inline_only_proto_ids,
    plan_inline_callbacks,
)
from lunaux.backends.scopes import build_scope_tree
from lunaux.backends.semantic_naming import (
    FunctionRole,
    build_semantic_name_plan,
    infer_returned_module_root,
)
from lunaux.backends.ssa import SSAValue, build_ssa
from lunaux.backends.state_machine import StateMachineRegion, recover_state_machines
from lunaux.backends.structuring import (
    DecisionPhiRegion,
    GuardedPhiRegion,
    ValueShortCircuitRegion,
    build_structured_recovery,
)
from lunaux.backends.symbols import SymbolRecovery, build_symbol_recovery
from lunaux.backends.table_recovery import (
    PendingTableLiteral,
    TableBuildPlan,
    is_safe_table_gap,
    is_table_write,
    plan_table_builds,
    table_write_source_registers,
    table_write_target_register,
    table_write_value_registers,
)

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_RESERVED = {
    "and",
    "break",
    "continue",
    "do",
    "else",
    "elseif",
    "end",
    "export",
    "false",
    "for",
    "function",
    "if",
    "in",
    "local",
    "nil",
    "not",
    "or",
    "repeat",
    "return",
    "then",
    "true",
    "type",
    "typeof",
    "until",
    "while",
}
_BINARY_OPS = {
    "ADD": "+",
    "SUB": "-",
    "MUL": "*",
    "DIV": "/",
    "MOD": "%",
    "POW": "^",
    "IDIV": "//",
    "AND": "and",
    "OR": "or",
}
_BINARY_CONST_OPS = {
    "ADDK": "+",
    "SUBK": "-",
    "MULK": "*",
    "DIVK": "/",
    "MODK": "%",
    "POWK": "^",
    "IDIVK": "//",
    "ANDK": "and",
    "ORK": "or",
}
_UNARY_OPS = {"NOT": "not ", "MINUS": "-", "LENGTH": "#"}
_COMPARISON_FALLTHROUGH = {
    "JUMPIFEQ": "~=",
    "JUMPIFLE": ">",
    "JUMPIFLT": ">=",
    "JUMPIFNOTEQ": "==",
    "JUMPIFNOTLE": "<=",
    "JUMPIFNOTLT": "<",
}
_CONDITIONAL_OPS = frozenset(
    {
        "JUMPIF",
        "JUMPIFNOT",
        *_COMPARISON_FALLTHROUGH,
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
    }
)
_CAPTURE_NAMES = {0: "value", 1: "reference", 2: "upvalue"}


@dataclass(frozen=True, slots=True)
class _Options:
    semicolons: bool
    upvalue_comment: bool
    show_line_defined: bool
    show_function_id: bool
    preserve_for_step: bool
    use_if_expression: bool
    recover_phi_expressions: bool
    combine_boolean_conditions: bool
    advanced_loops: bool
    unflatten_state_machines: bool
    reconstruct_table_literals: bool
    inline_single_use_temporaries: bool
    smart_variable_names: bool
    infer_types: bool
    flow_sensitive_types: bool
    roblox_api_types: bool
    contextual_functions: bool
    show_recovered_symbols: bool
    recover_roblox_events: bool
    inline_roblox_callbacks: bool
    recover_roblox_modules: bool
    recover_classes: bool
    recover_metatable_classes: bool

    @classmethod
    def from_backend(cls, options: dict[str, bool]) -> _Options:
        return cls(
            semicolons=options.get("Semicolons", False),
            upvalue_comment=options.get("UpvalueComment", True),
            show_line_defined=options.get("ShowLineDefined", True),
            show_function_id=options.get("ShowFunctionId", False),
            preserve_for_step=options.get("PreserveForStep", False),
            use_if_expression=options.get("UseIfExpression", True),
            recover_phi_expressions=options.get("RecoverPhiExpressions", True),
            combine_boolean_conditions=options.get(
                "CombineBooleanConditions",
                True,
            ),
            advanced_loops=options.get("AdvancedLoops", True),
            unflatten_state_machines=options.get("UnflattenStateMachines", True),
            reconstruct_table_literals=options.get(
                "ReconstructTableLiterals",
                True,
            ),
            inline_single_use_temporaries=options.get(
                "InlineSingleUseTemporaries",
                True,
            ),
            smart_variable_names=options.get("SmartVariableNames", True),
            infer_types=options.get("InferTypes", True),
            flow_sensitive_types=options.get("FlowSensitiveTypes", True),
            roblox_api_types=options.get("RobloxAPITypes", True),
            contextual_functions=options.get("ContextualFunctions", True),
            show_recovered_symbols=options.get(
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
            recover_metatable_classes=options.get("RecoverMetatableClasses", True),
        )


class _Emitter:
    def __init__(self, semicolons: bool) -> None:
        self.lines: list[str] = []
        self.indent = 0
        self.semicolons = semicolons

    def line(self, text: str = "", *, statement: bool = False) -> None:
        suffix = (
            ";"
            if statement and self.semicolons and text and not text.rstrip().endswith(";")
            else ""
        )
        parts = text.splitlines() or [""]
        for index, part in enumerate(parts):
            line_suffix = suffix if index == len(parts) - 1 else ""
            self.lines.append("    " * self.indent + part + line_suffix)

    def open(self, text: str) -> None:
        self.line(text)
        self.indent += 1

    def transition(self, text: str) -> None:
        self.indent = max(0, self.indent - 1)
        self.line(text)
        self.indent += 1

    def close(self, text: str = "end") -> None:
        self.indent = max(0, self.indent - 1)
        self.line(text)

    def render(self) -> str:
        return "\n".join(self.lines).rstrip() + "\n"


def _sanitize_identifier(value: str | None, fallback: str) -> str:
    if value and _IDENTIFIER.fullmatch(value) and value not in _RESERVED:
        return value
    return fallback


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _format_number(value: float) -> str:
    if math.isnan(value):
        return "(0 / 0)"
    if math.isinf(value):
        return "math.huge" if value > 0 else "-math.huge"
    if value == 0 and math.copysign(1.0, value) < 0:
        return "-0"
    return repr(value)


def _source_type(type_name: str | None) -> str | None:
    if type_name == "function":
        return "(...any) -> ...any"
    if type_name == "function?":
        return "((...any) -> ...any)?"
    return type_name


def _constant(proto: LuauProto, index: int) -> LuauConstant | None:
    return proto.constants[index] if 0 <= index < len(proto.constants) else None


def _constant_string(proto: LuauProto, index: int) -> str | None:
    constant = _constant(proto, index)
    if constant and constant.kind == "string" and isinstance(constant.value, str):
        return constant.value
    return None


def _class_shape_names(
    proto: LuauProto,
    shape: ClassShapeConstant,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    class_name = _constant_string(proto, shape.class_name_constant) or "AnonymousClass"
    properties = tuple(
        _constant_string(proto, index) or f"K{index}" for index in shape.property_name_constants
    )
    methods = tuple(
        _constant_string(proto, index) or f"K{index}" for index in shape.method_name_constants
    )
    return class_name, properties, methods


def _format_vector(value: tuple[float, float, float, float]) -> str:
    x, y, z, w = value
    values = ", ".join(_format_number(item) for item in value)
    if w == 0:
        return f"Vector3.new({_format_number(x)}, {_format_number(y)}, {_format_number(z)})"
    return f"vector.create({values})"


def _constant_expr(proto: LuauProto, index: int) -> str:
    constant = _constant(proto, index)
    if constant is None:
        return f"K{index}"
    value = constant.value
    if constant.kind == "nil":
        return "nil"
    if constant.kind == "boolean":
        return "true" if value else "false"
    if constant.kind == "number" and isinstance(value, float):
        return _format_number(value)
    if constant.kind == "integer" and isinstance(value, int):
        return str(value)
    if constant.kind == "string" and isinstance(value, str):
        return _quote(value)
    if constant.kind in {"vector", "vectord"} and isinstance(value, tuple):
        if len(value) == 4 and all(isinstance(item, float) for item in value):
            return _format_vector(cast(tuple[float, float, float, float], value))
    if constant.kind == "closure" and isinstance(value, int):
        return f"proto_{value}"
    if constant.kind == "table" and isinstance(value, tuple):
        return "{}"
    if constant.kind == "table_with_constants" and isinstance(value, tuple):
        entries = []
        pairs = cast(tuple[tuple[int, int], ...], value)
        for pair in pairs:
            if not isinstance(pair, tuple) or len(pair) != 2:
                continue
            key_index, value_index = pair
            if not isinstance(key_index, int) or not isinstance(value_index, int):
                continue
            rhs = _constant_expr(proto, value_index) if value_index >= 0 else "nil"
            entries.append(f"[{_constant_expr(proto, key_index)}] = {rhs}")
        return "{" + ", ".join(entries) + "}"
    if constant.kind == "class_shape" and isinstance(value, ClassShapeConstant):
        class_name, properties, methods = _class_shape_names(proto, value)
        details = [f"class {class_name}"]
        if properties:
            details.append("properties: " + ", ".join(properties))
        if methods:
            details.append("methods: " + ", ".join(methods))
        return "{} --[[ " + "; ".join(details) + " ]]"
    if constant.kind == "import" and isinstance(value, int):
        return f"--[[ import 0x{value:08x} ]] nil"
    return f"--[[ {constant.kind} ]] nil"


def _constant_description(proto: LuauProto, index: int) -> str:
    constant = _constant(proto, index)
    if constant is None:
        return f"K{index}=<invalid>"
    if constant.kind == "table" and isinstance(constant.value, tuple):
        keys_value = cast(tuple[int, ...], constant.value)
        keys = ", ".join(_constant_expr(proto, item) for item in keys_value)
        return f"K{index}=table-shape[{keys}]"
    if constant.kind == "class_shape" and isinstance(
        constant.value,
        ClassShapeConstant,
    ):
        name, properties, methods = _class_shape_names(proto, constant.value)
        return (
            f"K{index}=class-shape({name}; "
            f"properties={list(properties)!r}; methods={list(methods)!r})"
        )
    return f"K{index}={_constant_expr(proto, index)}"


def _field(base: str, key: str) -> str:
    if _IDENTIFIER.fullmatch(key) and key not in _RESERVED:
        return f"{base}.{key}"
    return f"{base}[{_quote(key)}]"


def _global(key: str) -> str:
    if _IDENTIFIER.fullmatch(key) and key not in _RESERVED:
        return key
    return f"_G[{_quote(key)}]"


def _decode_import(proto: LuauProto, aux: int | None) -> str:
    if aux is None:
        return "_G"
    count = aux >> 30
    indices = ((aux >> 20) & 1023, (aux >> 10) & 1023, aux & 1023)
    names = [_constant_string(proto, indices[index]) for index in range(min(count, 3))]
    if not names or names[0] is None:
        return f"_G --[[ import 0x{aux:08x} ]]"
    result = _global(names[0])
    for name in names[1:]:
        if name is None:
            return result + f" --[[ import 0x{aux:08x} ]]"
        result = _field(result, name)
    return result


def _jump_target(instruction: DecodedInstruction) -> int:
    target = get_jump_target(instruction)
    return target if target is not None else instruction.pc + instruction.size


def _local_name(proto: LuauProto, register: int, pc: int) -> str | None:
    candidates = [
        item
        for item in proto.locals
        if item.register == register and item.start_pc <= pc < item.end_pc and item.name
    ]
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: item.start_pc)
    return _sanitize_identifier(selected.name, f"v{register}")


def _local_type(
    module: LuauBytecodeModule,
    proto: LuauProto,
    register: int,
    pc: int,
) -> str | None:
    candidates = [
        item
        for item in proto.typed_locals
        if item.register == register and item.start_pc <= pc < item.end_pc
    ]
    if not candidates:
        return None
    selected = max(candidates, key=lambda item: item.start_pc)
    return format_type_tag(selected.type_tag, module.userdata_type_map)


def _proto_names(module: LuauBytecodeModule) -> dict[int, str]:
    used: set[str] = set()
    result: dict[int, str] = {}
    for proto in module.protos:
        base = _sanitize_identifier(proto.debug_name, f"proto_{proto.proto_id}")
        name = base
        suffix = 2
        while name in used:
            name = f"{base}_{suffix}"
            suffix += 1
        used.add(name)
        result[proto.proto_id] = name
    return result


@dataclass(frozen=True, slots=True)
class _IfElseRegion:
    else_pc: int
    end_pc: int
    skip_jump_pc: int


@dataclass(frozen=True, slots=True)
class _BytecodeLoopRegion:
    prep_pc: int
    body_pc: int
    loop_pc: int
    close_pc: int

    def contains(self, pc: int) -> bool:
        return self.body_pc <= pc < self.loop_pc


class _FunctionLifter:
    def __init__(
        self,
        module: LuauBytecodeModule,
        proto: LuauProto,
        proto_names: dict[int, str],
        options: _Options,
        emitter: _Emitter,
        *,
        inline_only_proto_ids: frozenset[int] = frozenset(),
        upvalue_bindings: dict[int, Expr] | None = None,
        parameter_name_overrides: dict[int, str] | None = None,
        parameter_type_overrides: dict[int, str] | None = None,
        return_type_override: str | None = None,
        module_analysis: ModuleAnalysis | None = None,
        proto_emission_plan: ProtoEmissionPlan | None = None,
        semantic_function_role: FunctionRole = "normal",
    ) -> None:
        self.module = module
        self.proto = proto
        self.proto_names = proto_names
        self.options = options
        self.out = emitter
        self.inline_only_proto_ids = inline_only_proto_ids
        self.upvalue_bindings = upvalue_bindings or {}
        self.lexically_reserved_names = frozenset().union(
            *(referenced_names(binding) for binding in self.upvalue_bindings.values())
        )
        self.parameter_name_overrides = parameter_name_overrides or {}
        self.parameter_type_overrides = dict(parameter_type_overrides or {})
        self.parameter_type_overrides.update(
            {
                index: type_name
                for index, type_name in enumerate(
                    function_parameter_types(proto, module.userdata_type_map)
                )
            }
        )
        self.return_type_override = return_type_override
        self.module_analysis = module_analysis
        self.proto_emission_plan = proto_emission_plan
        self.semantic_function_role = semantic_function_role
        if module_analysis is None:
            self.scope_tree = build_scope_tree(proto)
            self.instructions = list(decode_words(proto.code))
            self.analysis = analyze_control_flow(self.instructions, len(proto.code))
            self.ssa = build_ssa(
                self.instructions,
                len(proto.code),
                analysis=self.analysis,
            )
        else:
            module_analysis.require_module(module)
            analyzed = module_analysis.for_proto(proto)
            self.scope_tree = analyzed.scope_tree
            self.instructions = list(analyzed.instructions)
            self.analysis = analyzed.control_flow
            self.ssa = analyzed.ssa
        self.register_names: dict[int, str] = {}
        self.declared: set[str] = set()
        self.pending_namecalls: dict[int, tuple[Expr, str]] = {}
        self.block_closures: dict[int, list[str]] = defaultdict(list)
        self.else_transitions: dict[int, int] = {}
        self.parent_proto_plan: ParentProtoEmissionPlan | None = (
            proto_emission_plan.for_parent(proto.proto_id)
            if proto_emission_plan is not None
            else None
        )
        self.callback_plan = (
            self.parent_proto_plan.callback_plan
            if self.parent_proto_plan is not None
            else plan_inline_callbacks(
                module,
                proto,
                self.instructions,
                self.ssa,
                enabled=options.inline_roblox_callbacks,
            )
        )
        self.callback_expressions: dict[SSAValue, Expr] = {}
        self.callback_dependencies: dict[SSAValue, frozenset[SSAValue]] = {}
        self.state_machine_plan = recover_state_machines(
            proto,
            self.instructions,
            self.analysis,
            enabled=options.unflatten_state_machines,
        )
        self.advanced_loop_plan = analyze_advanced_loops(
            self.analysis,
            self.instructions,
            enabled=options.advanced_loops,
        )
        self.structured_plan = build_structured_recovery(self.ssa, proto)
        self.canonical_cfg_plan = build_canonical_cfg_plan(
            self.analysis,
            self.instructions,
            self.structured_plan,
            self.advanced_loop_plan,
            self.state_machine_plan,
        )
        self.structured_plan = self.canonical_cfg_plan.structured
        self.advanced_loop_plan = self.canonical_cfg_plan.advanced_loops
        self.state_machine_plan = self.canonical_cfg_plan.state_machines
        self.phi_conditions: dict[int, Expr] = {}
        self.pending_tables: dict[SSAValue, PendingTableLiteral] = {}
        self.pending_open_table_values: dict[
            int,
            tuple[Expr, frozenset[SSAValue], int],
        ] = {}
        self.symbols: SymbolRecovery | None = None
        symbol_config = SymbolAnalysisConfig(
            enabled=(
                options.smart_variable_names
                or options.infer_types
                or options.show_recovered_symbols
            ),
            flow_sensitive_types=options.flow_sensitive_types,
            roblox_api_types=options.roblox_api_types,
        )
        if module_analysis is not None:
            self.symbols = module_analysis.symbols_for(proto, symbol_config)
        elif symbol_config.enabled:
            self.symbols = build_symbol_recovery(
                module,
                proto,
                self.instructions,
                self.ssa,
                flow_sensitive_types=options.flow_sensitive_types,
                roblox_api_types=options.roblox_api_types,
            )
        self.semantic_names = build_semantic_name_plan(
            proto,
            self.instructions,
            self.ssa,
            self.scope_tree,
            self.symbols,
            parameter_overrides=self.parameter_name_overrides,
            reserved_names=self.lexically_reserved_names,
            function_role=semantic_function_role,
            returned_module_root=(
                infer_returned_module_root(proto, self.ssa)
                if proto.proto_id == module.main_proto_id
                else None
            ),
        )
        self.class_plan = (
            recover_classes(
                module,
                proto,
                self.instructions,
                self.ssa,
                recover_metatable_classes=options.recover_metatable_classes,
                module_analysis=module_analysis,
            )
            if options.recover_classes
            else ClassRecoveryPlan.empty()
        )
        self.contextual_plan = plan_contextual_functions(
            module,
            proto,
            self.instructions,
            self.ssa,
            self.class_plan,
            callback_plan=self.callback_plan,
            enabled=options.contextual_functions,
            module_analysis=module_analysis,
        )
        self.inline_plan = plan_expression_inlining(
            self.ssa,
            proto,
            call_frames=(
                self.parent_proto_plan.call_frames
                if self.parent_proto_plan is not None
                else None
            ),
        )
        self.call_frames = self.inline_plan.call_frames
        self.table_build_plan = (
            plan_table_builds(self.ssa, proto, self.call_frames)
            if options.reconstruct_table_literals
            else TableBuildPlan.empty()
        )
        self.rmw_plan = plan_read_modify_write(self.ssa, proto, self.scope_tree)
        self.inline_expressions: dict[SSAValue, Expr] = {}
        self.pending_rmw_rhs: dict[int, Expr] = {}
        self.planned_function_names: dict[int, str] = {}
        self.emitted_recursion_groups: set[tuple[int, ...]] = set()
        self.instruction_by_pc = {instruction.pc: instruction for instruction in self.instructions}
        self.instruction_index_by_pc = {
            instruction.pc: index for index, instruction in enumerate(self.instructions)
        }
        self.previous_by_next_pc = {
            instruction.pc + instruction.size: instruction for instruction in self.instructions
        }
        self.next_instruction_by_pc = {
            instruction.pc: next_instruction
            for instruction, next_instruction in zip(
                self.instructions,
                self.instructions[1:],
                strict=False,
            )
        }
        self.while_headers: dict[int, tuple[int, DecodedInstruction]] = {}
        self.while_back_pcs: set[int] = set()
        self.repeat_starts: dict[int, int] = {}
        self.repeat_conditions: dict[int, DecodedInstruction] = {}
        self.if_else_regions: dict[int, _IfElseRegion] = {}
        self.skip_jump_pcs: set[int] = set()
        self._analyze_control_flow()
        self._analyze_cfg_regions()
        machine_pcs = self.state_machine_plan.skipped_pcs
        self.active_advanced_loops = {
            pc: region
            for pc, region in self.advanced_loop_plan.by_open_pc.items()
            if not (
                machine_pcs
                & {
                    instruction.pc
                    for block_start in region.body_blocks
                    for instruction in self.analysis.block_by_start[block_start].instructions
                }
            )
        }
        self.active_advanced_repeat_conditions = {
            pc: region
            for pc, region in self.advanced_loop_plan.repeat_by_condition_pc.items()
            if region.header in self.active_advanced_loops
        }
        active_loop_headers = set(self.active_advanced_loops)
        self.active_loop_actions = {
            pc: action
            for pc, action in self.advanced_loop_plan.actions.items()
            if action.loop_header in active_loop_headers and pc not in machine_pcs
        }
        self.numeric_loop_regions = self._numeric_loop_regions()
        self.generic_loop_regions = self._generic_loop_regions()
        self.generic_loop_omitted_nil_values = self._generic_loop_nil_state_values()
        for pc, action in self._bytecode_loop_actions().items():
            self.active_loop_actions[pc] = action
        self.active_loop_skip_pcs = {
            pc
            for pc in self.advanced_loop_plan.skipped_pcs
            if pc not in machine_pcs
            and any(pc in region.backedge_pcs for region in self.active_advanced_loops.values())
        }
        advanced_legacy_pcs = (
            set(self.active_loop_actions)
            | self.active_loop_skip_pcs
            | {
                region.condition_pc
                for region in self.active_advanced_loops.values()
                if region.condition_pc is not None
            }
        )
        for header in self.active_advanced_loops:
            self.while_headers.pop(header, None)
            self.repeat_starts.pop(header, None)
        self.while_back_pcs.difference_update(advanced_legacy_pcs)
        self.repeat_conditions = {
            pc: condition
            for pc, condition in self.repeat_conditions.items()
            if pc not in advanced_legacy_pcs
        }
        loop_condition_pcs = (
            set(self.while_headers)
            | set(self.repeat_conditions)
            | {
                region.condition_pc
                for region in self.active_advanced_loops.values()
                if region.condition_pc is not None
            }
        )
        phi_enabled = options.use_if_expression and options.recover_phi_expressions
        self.active_phi_headers = (
            {
                pc: region
                for pc, region in self.structured_plan.phi_by_header.items()
                if not (region.skipped_pcs & machine_pcs)
            }
            if phi_enabled
            else {}
        )
        self.active_phi_joins = (
            {
                join: tuple(
                    region for region in regions if region.condition_pc in self.active_phi_headers
                )
                for join, regions in self.structured_plan.phi_by_join.items()
                if any(region.condition_pc in self.active_phi_headers for region in regions)
            }
            if phi_enabled
            else {}
        )
        self.captured_phi_values = (
            self.structured_plan.captured_phi_values if phi_enabled else frozenset()
        )
        self.phi_definition_pcs = frozenset(
            value.origin_pc for value in self.captured_phi_values if value.origin_pc is not None
        )
        self.active_boolean_chains = (
            {
                root: chain
                for root, chain in self.structured_plan.boolean_by_root.items()
                if not (set(chain.condition_pcs) & loop_condition_pcs)
                and not (set(chain.condition_pcs) & machine_pcs)
            }
            if options.combine_boolean_conditions
            else {}
        )
        self.active_value_short_circuits = (
            {
                root: region
                for root, region in self.structured_plan.value_short_circuit_by_root.items()
                if root not in loop_condition_pcs
                and not (region.skipped_pcs & machine_pcs)
            }
            if options.combine_boolean_conditions and options.inline_single_use_temporaries
            else {}
        )
        self.active_guarded_phi_regions = {
            region.root_pc: region
            for region in self.structured_plan.guarded_phi_regions
            if not (region.skipped_pcs & machine_pcs)
        }
        self.active_decision_phi_regions = {
            region.root_block: region
            for region in self.structured_plan.decision_phi_regions
            if not (region.skipped_pcs & machine_pcs)
        }
        decision_pcs = frozenset(
            pc
            for region in self.active_decision_phi_regions.values()
            for pc in region.skipped_pcs
        )
        self.active_boolean_chains = {
            root: region
            for root, region in self.active_boolean_chains.items()
            if not (region.skipped_pcs & decision_pcs)
        }
        self.active_value_short_circuits = {
            root: region
            for root, region in self.active_value_short_circuits.items()
            if not (region.skipped_pcs & decision_pcs)
        }
        guarded_results = frozenset(
            assignment.result
            for region in self.active_guarded_phi_regions.values()
            for assignment in region.assignments
        )
        self.guarded_success_results = {
            assignment.success_value: assignment.result
            for region in self.active_guarded_phi_regions.values()
            for assignment in region.assignments
        }
        self.guarded_phi_names: dict[SSAValue, str] = {}
        self.active_phi_headers = {
            pc: region
            for pc, region in self.active_phi_headers.items()
            if not any(
                assignment.result in guarded_results for assignment in region.assignments
            )
            and not (region.skipped_pcs & decision_pcs)
        }
        self.active_phi_joins = {
            join: active
            for join, regions in self.structured_plan.phi_by_join.items()
            if (
                active := tuple(
                    region
                    for region in regions
                    if region.condition_pc in self.active_phi_headers
                )
            )
        }
        self.captured_phi_values = frozenset(
            value
            for region in self.active_phi_headers.values()
            for value in region.captured_values
        )
        self.phi_definition_pcs = frozenset(
            value.origin_pc for value in self.captured_phi_values if value.origin_pc is not None
        )
        guarded_condition_pcs = {
            pc
            for region in self.active_guarded_phi_regions.values()
            for pc in region.condition_pcs
        }
        for condition_pc in guarded_condition_pcs:
            self.if_else_regions.pop(condition_pc, None)
        self.active_structuring_skip_pcs: set[int] = set()
        for region in self.active_phi_headers.values():
            self.active_structuring_skip_pcs.update(region.skipped_pcs)
        for chain in self.active_boolean_chains.values():
            self.active_structuring_skip_pcs.update(chain.skipped_pcs)
        for short_circuit in self.active_value_short_circuits.values():
            self.active_structuring_skip_pcs.update(short_circuit.skipped_pcs)
        for guarded in self.active_guarded_phi_regions.values():
            self.active_structuring_skip_pcs.update(guarded.skipped_pcs)
        for decision in self.active_decision_phi_regions.values():
            self.active_structuring_skip_pcs.update(decision.skipped_pcs)
        self.active_structuring_skip_pcs.update(
            value.origin_pc
            for values in self.generic_loop_omitted_nil_values.values()
            for value in values
            if value.origin_pc is not None
        )
        self.labels = self._collect_labels()

    def _analyze_control_flow(self) -> None:
        for instruction in self.instructions:
            if instruction.pc in self.state_machine_plan.skipped_pcs:
                continue
            target = get_jump_target(instruction)
            if target is None:
                continue
            if instruction.name in {"JUMPBACK", "JUMP"} and target < instruction.pc:
                header = self.instruction_by_pc.get(target)
                if (
                    header is not None
                    and header.name in _CONDITIONAL_OPS
                    and _jump_target(header) > instruction.pc
                ):
                    self.while_headers[header.pc] = (
                        instruction.pc + instruction.size,
                        header,
                    )
                    self.while_back_pcs.add(instruction.pc)
            elif instruction.name in _CONDITIONAL_OPS and target < instruction.pc:
                self.repeat_starts[target] = instruction.pc
                self.repeat_conditions[instruction.pc] = instruction

        for instruction in self.instructions:
            if (
                instruction.name not in _CONDITIONAL_OPS
                or instruction.pc in self.while_headers
                or instruction.pc in self.repeat_conditions
            ):
                continue
            else_pc = get_jump_target(instruction)
            if else_pc is None or else_pc <= instruction.pc:
                continue
            skip = self.previous_by_next_pc.get(else_pc)
            if skip is None or skip.name not in {"JUMP", "JUMPX"}:
                continue
            end_pc = get_jump_target(skip)
            if end_pc is None or end_pc <= else_pc:
                continue
            self.if_else_regions[instruction.pc] = _IfElseRegion(
                else_pc=else_pc,
                end_pc=end_pc,
                skip_jump_pc=skip.pc,
            )
            self.skip_jump_pcs.add(skip.pc)

    def _numeric_loop_regions(self) -> tuple[_BytecodeLoopRegion, ...]:
        regions: list[_BytecodeLoopRegion] = []
        for instruction in self.instructions:
            if instruction.name != "FORNPREP":
                continue
            close_pc = _jump_target(instruction)
            loop = self.previous_by_next_pc.get(close_pc)
            if loop is None or loop.name != "FORNLOOP" or loop.a != instruction.a:
                continue
            regions.append(
                _BytecodeLoopRegion(
                    prep_pc=instruction.pc,
                    body_pc=instruction.pc + instruction.size,
                    loop_pc=loop.pc,
                    close_pc=close_pc,
                )
            )
        return tuple(sorted(regions, key=lambda item: (item.prep_pc, item.close_pc)))

    def _generic_loop_regions(self) -> tuple[_BytecodeLoopRegion, ...]:
        prep_names = {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}
        regions: list[_BytecodeLoopRegion] = []
        for instruction in self.instructions:
            if instruction.name not in prep_names:
                continue
            loop_pc = _jump_target(instruction)
            loop = self.instruction_by_pc.get(loop_pc)
            if loop is None or loop.name != "FORGLOOP":
                continue
            regions.append(
                _BytecodeLoopRegion(
                    prep_pc=instruction.pc,
                    body_pc=instruction.pc + instruction.size,
                    loop_pc=loop_pc,
                    close_pc=loop_pc + loop.size,
                )
            )
        return tuple(sorted(regions, key=lambda item: (item.prep_pc, item.close_pc)))

    def _generic_loop_nil_state_values(self) -> dict[int, frozenset[SSAValue]]:
        """Prove compiler-generated trailing nil iterator operands by SSA identity.

        FORGPREP keeps iterator/state/control alive through FORGLOOP, so these nil
        values have two VM uses and are intentionally not ordinary one-use inline
        candidates.  They are source-elidable only when one exact LOADNIL SSA value
        is used exclusively by the matching prep/loop pair and has no named debug
        binding.  Physical register history is never consulted.
        """

        result: dict[int, frozenset[SSAValue]] = {}
        for region in self.generic_loop_regions:
            prep = self.instruction_by_pc[region.prep_pc]
            loop = self.instruction_by_pc[region.loop_pc]
            omitted: set[SSAValue] = set()
            for register in (prep.a + 1, prep.a + 2):
                value = self.ssa.value_at_use(prep.pc, register)
                if value is None or value.kind != "instruction" or value.origin_pc is None:
                    continue
                definition = self.ssa.instruction_at(value.origin_pc)
                if (
                    definition is None
                    or definition.instruction.name != "LOADNIL"
                    or self.scope_tree.binding_for_register(register, value.origin_pc)
                    is not None
                ):
                    continue
                sites = {
                    (ssa_instruction.pc, use.register)
                    for ssa_instruction in self.ssa.instructions.values()
                    for use in ssa_instruction.uses
                    if use.value == value
                }
                expected = {(prep.pc, register), (loop.pc, register)}
                if sites == expected and self.ssa.uses_of(value) == len(expected):
                    omitted.add(value)
            if omitted:
                result[prep.pc] = frozenset(omitted)
        return result

    def _generic_iterator_operands(
        self,
        instruction: DecodedInstruction,
    ) -> tuple[Expr, ...]:
        operands = [
            self._ref_expr(register, instruction.pc)
            for register in range(instruction.a, instruction.a + 3)
        ]
        values = [
            self.ssa.value_at_use(instruction.pc, register)
            for register in range(instruction.a, instruction.a + 3)
        ]
        omitted = self.generic_loop_omitted_nil_values.get(instruction.pc, frozenset())
        while len(operands) > 1 and values[-1] in omitted:
            operands.pop()
            values.pop()
        return tuple(operands)

    def _bytecode_loop_actions(self) -> dict[int, LoopJumpAction]:
        actions: dict[int, LoopJumpAction] = {}
        regions = self.numeric_loop_regions + self.generic_loop_regions
        complex_regions = {
            region
            for region in regions
            if any(
                other is not region and region.contains(other.prep_pc)
                for other in regions
            )
            or any(
                region.contains(candidate.pc)
                and get_jump_target(candidate) == region.close_pc
                for candidate in self.instructions
                if candidate.name
                in _CONDITIONAL_OPS | {"JUMP", "JUMPBACK", "JUMPX"}
            )
            or any(
                region.contains(candidate.pc)
                and candidate.name in {"JUMP", "JUMPBACK", "JUMPX"}
                and get_jump_target(candidate) == region.loop_pc
                for candidate in self.instructions
            )
        }
        for instruction in self.instructions:
            if instruction.name not in _CONDITIONAL_OPS | {"JUMP", "JUMPBACK", "JUMPX"}:
                continue
            containing = [
                region for region in regions if region.contains(instruction.pc)
            ]
            if not containing:
                continue
            region = min(containing, key=lambda item: item.loop_pc - item.body_pc)
            target = get_jump_target(instruction)
            kind: Literal["break", "continue"]
            if target == region.loop_pc:
                kind = "continue"
            elif target == region.close_pc:
                kind = "break"
            else:
                continue
            if kind == "continue" and region not in complex_regions:
                continue
            actions[instruction.pc] = LoopJumpAction(
                pc=instruction.pc,
                kind=kind,
                target=target,
                edge=(
                    "always"
                    if instruction.name in {"JUMP", "JUMPBACK", "JUMPX"}
                    else "taken"
                ),
                loop_header=region.prep_pc,
            )
        return actions

    def _analyze_cfg_regions(self) -> None:
        for loop in self.analysis.loops:
            header_block = self.analysis.block_by_start[loop.header]
            latch_block = self.analysis.block_by_start[loop.latch]
            header = header_block.terminator
            latch = latch_block.terminator
            if header is None or latch is None:
                continue

            if header.name in _CONDITIONAL_OPS and latch.name in {"JUMP", "JUMPBACK", "JUMPX"}:
                exits = sorted(target for source, target in loop.exits if source == loop.header)
                if exits:
                    self.while_headers.setdefault(
                        header.pc,
                        (exits[0], header),
                    )
                    self.while_back_pcs.add(latch.pc)

            if latch.name in _CONDITIONAL_OPS and get_jump_target(latch) == loop.header:
                self.repeat_starts.setdefault(loop.header, latch.pc)
                self.repeat_conditions.setdefault(latch.pc, latch)

        for branch in self.analysis.branches:
            header_block = self.analysis.block_by_start[branch.header]
            condition = header_block.terminator
            join = branch.join
            if (
                condition is None
                or condition.name not in _CONDITIONAL_OPS
                or join is None
                or branch.taken <= condition.pc
                or condition.pc in self.while_headers
                or condition.pc in self.repeat_conditions
            ):
                continue

            join_block = self.analysis.block_by_start.get(join)
            if join_block is None:
                continue
            skip_candidates: list[DecodedInstruction] = []
            for predecessor in join_block.predecessors:
                predecessor_block = self.analysis.block_by_start[predecessor]
                terminator = predecessor_block.terminator
                if (
                    terminator is not None
                    and terminator.name in {"JUMP", "JUMPX"}
                    and get_jump_target(terminator) == join
                    and self.analysis.dominates(branch.fallthrough, predecessor)
                ):
                    skip_candidates.append(terminator)
            if not skip_candidates:
                continue

            skip = max(skip_candidates, key=lambda item: item.pc)
            self.if_else_regions.setdefault(
                condition.pc,
                _IfElseRegion(
                    else_pc=branch.taken,
                    end_pc=join,
                    skip_jump_pc=skip.pc,
                ),
            )
            self.skip_jump_pcs.add(skip.pc)

    def _collect_labels(self) -> set[int]:
        labels: set[int] = set()
        structured_targets = set(self.while_headers)
        structured_targets.update(self.repeat_starts)
        structured_targets.update(self.advanced_loop_plan.structured_targets)
        structured_targets.update(self.state_machine_plan.structured_targets)
        for if_region in self.if_else_regions.values():
            structured_targets.add(if_region.else_pc)
            structured_targets.add(if_region.end_pc)
        for phi_region in self.active_phi_headers.values():
            structured_targets.add(phi_region.then_block)
            structured_targets.add(phi_region.else_block)
            structured_targets.add(phi_region.join_pc)
        for chain in self.active_boolean_chains.values():
            structured_targets.add(chain.body_start)
            structured_targets.add(chain.false_start)
            structured_targets.add(chain.join)
        for decision in self.active_decision_phi_regions.values():
            structured_targets.update(decision.blocks)
            structured_targets.add(decision.join_pc)
        for instruction in self.instructions:
            if instruction.pc in self.state_machine_plan.skipped_pcs:
                continue
            target = get_jump_target(instruction)
            if (
                target is not None
                and 0 <= target <= len(self.proto.code)
                and target not in structured_targets
            ):
                labels.add(target)
        return labels

    def _name(self, register: int, pc: int) -> str:
        if register < self.proto.num_params and register in self.register_names:
            return self.register_names[register]
        binding = self.scope_tree.binding_for_register(register, pc)
        if binding is not None:
            active = _sanitize_identifier(binding.name, f"v{register}")
            self.register_names[register] = active
            return active
        if self.options.smart_variable_names and self.symbols is not None:
            planned = self.semantic_names.name_at_use(self.ssa, pc, register)
            if planned is not None:
                self.register_names[register] = planned
                return planned
            recovered = self.symbols.name_at_use(pc, register)
            if recovered is not None:
                self.register_names[register] = recovered
                return recovered
        return self.register_names.get(register, f"v{register}")

    def _definition_name(self, register: int, pc: int) -> str:
        if register < self.proto.num_params and register in self.register_names:
            return self.register_names[register]
        binding = self.scope_tree.binding_for_register(register, pc)
        if binding is not None:
            active = _sanitize_identifier(binding.name, f"v{register}")
            self.register_names[register] = active
            return active
        if self.options.smart_variable_names and self.symbols is not None:
            planned = self.semantic_names.name_at_definition(self.ssa, pc, register)
            if planned is not None:
                self.register_names[register] = planned
                return planned
            recovered = self.symbols.name_at_definition(pc, register)
            if recovered is not None:
                self.register_names[register] = recovered
                return recovered
        return self.register_names.get(register, f"v{register}")

    def _ref_expr(self, register: int, pc: int) -> Expr:
        value = self.ssa.value_at_use(pc, register)
        if value is not None:
            pending = self.pending_tables.get(value)
            if (
                pending is not None
                and self._table_value_can_inline(pending, pc)
            ):
                self.pending_tables.pop(value, None)
                return pending.expression()
            callback = self.callback_expressions.get(value)
            if callback is not None:
                return callback
            if self.options.inline_single_use_temporaries:
                expression = self.inline_expressions.get(value)
                if expression is not None:
                    return expression
        return NameExpr(self._name(register, pc))

    def _ref(self, register: int, pc: int) -> str:
        return render_expression(self._ref_expr(register, pc))

    def _transfer_inline_callback(
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
        type_name = _local_type(self.module, self.proto, register, pc)
        if type_name is None and pc == 0:
            type_name = self.parameter_type_overrides.get(register)
        if type_name is None and self.options.infer_types and self.symbols is not None:
            type_name = self.symbols.type_at_definition(pc, register)
            if type_name is None and pc == 0:
                type_name = self.symbols.entry_types.get(register)
        type_name = _source_type(type_name)
        return f"{name}: {type_name}" if type_name and type_name != "any" else name

    def _lexically_safe_local_name(self, register: int, pc: int, name: str) -> str:
        if name not in self.lexically_reserved_names:
            return name
        occupied = (
            self.declared
            | self.lexically_reserved_names
            | set(self.register_names.values())
        )
        base = name
        suffix = 2
        while f"{base}{suffix}" in occupied:
            suffix += 1
        safe = f"{base}{suffix}"
        value = self.ssa.value_defined_at(pc, register)
        forced_names = getattr(self, "_forced_value_names", None)
        if value is not None and callable(forced_names):
            forced_names()[value] = safe
        self.register_names[register] = safe
        return safe

    def _assign(self, register: int, expression: Expr | str, pc: int) -> None:
        resolved_expression = ensure_expr(expression)
        value = self.ssa.value_defined_at(pc, register)
        guarded_result = (
            self.guarded_success_results.get(value) if value is not None else None
        )
        if guarded_result is not None:
            name = self._guarded_phi_binding_name(guarded_result)
            self.out.line(
                f"{name} = {render_expression(resolved_expression, pretty_tables=True)}",
                statement=True,
            )
            self.register_names[register] = name
            return
        if self.options.inline_single_use_temporaries and self.rmw_plan.should_capture(value):
            assert value is not None
            self.inline_expressions[value] = resolved_expression
            self.register_names.setdefault(register, f"v{register}")
            return
        if value is not None and value in self.captured_phi_values:
            self.inline_expressions[value] = resolved_expression
            return
        if (
            self.options.inline_single_use_temporaries
            and value is not None
            and self.inline_plan.should_inline(value)
        ):
            self.inline_expressions[value] = resolved_expression
            self.register_names.setdefault(register, f"v{register}")
            return
        name = self._lexically_safe_local_name(
            register,
            pc,
            self._definition_name(register, pc),
        )
        if name in self.declared:
            lhs = name
        else:
            lhs = "local " + self._annotated_name(register, name, pc)
            self.declared.add(name)
        self.register_names[register] = name
        rendered = render_expression(resolved_expression, pretty_tables=True)
        self.out.line(f"{lhs} = {rendered}", statement=True)

    def _assign_many(
        self,
        registers: list[int],
        expression: Expr | str,
        pc: int,
    ) -> None:
        if len(registers) == 1:
            self._assign(registers[0], expression, pc)
            return
        rendered_expression = render_expression(
            ensure_expr(expression),
            pretty_tables=True,
        )
        names = [
            self._lexically_safe_local_name(
                register,
                pc,
                self._definition_name(register, pc),
            )
            for register in registers
        ]
        new_flags = [name not in self.declared for name in names]
        if all(new_flags):
            annotated = [
                self._annotated_name(register, name, pc)
                for register, name in zip(registers, names, strict=True)
            ]
            self.out.line(
                f"local {', '.join(annotated)} = {rendered_expression}",
                statement=True,
            )
        elif any(new_flags):
            declarations = [
                self._annotated_name(register, name, pc)
                for register, name, is_new in zip(
                    registers,
                    names,
                    new_flags,
                    strict=True,
                )
                if is_new
            ]
            self.out.line("local " + ", ".join(declarations), statement=True)
            self.out.line(
                f"{', '.join(names)} = {rendered_expression}",
                statement=True,
            )
        else:
            self.out.line(
                f"{', '.join(names)} = {rendered_expression}",
                statement=True,
            )
        self.declared.update(names)
        for register, name in zip(registers, names, strict=True):
            self.register_names[register] = name

    def _assign_phi_result(self, value: SSAValue, expression: Expr, pc: int) -> None:
        if self.ssa.uses_of(value) <= 0:
            return
        binding = self.scope_tree.binding_for_register(value.register, pc)
        if (
            self.options.inline_single_use_temporaries
            and self.ssa.uses_of(value) == 1
            and binding is None
        ):
            self.inline_expressions[value] = expression
            return
        symbol = self.symbols.symbol_for(value) if self.symbols is not None else None
        recovered_name = symbol.name if symbol is not None else None
        fallback = self.register_names.get(value.register, f"v{value.register}")
        name = _sanitize_identifier(
            binding.name if binding is not None else recovered_name,
            fallback,
        )
        name = self._lexically_safe_local_name(value.register, pc, name)
        type_name = symbol.type_name if symbol is not None else None
        if type_name is None:
            type_name = _local_type(
                self.module,
                self.proto,
                value.register,
                pc,
            )
        type_name = _source_type(type_name)
        annotated = f"{name}: {type_name}" if type_name and type_name != "any" else name
        is_new = name not in self.declared
        lhs = annotated if is_new else name
        prefix = "local " if is_new else ""
        self.out.line(
            f"{prefix}{lhs} = {render_expression(expression)}",
            statement=True,
        )
        self.declared.add(name)
        self.register_names[value.register] = name

    def _finalize_phi_regions(self, pc: int) -> None:
        for region in self.active_phi_joins.get(pc, ()):
            condition = self.phi_conditions.pop(region.condition_pc, None)
            if condition is None:
                continue
            for assignment in region.assignments:
                then_value = self.inline_expressions.pop(assignment.then_value, None)
                else_value = self.inline_expressions.pop(assignment.else_value, None)
                if then_value is None or else_value is None:
                    continue
                self._assign_phi_result(
                    assignment.result,
                    IfExpr(condition, then_value, else_value),
                    pc,
                )

    def _flush_pending_table(self, pending: PendingTableLiteral) -> None:
        if self.pending_tables.get(pending.value) is not pending:
            return
        self.pending_tables.pop(pending.value, None)
        self._assign(
            pending.register,
            pending.expression(),
            pending.emit_pc,
        )

    def _flush_pending_tables(self) -> None:
        for pending in sorted(
            tuple(self.pending_tables.values()),
            key=lambda item: (item.definition_pc, item.emit_pc),
        ):
            self._flush_pending_table(pending)

    def _pending_table_for_register(
        self,
        pc: int,
        register: int,
    ) -> PendingTableLiteral | None:
        value = self.ssa.value_at_use(pc, register)
        return self.pending_tables.get(value) if value is not None else None

    def _pending_table_for_identity(
        self,
        identity: SSAValue,
    ) -> PendingTableLiteral | None:
        return next(
            (
                pending
                for pending in self.pending_tables.values()
                if self.table_build_plan.table_identity(pending.value) == identity
            ),
            None,
        )

    def _pending_table_for_write(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        target = table_write_target_register(instruction)
        if target is None:
            return None
        return self._pending_table_for_register(instruction.pc, target)

    def _pending_table_for_move(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        if instruction.name != "MOVE":
            return None
        source_value = self.ssa.value_at_use(instruction.pc, instruction.b)
        destination_value = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if source_value is None or destination_value is None:
            return None
        pending = self.pending_tables.get(source_value)
        if pending is None or self.ssa.uses_of(source_value) != 1:
            return None
        if instruction.a in pending.dependency_registers:
            return None
        return pending

    def _open_table_parent_for_producer(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        next_instruction = self.next_instruction_by_pc.get(instruction.pc)
        ownership = (
            self.table_build_plan.call_at(instruction.pc)
            if instruction.name in {"CALL", "CALLFB"}
            else None
        )
        if ownership is not None and ownership.result_shape == CallResultShape.OPEN:
            if (
                next_instruction is None
                or next_instruction.pc != ownership.consumer_pc
                or next_instruction.name != "SETLIST"
                or next_instruction.c != 0
            ):
                return None
            return self._pending_table_for_identity(ownership.owner_value)
        if (
            next_instruction is None
            or next_instruction.name != "SETLIST"
            or next_instruction.c != 0
            or next_instruction.b != instruction.a
        ):
            return None
        pending = self._pending_table_for_write(next_instruction)
        if pending is None:
            return None
        access = self.analysis.register_accesses[instruction.pc]
        if pending.register in access.uses:
            return None
        semantics = setlist_semantics(next_instruction)
        if semantics is None:
            return None
        start_index = semantics.semantic_first_array_index
        return pending if pending.can_add_open_tail(start_index) else None

    def _flush_tables_before(self, instruction: DecodedInstruction) -> None:
        if not self.options.reconstruct_table_literals or not self.pending_tables:
            return
        access = self.analysis.register_accesses[instruction.pc]
        target_pending = (
            self._pending_table_for_write(instruction) if is_table_write(instruction) else None
        )
        transfer_pending = self._pending_table_for_move(instruction)
        open_parent = (
            self._open_table_parent_for_producer(instruction)
            if instruction.name in {"CALL", "CALLFB", "GETVARARGS"}
            else None
        )
        owned_call = (
            self.table_build_plan.call_at(instruction.pc)
            if instruction.name in {"CALL", "CALLFB"}
            or instruction.name.startswith("FASTCALL")
            else None
        )
        protected_identities = (
            owned_call.protected_values if owned_call is not None else frozenset()
        )
        write_sources = (
            table_write_source_registers(instruction) if target_pending is not None else frozenset()
        )
        ssa_instruction = self.ssa.instruction_at(instruction.pc)
        used_values = (
            frozenset(use.value for use in ssa_instruction.uses)
            if ssa_instruction is not None
            else frozenset()
        )
        closure = (
            self.parent_proto_plan.at_creation(instruction.pc)
            if self.parent_proto_plan is not None
            else None
        )
        if closure is not None:
            used_values |= frozenset(
                capture.source_value
                for capture in closure.captures
                if capture.source_value is not None
            )
        table_value_registers = table_write_value_registers(instruction)
        source_table_values = frozenset(
            value
            for register in table_value_registers
            if (value := self.ssa.value_at_use(instruction.pc, register)) is not None
        )

        for pending in sorted(
            tuple(self.pending_tables.values()),
            key=lambda item: (item.definition_pc, item.emit_pc),
        ):
            if self.table_build_plan.is_in_transaction(
                pending.value,
                protected_identities,
            ):
                continue
            if pending is transfer_pending:
                continue
            if pending is target_pending:
                continue
            if pending is open_parent:
                continue
            if pending.value in source_table_values:
                continue
            if target_pending is not None and pending.register in write_sources:
                continue
            if access.definitions & pending.dependency_registers:
                self._flush_pending_table(pending)
                continue
            if pending.value in used_values:
                self._flush_pending_table(pending)
                continue
            if is_table_write(instruction):
                if target_pending is None:
                    self._flush_pending_table(pending)
                continue
            if not is_safe_table_gap(instruction):
                self._flush_pending_table(pending)

    def _dependencies_for_value(
        self,
        value: SSAValue,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> frozenset[SSAValue]:
        callback_dependencies = self.callback_dependencies.get(value)
        if callback_dependencies is not None:
            return callback_dependencies
        if value in seen or value.kind != "instruction":
            return frozenset({value})
        if value not in self.inline_expressions or value.origin_pc is None:
            return frozenset({value})
        instruction = self.ssa.instruction_at(value.origin_pc)
        if instruction is None:
            return frozenset({value})
        dependencies: set[SSAValue] = set()
        next_seen = seen | frozenset({value})
        for use in instruction.uses:
            dependencies.update(self._dependencies_for_value(use.value, next_seen))
        return frozenset(dependencies)

    def _structured_value_expression(
        self,
        value: SSAValue,
        region: ValueShortCircuitRegion,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> Expr | None:
        if value in seen:
            return None
        if value.kind == "entry":
            name = self.semantic_names.entry_names.get(
                value.register,
                self.register_names.get(value.register, f"arg{value.register + 1}"),
            )
            return NameExpr(name)
        if (
            value not in region.expression_values
            or value.kind != "instruction"
            or value.origin_pc is None
        ):
            return None
        definition = self.ssa.instruction_at(value.origin_pc)
        if definition is None:
            return None
        instruction = definition.instruction
        next_seen = seen | frozenset({value})

        def operand(register: int) -> Expr | None:
            source = next(
                (use.value for use in definition.uses if use.register == register),
                None,
            )
            return (
                self._structured_value_expression(source, region, next_seen)
                if source is not None
                else None
            )

        name = instruction.name
        if name == "LOADNIL":
            return LiteralExpr("nil")
        if name == "LOADB" and instruction.c == 0:
            return LiteralExpr("true" if instruction.b else "false")
        if name == "LOADN":
            return LiteralExpr(str(instruction.d))
        if name == "LOADK":
            return source_expr(_constant_expr(self.proto, instruction.d))
        if name == "LOADKX":
            return source_expr(_constant_expr(self.proto, instruction.aux or 0))
        if name == "MOVE":
            return operand(instruction.b)
        if name == "GETGLOBAL":
            return RawExpr(self._global_key(instruction), Precedence.POSTFIX)
        if name == "GETIMPORT":
            return RawExpr(
                _decode_import(self.proto, instruction.aux),
                Precedence.POSTFIX,
            )
        if name == "GETUPVAL":
            binding = self.upvalue_bindings.get(instruction.b)
            if binding is not None:
                return binding
            upvalue = (
                self.proto.upvalue_names[instruction.b]
                if instruction.b < len(self.proto.upvalue_names)
                else None
            )
            return NameExpr(_sanitize_identifier(upvalue, f"upvalue_{instruction.b}"))
        if name == "GETTABLE":
            base = operand(instruction.b)
            index = operand(instruction.c)
            return IndexExpr(base, index) if base is not None and index is not None else None
        if name in {"GETTABLEKS", "GETUDATAKS"}:
            base = operand(instruction.b)
            return FieldExpr(base, self._table_key(instruction)) if base is not None else None
        if name == "GETTABLEN":
            base = operand(instruction.b)
            return (
                IndexExpr(base, LiteralExpr(str(instruction.c + 1)))
                if base is not None
                else None
            )
        if name in _BINARY_OPS:
            left = operand(instruction.b)
            right = operand(instruction.c)
            return (
                BinaryExpr(left, _BINARY_OPS[name], right)
                if left is not None and right is not None
                else None
            )
        if name in _BINARY_CONST_OPS:
            left = operand(instruction.b)
            return (
                BinaryExpr(
                    left,
                    _BINARY_CONST_OPS[name],
                    source_expr(_constant_expr(self.proto, instruction.c)),
                )
                if left is not None
                else None
            )
        if name in {"SUBRK", "DIVRK"}:
            right = operand(instruction.c)
            return (
                BinaryExpr(
                    source_expr(_constant_expr(self.proto, instruction.b)),
                    "-" if name == "SUBRK" else "/",
                    right,
                )
                if right is not None
                else None
            )
        if name in _UNARY_OPS:
            item = operand(instruction.b)
            return UnaryExpr(_UNARY_OPS[name].strip(), item) if item is not None else None
        if name == "CONCAT":
            items = [operand(register) for register in range(instruction.b, instruction.c + 1)]
            if any(item is None for item in items):
                return None
            expression = cast(Expr, items[-1])
            for item in reversed(items[:-1]):
                expression = BinaryExpr(cast(Expr, item), "..", expression)
            return expression
        return None

    def _capture_value_short_circuit(
        self,
        region: ValueShortCircuitRegion,
    ) -> bool:
        left = self._structured_value_expression(region.left, region)
        right = self._structured_value_expression(region.right, region)
        if left is None or right is None:
            return False
        self.inline_expressions[region.result] = BinaryExpr(
            left,
            region.operator,
            right,
        )
        return True

    def _decision_value_expression(
        self,
        value: SSAValue | None,
        region: DecisionPhiRegion,
        cache: dict[SSAValue, Expr],
        seen: frozenset[SSAValue] = frozenset(),
    ) -> Expr | None:
        if value is None or value in seen:
            return None
        cached = cache.get(value)
        if cached is not None:
            return cached
        if value.kind == "entry":
            entry_expression = NameExpr(
                self.semantic_names.entry_names.get(
                    value.register,
                    self.register_names.get(value.register, f"arg{value.register + 1}"),
                )
            )
            cache[value] = entry_expression
            return entry_expression
        if value.kind != "instruction" or value.origin_pc is None:
            return None
        block = self.analysis.block_for_pc.get(value.origin_pc)
        definition = self.ssa.instruction_at(value.origin_pc)
        if block not in region.blocks or definition is None:
            return None
        instruction = definition.instruction
        next_seen = seen | frozenset({value})

        def operand(register: int) -> Expr | None:
            source = next(
                (use.value for use in definition.uses if use.register == register),
                None,
            )
            return self._decision_value_expression(source, region, cache, next_seen)

        name = instruction.name
        expression: Expr | None = None
        if name == "LOADNIL":
            expression = LiteralExpr("nil")
        elif name == "LOADB" and instruction.c == 0:
            expression = LiteralExpr("true" if instruction.b else "false")
        elif name == "LOADN":
            expression = LiteralExpr(str(instruction.d))
        elif name == "LOADK":
            expression = source_expr(_constant_expr(self.proto, instruction.d))
        elif name == "LOADKX":
            expression = source_expr(_constant_expr(self.proto, instruction.aux or 0))
        elif name == "MOVE":
            expression = operand(instruction.b)
        elif name == "GETGLOBAL":
            expression = RawExpr(self._global_key(instruction), Precedence.POSTFIX)
        elif name == "GETIMPORT":
            expression = RawExpr(
                _decode_import(self.proto, instruction.aux),
                Precedence.POSTFIX,
            )
        elif name == "GETUPVAL":
            expression = self.upvalue_bindings.get(instruction.b)
            if expression is None:
                upvalue = (
                    self.proto.upvalue_names[instruction.b]
                    if instruction.b < len(self.proto.upvalue_names)
                    else None
                )
                expression = NameExpr(
                    _sanitize_identifier(upvalue, f"upvalue_{instruction.b}")
                )
        elif name == "GETTABLE":
            base = operand(instruction.b)
            index = operand(instruction.c)
            expression = IndexExpr(base, index) if base is not None and index is not None else None
        elif name in {"GETTABLEKS", "GETUDATAKS"}:
            base = operand(instruction.b)
            expression = FieldExpr(base, self._table_key(instruction)) if base is not None else None
        elif name == "GETTABLEN":
            base = operand(instruction.b)
            expression = (
                IndexExpr(base, LiteralExpr(str(instruction.c + 1)))
                if base is not None
                else None
            )
        elif name in _BINARY_OPS:
            left = operand(instruction.b)
            right = operand(instruction.c)
            expression = (
                BinaryExpr(left, _BINARY_OPS[name], right)
                if left is not None and right is not None
                else None
            )
        elif name in _BINARY_CONST_OPS:
            left = operand(instruction.b)
            expression = (
                BinaryExpr(
                    left,
                    _BINARY_CONST_OPS[name],
                    source_expr(_constant_expr(self.proto, instruction.c)),
                )
                if left is not None
                else None
            )
        elif name in {"SUBRK", "DIVRK"}:
            right = operand(instruction.c)
            expression = (
                BinaryExpr(
                    source_expr(_constant_expr(self.proto, instruction.b)),
                    "-" if name == "SUBRK" else "/",
                    right,
                )
                if right is not None
                else None
            )
        elif name in _UNARY_OPS:
            item = operand(instruction.b)
            expression = UnaryExpr(_UNARY_OPS[name].strip(), item) if item is not None else None
        elif name == "CONCAT":
            items = [operand(register) for register in range(instruction.b, instruction.c + 1)]
            if items and all(item is not None for item in items):
                expression = cast(Expr, items[-1])
                for item in reversed(items[:-1]):
                    expression = BinaryExpr(cast(Expr, item), "..", expression)
        elif name in {"CALL", "CALLFB"}:
            frame = self.call_frames.at(instruction.pc)
            if frame is not None and not frame.is_open_result:
                arguments = tuple(
                    self._decision_value_expression(argument, region, cache, next_seen)
                    for argument in frame.arguments
                )
                if all(argument is not None for argument in arguments):
                    if frame.namecall_pc is not None and frame.receiver is not None:
                        receiver = self._decision_value_expression(
                            frame.receiver,
                            region,
                            cache,
                            next_seen,
                        )
                        namecall = self.instruction_by_pc.get(frame.namecall_pc)
                        if receiver is not None and namecall is not None:
                            expression = MethodCallExpr(
                                receiver,
                                self._table_key(namecall),
                                cast(tuple[Expr, ...], arguments),
                            )
                    else:
                        function = self._decision_value_expression(
                            frame.callee,
                            region,
                            cache,
                            next_seen,
                        )
                        if function is not None:
                            expression = CallExpr(
                                function,
                                cast(tuple[Expr, ...], arguments),
                            )
        if expression is not None:
            cache[value] = expression
        return expression

    def _decision_condition_expression(
        self,
        instruction: DecodedInstruction,
        region: DecisionPhiRegion,
        cache: dict[SSAValue, Expr],
    ) -> Expr | None:
        def used(register: int) -> Expr | None:
            return self._decision_value_expression(
                self.ssa.value_at_use(instruction.pc, register),
                region,
                cache,
            )

        name = instruction.name
        left = used(instruction.a)
        if left is None:
            return None
        if name == "JUMPIF":
            return UnaryExpr("not", left)
        if name == "JUMPIFNOT":
            return left
        if name in _COMPARISON_FALLTHROUGH:
            right = used((instruction.aux or 0) & 0xFF)
            return (
                BinaryExpr(left, _COMPARISON_FALLTHROUGH[name], right)
                if right is not None
                else None
            )
        if name.startswith("JUMPXEQK"):
            if name == "JUMPXEQKNIL":
                right = LiteralExpr("nil")
            elif name == "JUMPXEQKB":
                right = LiteralExpr("true" if (instruction.aux or 0) & 1 else "false")
            else:
                right = source_expr(
                    _constant_expr(self.proto, (instruction.aux or 0) & 0xFFFFFF)
                )
            return BinaryExpr(left, "==" if instruction.aux_not else "~=", right)
        return None

    def _decision_phi_expression(self, region: DecisionPhiRegion) -> Expr | None:
        cache: dict[SSAValue, Expr] = {}
        block_cache: dict[int, Expr] = {}
        visiting: set[int] = set()
        branches = {branch.header: branch for branch in self.analysis.branches}

        def leaf(block: int) -> Expr | None:
            return self._decision_value_expression(
                region.phi.operands.get(block),
                region,
                cache,
            )

        def build(block_start: int) -> Expr | None:
            cached = block_cache.get(block_start)
            if cached is not None:
                return cached
            if block_start in visiting or block_start not in region.blocks:
                return None
            visiting.add(block_start)
            block = self.analysis.block_by_start[block_start]
            branch = branches.get(block_start)
            expression: Expr | None
            if branch is not None and block.terminator is not None:
                instruction = block.terminator
                fallthrough = (
                    leaf(block_start)
                    if branch.fallthrough == region.join_pc
                    else build(branch.fallthrough)
                )
                taken = (
                    leaf(block_start)
                    if branch.taken == region.join_pc
                    else build(branch.taken)
                )
                tested = self.ssa.value_at_use(instruction.pc, instruction.a)
                operand = region.phi.operands.get(block_start)
                tested_expression = self._decision_value_expression(
                    tested,
                    region,
                    cache,
                )
                if (
                    tested_expression is not None
                    and operand == tested
                    and instruction.name in {"JUMPIF", "JUMPIFNOT"}
                ):
                    if branch.taken == region.join_pc and fallthrough is not None:
                        expression = BinaryExpr(
                            tested_expression,
                            "or" if instruction.name == "JUMPIF" else "and",
                            fallthrough,
                        )
                    elif branch.fallthrough == region.join_pc and taken is not None:
                        expression = BinaryExpr(
                            tested_expression,
                            "and" if instruction.name == "JUMPIF" else "or",
                            taken,
                        )
                    else:
                        expression = None
                else:
                    condition = self._decision_condition_expression(
                        instruction,
                        region,
                        cache,
                    )
                    if (
                        condition is not None
                        and isinstance(fallthrough, BinaryExpr)
                        and fallthrough.operator == "or"
                        and fallthrough.right == taken
                    ):
                        expression = BinaryExpr(
                            BinaryExpr(condition, "and", fallthrough.left),
                            "or",
                            taken,
                        )
                    else:
                        expression = (
                            IfExpr(condition, fallthrough, taken)
                            if condition is not None
                            and fallthrough is not None
                            and taken is not None
                            else None
                        )
            elif region.join_pc in block.successors:
                expression = leaf(block_start)
            elif len(block.successors) == 1:
                expression = build(next(iter(block.successors)))
            else:
                expression = None
            visiting.remove(block_start)
            if expression is not None:
                block_cache[block_start] = expression
            return expression

        return build(region.root_block)

    def _literal_value_expression(self, value: SSAValue) -> Expr | None:
        if value.kind != "instruction" or value.origin_pc is None:
            return None
        definition = self.ssa.instruction_at(value.origin_pc)
        if definition is None:
            return None
        instruction = definition.instruction
        if instruction.name == "LOADNIL":
            return LiteralExpr("nil")
        if instruction.name == "LOADB" and instruction.c == 0:
            return LiteralExpr("true" if instruction.b else "false")
        if instruction.name == "LOADN":
            return LiteralExpr(str(instruction.d))
        if instruction.name == "LOADK":
            return source_expr(_constant_expr(self.proto, instruction.d))
        if instruction.name == "LOADKX":
            return source_expr(_constant_expr(self.proto, instruction.aux or 0))
        return None

    def _guarded_phi_binding_name(self, value: SSAValue) -> str:
        existing = self.guarded_phi_names.get(value)
        if existing is not None:
            return existing
        phi_names = getattr(self, "_all_phi_names", None)
        if phi_names is not None:
            planned = phi_names().get(value)
            if planned is not None:
                name = cast(str, planned)
                self.guarded_phi_names[value] = name
                return name
        base = "result"
        candidate = base
        suffix = 2
        while candidate in self.declared:
            candidate = f"{base}{suffix}"
            suffix += 1
        self.guarded_phi_names[value] = candidate
        return candidate

    def _emit_guarded_phi_initializers(self, region: GuardedPhiRegion) -> None:
        for assignment in region.assignments:
            expression = self._literal_value_expression(assignment.default_value)
            if expression is None:
                continue
            name = self._guarded_phi_binding_name(assignment.result)
            if name in self.declared:
                self.out.line(
                    f"{name} = {render_expression(expression)}",
                    statement=True,
                )
            else:
                self.out.line(
                    f"local {name} = {render_expression(expression)}",
                    statement=True,
                )
                self.declared.add(name)
            self.register_names[assignment.result.register] = name

    def _table_value_can_inline(
        self,
        child: PendingTableLiteral,
        consumer_pc: int,
    ) -> bool:
        accounted_uses = 0
        for ssa_instruction in self.ssa.instructions.values():
            matching_uses = tuple(use for use in ssa_instruction.uses if use.value == child.value)
            if not matching_uses:
                continue
            accounted_uses += len(matching_uses)
            instruction = ssa_instruction.instruction
            target = table_write_target_register(instruction)
            if instruction.pc == consumer_pc:
                if not is_table_write(
                    instruction
                ) or child.register not in table_write_source_registers(instruction):
                    return False
                continue
            if (
                not is_table_write(instruction)
                or target != child.register
                or self.ssa.value_at_use(instruction.pc, target) != child.value
            ):
                return False
        return accounted_uses == self.ssa.uses_of(child.value)

    def _capture_register_expression(
        self,
        owner: PendingTableLiteral,
        register: int,
        pc: int,
        *,
        allow_nested: bool,
    ) -> tuple[Expr, frozenset[SSAValue]] | None:
        value = self.ssa.value_at_use(pc, register)
        expression: Expr
        child = self.pending_tables.get(value) if value is not None else None
        if child is owner:
            return None
        if child is not None:
            if (
                allow_nested
                and value is not None
                and self._table_value_can_inline(child, pc)
                and owner.can_adopt(child)
            ):
                self.pending_tables.pop(child.value, None)
                expression = child.expression()
                if not owner.adopt(child):
                    return None
                return expression, frozenset()
            self._flush_pending_table(child)
        expression = self._ref_expr(register, pc)
        dependencies = self._dependencies_for_value(value) if value is not None else frozenset()
        return expression, dependencies

    def _record_table_write(self, instruction: DecodedInstruction) -> bool:
        pending = self._pending_table_for_write(instruction)
        if pending is None:
            return False
        pc = instruction.pc
        target = table_write_target_register(instruction)
        source_registers = table_write_source_registers(instruction)
        if target is not None and target in source_registers:
            self._flush_pending_table(pending)
            return False

        success = False
        if instruction.name in {"SETTABLEKS", "SETUDATAKS"}:
            captured = self._capture_register_expression(
                pending,
                instruction.a,
                pc,
                allow_nested=True,
            )
            if captured is not None:
                value, dependencies = captured
                success = pending.add_named(
                    self._table_key(instruction),
                    value,
                    dependencies,
                )
        elif instruction.name == "SETTABLEN":
            captured = self._capture_register_expression(
                pending,
                instruction.a,
                pc,
                allow_nested=True,
            )
            if captured is not None:
                value, dependencies = captured
                success = pending.add_index(
                    instruction.c + 1,
                    value,
                    dependencies,
                )
        elif instruction.name == "SETTABLE":
            captured_key = self._capture_register_expression(
                pending,
                instruction.c,
                pc,
                allow_nested=False,
            )
            captured_value = self._capture_register_expression(
                pending,
                instruction.a,
                pc,
                allow_nested=True,
            )
            if captured_key is not None and captured_value is not None:
                key, key_dependencies = captured_key
                value, value_dependencies = captured_value
                success = pending.add_dynamic(
                    key,
                    value,
                    key_dependencies | value_dependencies,
                )
        elif instruction.name == "SETLIST" and instruction.c > 0:
            semantics = setlist_semantics(instruction)
            if semantics is None or semantics.fixed_value_count is None:
                return False
            count = semantics.fixed_value_count
            start_index = semantics.semantic_first_array_index
            entries: list[tuple[int, Expr, frozenset[SSAValue]]] = []
            for index in range(count):
                captured = self._capture_register_expression(
                    pending,
                    instruction.b + index,
                    pc,
                    allow_nested=True,
                )
                if captured is None:
                    break
                value, dependencies = captured
                entries.append((start_index + index, value, dependencies))
            if len(entries) == count:
                success = pending.add_setlist_entries(tuple(entries))
        elif instruction.name == "SETLIST" and instruction.c == 0:
            open_captured = self.pending_open_table_values.pop(
                pc,
                None,
            )
            if open_captured is not None and open_captured[2] == pc:
                value, dependencies, _consumer_pc = open_captured
                semantics = setlist_semantics(instruction)
                if semantics is None:
                    return False
                start_index = semantics.semantic_first_array_index
                multi_use = self.ssa.multi_use_at(pc)
                prefix_registers = (
                    multi_use.prefix_registers
                    if multi_use is not None and multi_use.kind == "setlist"
                    else ()
                )
                fixed_entries: list[
                    tuple[int, Expr, frozenset[SSAValue]]
                ] = []
                for offset, register in enumerate(prefix_registers):
                    captured = self._capture_register_expression(
                        pending,
                        register,
                        pc,
                        allow_nested=True,
                    )
                    if captured is None:
                        break
                    prefix_value, prefix_dependencies = captured
                    fixed_entries.append(
                        (start_index + offset, prefix_value, prefix_dependencies)
                    )
                success = len(fixed_entries) == len(prefix_registers) and pending.add_open_setlist(
                    start_index,
                    tuple(fixed_entries),
                    value,
                    dependencies,
                )
                if success:
                    return True

        if success:
            return True
        self._flush_pending_table(pending)
        return False

    def _transfer_pending_table(self, instruction: DecodedInstruction) -> bool:
        pending = self._pending_table_for_move(instruction)
        if pending is None:
            return False
        destination = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if destination is None:
            return False
        self.pending_tables.pop(pending.value, None)
        pending.rebind(destination, instruction.a, instruction.pc)
        self.pending_tables[destination] = pending
        self.register_names.setdefault(instruction.a, f"v{instruction.a}")
        return True

    def _start_pending_table(
        self,
        instruction: DecodedInstruction,
    ) -> PendingTableLiteral | None:
        value = self.ssa.value_defined_at(instruction.pc, instruction.a)
        if value is None:
            return None
        template_kind: str | None = None
        pending = PendingTableLiteral(
            value=value,
            register=instruction.a,
            definition_pc=instruction.pc,
        )
        if instruction.name == "DUPTABLE":
            constant = _constant(self.proto, instruction.d)
            if constant is None or constant.kind not in {"table", "table_with_constants"}:
                return None
            template_kind = constant.kind
            pending.template_kind = template_kind
            if constant.kind == "table_with_constants" and isinstance(
                constant.value,
                tuple,
            ):
                pairs = cast(tuple[tuple[int, int], ...], constant.value)
                for key_index, value_index in pairs:
                    if value_index < 0:
                        continue
                    key = source_expr(_constant_expr(self.proto, key_index))
                    item = source_expr(_constant_expr(self.proto, value_index))
                    if not pending.add_dynamic(key, item):
                        return None
        self.pending_tables[value] = pending
        self.register_names.setdefault(instruction.a, f"v{instruction.a}")
        return pending

    def _capture_open_table_value(
        self,
        instruction: DecodedInstruction,
        expression: Expr,
    ) -> bool:
        parent = self._open_table_parent_for_producer(instruction)
        next_instruction = self.next_instruction_by_pc.get(instruction.pc)
        if parent is None or next_instruction is None:
            return False
        dependency_values: set[SSAValue] = set()
        for register in self.analysis.register_accesses[instruction.pc].uses:
            value = self.ssa.value_at_use(instruction.pc, register)
            if value is not None:
                dependency_values.update(self._dependencies_for_value(value))
        dependencies = frozenset(dependency_values)
        self.pending_open_table_values[next_instruction.pc] = (
            expression,
            dependencies,
            next_instruction.pc,
        )
        return True

    def _capture_owned_table_call(
        self,
        instruction: DecodedInstruction,
        expression: Expr,
    ) -> bool:
        ownership = self.table_build_plan.call_at(instruction.pc)
        if (
            ownership is None
            or ownership.result_shape != CallResultShape.FIXED_ONE
            or ownership.result_value is None
            or self._pending_table_for_identity(ownership.owner_value) is None
        ):
            return False
        self.inline_expressions[ownership.result_value] = expression
        self.register_names.setdefault(instruction.a, f"v{instruction.a}")
        return True

    def _close_blocks(self, pc: int) -> None:
        if pc in self.else_transitions:
            end_pc = self.else_transitions.pop(pc)
            self.out.transition("else")
            self.block_closures[end_pc].append("end")
        for close_text in reversed(self.block_closures.pop(pc, [])):
            self.out.close(close_text)

    def _open_until(self, target: int, header: str, close_text: str = "end") -> bool:
        if target <= 0 or target > len(self.proto.code):
            return False
        self.out.open(header)
        self.block_closures[target].append(close_text)
        return True

    def _constant_key_index(self, instruction: DecodedInstruction) -> int:
        if instruction.name in {"GETUDATAKS", "SETUDATAKS", "NAMECALLUDATA"}:
            return (instruction.aux or 0) & 0xFFFF
        return instruction.aux if instruction.aux is not None else -1

    def _global_key(self, instruction: DecodedInstruction) -> str:
        index = instruction.aux if instruction.aux is not None else -1
        key = _constant_string(self.proto, index)
        return _global(key) if key is not None else f"_G[K{instruction.aux}]"

    def _table_key(self, instruction: DecodedInstruction) -> str:
        index = self._constant_key_index(instruction)
        key = _constant_string(self.proto, index)
        return key if key is not None else f"K{index}"

    def _callback_capture_bindings(
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
                    binding = NameExpr(_sanitize_identifier(name, f"upvalue_{capture.b}"))
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
        *,
        capture_bindings: dict[int, Expr] | None = None,
    ) -> tuple[Expr, frozenset[SSAValue]]:
        child = self.module.protos[child_id]
        bindings, dependencies = self._callback_capture_bindings(
            instruction,
            child,
        )
        if capture_bindings:
            bindings.update(capture_bindings)
        callback_out = _Emitter(self.options.semicolons)
        closure_value = self.ssa.value_defined_at(instruction.pc, instruction.a)
        callback_types = (
            self.callback_plan.parameter_types_by_value.get(closure_value, ())
            if closure_value is not None and self.options.roblox_api_types
            else ()
        )
        context = self.contextual_plan.for_value(closure_value)
        parameter_name_overrides = dict(context.parameter_names) if context is not None else {}
        parameter_type_overrides = {
            index: type_name
            for index, type_name in enumerate(callback_types)
            if index < child.num_params and not type_name.startswith("...")
        }
        if context is not None:
            parameter_type_overrides.update(context.parameter_types)
        _FunctionLifter(
            self.module,
            child,
            self.proto_names,
            self.options,
            callback_out,
            inline_only_proto_ids=self.inline_only_proto_ids,
            upvalue_bindings=bindings,
            parameter_name_overrides=parameter_name_overrides,
            parameter_type_overrides=parameter_type_overrides,
            return_type_override=context.return_type if context is not None else None,
            module_analysis=self.module_analysis,
            proto_emission_plan=self.proto_emission_plan,
        ).lift(as_function=True, anonymous_function=True)
        return (
            RawExpr(callback_out.render().strip(), Precedence.ATOM),
            dependencies,
        )

    def _planned_function_name(self, instance: ProtoInstancePlan) -> str:
        existing = self.planned_function_names.get(instance.creation_pc)
        if existing is not None:
            return existing
        fallback = "recursiveFunction" if instance.recursive else "localFunction"
        base = _sanitize_identifier(instance.binding_hint, fallback)
        candidate = base
        suffix = 2
        occupied = self.declared | set(self.planned_function_names.values())
        while candidate in occupied:
            candidate = f"{base}{suffix}"
            suffix += 1
        self.planned_function_names[instance.creation_pc] = candidate
        return candidate

    def _recursion_group_names(
        self,
        group: tuple[int, ...],
    ) -> dict[int, str]:
        assert self.parent_proto_plan is not None
        return {
            pc: self._planned_function_name(self.parent_proto_plan.by_creation_pc[pc])
            for pc in group
        }

    def _planned_capture_overrides(
        self,
        instance: ProtoInstancePlan,
        *,
        own_name: str | None = None,
        group_names: dict[int, str] | None = None,
    ) -> dict[int, Expr]:
        overrides: dict[int, Expr] = {}
        binding_names: dict[object, str] = {}
        reference_cell_names: dict[int, str] = {}
        if group_names is not None and self.parent_proto_plan is not None:
            for creation_pc, name in group_names.items():
                binding = self.parent_proto_plan.by_creation_pc[creation_pc].binding
                if binding is not None:
                    binding_names[binding] = name
                creation = self.instruction_by_pc.get(creation_pc)
                if creation is not None:
                    reference_cell_names[creation.a] = name
        for capture in instance.captures:
            if own_name is not None and capture.source_value == instance.closure_value:
                overrides[capture.upvalue_index] = NameExpr(own_name)
                continue
            group_name = binding_names.get(capture.source_binding)
            if group_name is None and capture.kind == "reference":
                group_name = reference_cell_names.get(capture.source_register)
            if group_name is not None:
                overrides[capture.upvalue_index] = NameExpr(group_name)
        return overrides

    def _emit_predeclared_group(self, instance: ProtoInstancePlan) -> dict[int, str]:
        group = instance.recursion_group
        names = self._recursion_group_names(group)
        if group not in self.emitted_recursion_groups:
            self.out.line(
                "local " + ", ".join(names[pc] for pc in group),
                statement=True,
            )
            self.declared.update(names.values())
            self.emitted_recursion_groups.add(group)
        return names

    def _emit_planned_closure(self, instruction: DecodedInstruction) -> bool:
        if self.parent_proto_plan is None:
            return False
        instance = self.parent_proto_plan.at_creation(instruction.pc)
        if instance is None or instance.emission_kind == "shared-proto":
            return False
        if instance.emission_kind == "inline-expression":
            expression, dependencies = self._anonymous_function_expr(
                instance.child_proto_id,
                instruction,
                capture_bindings=self._planned_capture_overrides(instance),
            )
            self.callback_expressions[instance.closure_value] = expression
            self.callback_dependencies[instance.closure_value] = dependencies
            self.register_names.setdefault(instruction.a, f"v{instruction.a}")
            return True
        if instance.emission_kind in {"method-declaration", "field-declaration"}:
            return True

        child = self.module.protos[instance.child_proto_id]
        context = self.contextual_plan.for_value(instance.closure_value)
        if instance.emission_kind == "predeclared-assignment":
            group_names = self._emit_predeclared_group(instance)
            name = group_names[instance.creation_pc]
            expression, _dependencies = self._anonymous_function_expr(
                instance.child_proto_id,
                instruction,
                capture_bindings=self._planned_capture_overrides(
                    instance,
                    own_name=name,
                    group_names=group_names,
                ),
            )
            self.out.line(
                f"{name} = {render_expression(expression)}",
                statement=True,
            )
        else:
            name = self._planned_function_name(instance)
            bindings, _dependencies = self._callback_capture_bindings(
                instruction,
                child,
            )
            bindings.update(
                self._planned_capture_overrides(instance, own_name=name)
            )
            _FunctionLifter(
                self.module,
                child,
                self.proto_names,
                self.options,
                self.out,
                inline_only_proto_ids=self.inline_only_proto_ids,
                upvalue_bindings=bindings,
                parameter_name_overrides=(
                    dict(context.parameter_names) if context is not None else None
                ),
                parameter_type_overrides=(
                    dict(context.parameter_types) if context is not None else None
                ),
                return_type_override=context.return_type if context is not None else None,
                module_analysis=self.module_analysis,
                proto_emission_plan=self.proto_emission_plan,
                semantic_function_role=(
                    "recursive" if instance.recursive else "normal"
                ),
            ).lift(
                as_function=True,
                function_name_override=name,
                local_function=True,
            )
        self.register_names[instruction.a] = name
        self.declared.add(name)
        return True

    def _emit_planned_method(self, instruction: DecodedInstruction) -> bool:
        if self.parent_proto_plan is None:
            return False
        instance = self.parent_proto_plan.at_terminal(instruction.pc)
        if instance is None or instance.method_name is None:
            return False
        pending = self._pending_table_for_write(instruction)
        if pending is not None:
            self._flush_pending_table(pending)
        creation = self.instruction_by_pc.get(instance.creation_pc)
        if creation is None:
            return False
        child = self.module.protos[instance.child_proto_id]
        bindings, _dependencies = self._callback_capture_bindings(creation, child)
        context = self.contextual_plan.for_value(instance.closure_value)
        base = self._ref_expr(instruction.b, instruction.pc)
        _FunctionLifter(
            self.module,
            child,
            self.proto_names,
            self.options,
            self.out,
            inline_only_proto_ids=self.inline_only_proto_ids,
            upvalue_bindings=bindings,
            parameter_name_overrides=(
                dict(context.parameter_names) if context is not None else {0: "self"}
            ),
            parameter_type_overrides=(
                dict(context.parameter_types) if context is not None else None
            ),
            return_type_override=context.return_type if context is not None else None,
            module_analysis=self.module_analysis,
            proto_emission_plan=self.proto_emission_plan,
            semantic_function_role="method",
        ).lift(
            as_function=True,
            method_declaration=(base, instance.method_name),
        )
        return True

    def _emit_planned_field_function(self, instruction: DecodedInstruction) -> bool:
        if self.parent_proto_plan is None:
            return False
        instance = self.parent_proto_plan.at_terminal(instruction.pc)
        if (
            instance is None
            or instance.emission_kind != "field-declaration"
            or instance.field_name is None
        ):
            return False
        pending = self._pending_table_for_write(instruction)
        if pending is not None:
            self._flush_pending_table(pending)
        creation = self.instruction_by_pc.get(instance.creation_pc)
        if creation is None:
            return False
        child = self.module.protos[instance.child_proto_id]
        bindings, _dependencies = self._callback_capture_bindings(creation, child)
        context = self.contextual_plan.for_value(instance.closure_value)
        base = self._ref_expr(instruction.b, instruction.pc)
        _FunctionLifter(
            self.module,
            child,
            self.proto_names,
            self.options,
            self.out,
            inline_only_proto_ids=self.inline_only_proto_ids,
            upvalue_bindings=bindings,
            parameter_name_overrides=(
                dict(context.parameter_names) if context is not None else None
            ),
            parameter_type_overrides=(
                dict(context.parameter_types) if context is not None else None
            ),
            return_type_override=context.return_type if context is not None else None,
            module_analysis=self.module_analysis,
            proto_emission_plan=self.proto_emission_plan,
            semantic_function_role="normal",
        ).lift(
            as_function=True,
            field_function_declaration=(base, instance.field_name),
        )
        return True

    def _call_expression(self, instruction: DecodedInstruction) -> Expr:
        frame = self.call_frames.at(instruction.pc)
        if instruction.a in self.pending_namecalls:
            base, method = self.pending_namecalls.pop(instruction.a)
            argument_registers = tuple(
                range(
                    instruction.a + 2,
                    instruction.a + 2 + (max(0, instruction.b - 2) if instruction.b else 0),
                )
            )
            args = tuple(
                self._ref_expr(register, instruction.pc) for register in argument_registers
            )
            return MethodCallExpr(base, method, args)
        function = self._ref_expr(instruction.a, instruction.pc)
        if instruction.b == 0:
            text = f"{render_expression(function)}(... --[[ all arguments through stack top ]])"
            return RawExpr(text, Precedence.POSTFIX)
        argument_registers = (
            frame.argument_registers
            if frame is not None
            else tuple(range(instruction.a + 1, instruction.a + instruction.b))
        )
        args = tuple(self._ref_expr(register, instruction.pc) for register in argument_registers)
        return CallExpr(function, args)

    def _rmw_rhs_expression(
        self,
        instruction: DecodedInstruction,
        candidate: ReadModifyWrite,
    ) -> Expr:
        if candidate.rhs_register is not None:
            return self._ref_expr(candidate.rhs_register, instruction.pc)
        assert candidate.rhs_constant_index is not None
        return source_expr(_constant_expr(self.proto, candidate.rhs_constant_index))

    def _rmw_target_expression(
        self,
        instruction: DecodedInstruction,
        candidate: ReadModifyWrite,
    ) -> Expr:
        location = candidate.location
        if location.kind == StorageKind.LOCAL:
            return NameExpr(self._definition_name(instruction.a, instruction.pc))
        if location.kind == StorageKind.GLOBAL:
            return RawExpr(self._global_key(instruction), Precedence.POSTFIX)
        if location.kind == StorageKind.UPVALUE:
            binding = self.upvalue_bindings.get(instruction.b)
            if binding is not None:
                return binding
            upvalue = (
                self.proto.upvalue_names[instruction.b]
                if instruction.b < len(self.proto.upvalue_names)
                else None
            )
            return NameExpr(_sanitize_identifier(upvalue, f"upvalue_{instruction.b}"))
        base = self._ref_expr(instruction.b, instruction.pc)
        if location.kind == StorageKind.FIELD:
            return FieldExpr(base, self._table_key(instruction))
        if instruction.name == "SETTABLEN":
            return IndexExpr(base, LiteralExpr(str(instruction.c + 1)))
        return IndexExpr(base, self._ref_expr(instruction.c, instruction.pc))

    def _emit_rmw(
        self,
        instruction: DecodedInstruction,
        candidate: ReadModifyWrite,
        rhs: Expr,
    ) -> None:
        target = self._rmw_target_expression(instruction, candidate)
        self.out.line(
            render_statement(CompoundAssignment(target, candidate.operator, rhs)),
            statement=True,
        )
        if candidate.location.kind == StorageKind.LOCAL:
            name = render_expression(target)
            self.register_names[instruction.a] = name
            self.declared.add(name)

    def _conditional_expr(self, instruction: DecodedInstruction) -> Expr | None:
        name = instruction.name
        if name == "JUMPIF":
            return UnaryExpr("not", self._ref_expr(instruction.a, instruction.pc))
        if name == "JUMPIFNOT":
            return self._ref_expr(instruction.a, instruction.pc)
        if name in _COMPARISON_FALLTHROUGH:
            rhs_register = (instruction.aux or 0) & 0xFF
            return BinaryExpr(
                self._ref_expr(instruction.a, instruction.pc),
                _COMPARISON_FALLTHROUGH[name],
                self._ref_expr(rhs_register, instruction.pc),
            )
        if name.startswith("JUMPXEQK"):
            rhs: Expr
            if name == "JUMPXEQKNIL":
                rhs = LiteralExpr("nil")
            elif name == "JUMPXEQKB":
                rhs = LiteralExpr("true" if (instruction.aux or 0) & 1 else "false")
            else:
                rhs = source_expr(
                    _constant_expr(
                        self.proto,
                        (instruction.aux or 0) & 0xFFFFFF,
                    )
                )
            fallthrough_operator = "==" if instruction.aux_not else "~="
            return BinaryExpr(
                self._ref_expr(instruction.a, instruction.pc),
                fallthrough_operator,
                rhs,
            )
        return None

    def _conditional_body(self, instruction: DecodedInstruction) -> str | None:
        expression = self._conditional_expr(instruction)
        return render_expression(expression) if expression is not None else None

    def _boolean_chain_expression(
        self,
        condition_pcs: tuple[int, ...],
        operator: str,
    ) -> Expr | None:
        expressions: list[Expr] = []
        for condition_pc in condition_pcs:
            instruction = self.instruction_by_pc.get(condition_pc)
            if instruction is None:
                return None
            expression = self._conditional_expr(instruction)
            if expression is None:
                return None
            expressions.append(expression)
        if not expressions:
            return None
        combined = expressions[0]
        for expression in expressions[1:]:
            combined = BinaryExpr(combined, operator, expression)
        return combined

    def _handle_loop_prep(self, instruction: DecodedInstruction) -> bool:
        if instruction.name == "FORNPREP":
            target = _jump_target(instruction)
            variable = self._name(instruction.a + 3, instruction.pc)
            self.declared.add(variable)
            start = self._ref(instruction.a + 2, instruction.pc)
            limit = self._ref(instruction.a, instruction.pc)
            step = self._ref(instruction.a + 1, instruction.pc)
            header = f"for {variable} = {start}, {limit}"
            if self.options.preserve_for_step or step not in ("1", "1.0"):
                header += f", {step}"
            header += " do"
            return self._open_until(target, header)

        generic_prep = {"FORGPREP", "FORGPREP_INEXT", "FORGPREP_NEXT"}
        if instruction.name in generic_prep:
            loop_pc = _jump_target(instruction)
            loop_instruction = self.instruction_by_pc.get(loop_pc)
            variable_count = 2
            close_pc = loop_pc + 1
            if loop_instruction and loop_instruction.name == "FORGLOOP":
                variable_count = max(1, (loop_instruction.aux or 1) & 0xFF)
                close_pc = loop_pc + loop_instruction.size
            variables = [
                self._name(instruction.a + 3 + index, instruction.pc)
                for index in range(variable_count)
            ]
            self.declared.update(variables)
            iterator_operands = self._generic_iterator_operands(instruction)
            return self._open_until(
                close_pc,
                f"for {', '.join(variables)} in "
                f"{', '.join(render_expression(item) for item in iterator_operands)} do",
            )
        return False

    def _open_structured_loop(self, instruction: DecodedInstruction) -> bool:
        advanced = self.active_advanced_loops.get(instruction.pc)
        if advanced is not None:
            if advanced.kind == "repeat":
                self.out.open("repeat")
                return True
            if advanced.kind == "infinite":
                self.out.open("while true do")
                self.block_closures[advanced.close_pc].append("end")
                return True
            condition_instruction = (
                self.instruction_by_pc.get(advanced.condition_pc)
                if advanced.condition_pc is not None
                else None
            )
            condition = (
                self._conditional_body(condition_instruction)
                if condition_instruction is not None
                else None
            )
            if condition is None:
                return False
            self.out.open(f"while {condition} do")
            self.block_closures[advanced.close_pc].append("end")
            return True

        if instruction.pc in self.repeat_starts:
            self.out.open("repeat")
        if instruction.pc not in self.while_headers:
            return False
        end_pc, condition_instruction = self.while_headers[instruction.pc]
        condition = self._conditional_body(condition_instruction)
        if condition is None:
            return False
        self.out.open(f"while {condition} do")
        self.block_closures[end_pc].append("end")
        return True

    def _emit_loop_action(
        self,
        instruction: DecodedInstruction,
        action: LoopJumpAction,
    ) -> None:
        if action.edge == "always":
            self.out.line(action.kind, statement=True)
            return
        condition = self._conditional_expr(instruction)
        if condition is None:
            self.out.line(f"-- unresolved {action.kind} edge to L{action.target:04d}")
            return
        if action.edge == "taken":
            condition = UnaryExpr("not", condition)
        self.out.open(f"if {render_expression(condition)} then")
        self.out.line(action.kind, statement=True)
        self.out.close()

    def _emit_state_machine(self, region: StateMachineRegion) -> None:
        self.out.line(
            f"-- unflattened state machine R{region.state_register}; "
            f"initial={region.initial_state!r}"
        )
        if region.kind == "cycle":
            self.out.open("while true do")
        for case in region.cases:
            for pc in case.body_pcs:
                instruction = self.instruction_by_pc.get(pc)
                if instruction is None:
                    continue
                self._flush_tables_before(instruction)
                if instruction.pc in self.callback_plan.capture_pcs:
                    continue
                if instruction.pc in self.class_plan.skipped_instruction_pcs:
                    continue
                self._lift_instruction(instruction)
        if region.kind == "cycle":
            self.out.close()

    def lift(
        self,
        *,
        as_function: bool,
        function_name_override: str | None = None,
        local_function: bool = True,
        anonymous_function: bool = False,
        method_declaration: tuple[Expr, str] | None = None,
        field_function_declaration: tuple[Expr, str] | None = None,
    ) -> None:
        parameters = []
        for register in range(self.proto.num_params):
            if method_declaration is not None and register == 0:
                self.register_names[register] = "self"
                self.declared.add("self")
                continue
            recovered_name = (
                self.symbols.entry_names.get(register)
                if self.options.smart_variable_names and self.symbols is not None
                else None
            )
            contextual_name = self.parameter_name_overrides.get(register)
            name = (
                _local_name(self.proto, register, 0)
                or self.semantic_names.entry_names.get(register)
                or contextual_name
                or recovered_name
                or f"arg{register + 1}"
            )
            name = _sanitize_identifier(name, f"arg{register + 1}")
            name = self._lexically_safe_local_name(register, 0, name)
            parameters.append(self._annotated_name(register, name, 0))
            self.register_names[register] = name
            self.declared.add(name)
        if self.proto.is_vararg:
            parameters.append("...")

        if as_function:
            if method_declaration is not None:
                receiver, method_name = method_declaration
                header = (
                    f"function {render_expression(receiver)}:"
                    f"{_sanitize_identifier(method_name, 'method')}"
                    f"({', '.join(parameters)})"
                )
            elif field_function_declaration is not None:
                receiver, field_name = field_function_declaration
                header = (
                    f"function {render_expression(receiver)}."
                    f"{_sanitize_identifier(field_name, 'field')}"
                    f"({', '.join(parameters)})"
                )
            elif anonymous_function:
                header = f"function({', '.join(parameters)})"
            else:
                function_name = function_name_override or self.proto_names[self.proto.proto_id]
                prefix = "local function" if local_function else "function"
                header = f"{prefix} {function_name}({', '.join(parameters)})"
            if self.options.infer_types:
                return_type = self.return_type_override
                if return_type is None and self.symbols is not None and self.symbols.return_type:
                    return_type = self.symbols.return_type
                return_type = _source_type(return_type)
                if return_type and return_type != "any":
                    header += f": {return_type}"
            self.out.open(header)
        if self.options.show_function_id:
            self.out.line(f"-- function id: {self.proto.proto_id}")
        if self.options.show_line_defined:
            self.out.line(f"-- line defined: {self.proto.line_defined}")
        if self.proto.flag_names:
            self.out.line("-- proto flags: " + ", ".join(self.proto.flag_names))
        if self.proto.cost is not None:
            self.out.line(f"-- inlining cost: {self.proto.cost}")
        if self.options.show_recovered_symbols and self.symbols is not None:
            report = self.symbols.report_lines()
            if report:
                self.out.line("-- recovered symbols:")
                for line in report:
                    self.out.line("--   " + line)
        if self.options.upvalue_comment and self.proto.num_upvalues:
            names = [
                (
                    render_expression(self.upvalue_bindings[index])
                    if index in self.upvalue_bindings
                    else name or f"upvalue_{index}"
                )
                for index, name in enumerate(self.proto.upvalue_names)
            ]
            if len(names) < self.proto.num_upvalues:
                names.extend(
                    f"upvalue_{index}" for index in range(len(names), self.proto.num_upvalues)
                )
            typed = []
            for index, name in enumerate(names):
                if index < len(self.proto.upvalue_types):
                    type_name = format_type_tag(
                        self.proto.upvalue_types[index],
                        self.module.userdata_type_map,
                    )
                    typed.append(f"{name}: {type_name}")
                else:
                    typed.append(name)
            self.out.line("-- upvalues: " + ", ".join(typed))

        rejected_decision_regions: list[DecisionPhiRegion] = []
        for decision_region in self.active_decision_phi_regions.values():
            expression = self._decision_phi_expression(decision_region)
            if expression is None:
                rejected_decision_regions.append(decision_region)
            else:
                self.inline_expressions[decision_region.phi.result] = expression
        for decision_region in rejected_decision_regions:
            self.active_decision_phi_regions.pop(decision_region.root_block, None)
            self.active_structuring_skip_pcs.difference_update(decision_region.skipped_pcs)

        rejected_value_regions = [
            region
            for region in self.active_value_short_circuits.values()
            if not self._capture_value_short_circuit(region)
        ]
        for value_region in rejected_value_regions:
            self.active_value_short_circuits.pop(value_region.root_pc, None)
            self.active_structuring_skip_pcs.difference_update(value_region.skipped_pcs)

        for instruction in self.instructions:
            self._finalize_phi_regions(instruction.pc)
            self._flush_tables_before(instruction)
            if instruction.pc in self.callback_plan.capture_pcs or (
                self.parent_proto_plan is not None
                and instruction.pc in self.parent_proto_plan.skipped_pcs
            ):
                continue
            self._close_blocks(instruction.pc)
            state_machine = self.state_machine_plan.at(instruction.pc)
            if state_machine is not None:
                self._emit_state_machine(state_machine)
                continue
            if instruction.pc in self.state_machine_plan.skipped_pcs:
                continue
            opened_loop = self._open_structured_loop(instruction)
            if instruction.pc in self.labels:
                self.out.line(f"-- L{instruction.pc:04d}")

            if instruction.pc in self.class_plan.skipped_instruction_pcs:
                continue
            if instruction.pc in self.active_loop_actions:
                self._lift_instruction(instruction)
                continue
            if (
                instruction.pc in self.active_structuring_skip_pcs
                and instruction.pc not in self.phi_definition_pcs
            ):
                continue
            advanced_repeat = self.active_advanced_repeat_conditions.get(instruction.pc)
            if advanced_repeat is not None:
                condition = self._conditional_body(instruction)
                self.out.close(f"until {condition or 'false'}")
                continue
            if instruction.pc in self.repeat_conditions:
                condition = self._conditional_body(instruction)
                self.out.close(f"until {condition or 'false'}")
                continue
            if instruction.pc in self.active_loop_skip_pcs:
                continue
            if instruction.pc in self.while_back_pcs:
                continue
            if instruction.pc in self.skip_jump_pcs:
                continue
            if opened_loop:
                continue
            self._lift_instruction(instruction)

        self._finalize_phi_regions(len(self.proto.code))
        self._flush_pending_tables()
        self._close_blocks(len(self.proto.code))
        for target in sorted(self.block_closures):
            self._close_blocks(target)
        if as_function:
            self.out.close()
            if not anonymous_function:
                self.out.line()

    def _emit_recovered_class(self, instruction: DecodedInstruction) -> bool:
        declaration = self.class_plan.at(instruction.pc)
        if declaration is None:
            return False
        class_name = _sanitize_identifier(declaration.name, "AnonymousClass")
        self.register_names[instruction.a] = class_name
        self.declared.add(class_name)
        self.out.line(f"local {class_name} = {{}}", statement=True)
        if declaration.source_kind == "metatable":
            self.out.line(f"{class_name}.__index = {class_name}", statement=True)
        if declaration.superclass_register is not None:
            superclass = self._ref(declaration.superclass_register, instruction.pc)
            self.out.line(
                f"setmetatable({class_name}, {{__index = {superclass}}})",
                statement=True,
            )
        elif declaration.superclass_name is not None:
            self.out.line(
                f"setmetatable({class_name}, {{__index = "
                f"{declaration.superclass_name}}})",
                statement=True,
            )
        if declaration.methods:
            self.out.line()
        for method in declaration.methods:
            method_name = _sanitize_identifier(method.name, "method")
            if method.proto_id is None:
                self.out.line(f"-- unresolved method {method_name}")
                continue
            child = self.module.protos[method.proto_id]
            instance = (
                self.parent_proto_plan.at_creation(method.closure_pc)
                if self.parent_proto_plan is not None and method.closure_pc is not None
                else None
            )
            creation = self.instruction_by_pc.get(method.closure_pc or -1)
            capture_overrides: dict[int, Expr] = {}
            if creation is not None:
                capture_overrides, _dependencies = self._callback_capture_bindings(
                    creation,
                    child,
                )
            if instance is not None:
                capture_overrides.update(self._planned_capture_overrides(instance))
            child_lifter = _FunctionLifter(
                self.module,
                child,
                self.proto_names,
                self.options,
                self.out,
                inline_only_proto_ids=self.inline_only_proto_ids,
                upvalue_bindings=capture_overrides,
                parameter_name_overrides=dict(method.parameter_names),
                parameter_type_overrides=dict(method.parameter_types),
                return_type_override=method.return_type,
                module_analysis=self.module_analysis,
                proto_emission_plan=self.proto_emission_plan,
                semantic_function_role=(
                    "method" if method.kind == "instance_method" else "normal"
                ),
            )
            if method.kind == "instance_method":
                child_lifter.lift(
                    as_function=True,
                    method_declaration=(NameExpr(class_name), method_name),
                )
            else:
                child_lifter.lift(
                    as_function=True,
                    field_function_declaration=(NameExpr(class_name), method_name),
                )
        return True

    def _lift_instruction(self, instruction: DecodedInstruction) -> None:
        name = instruction.name
        pc = instruction.pc
        expression: Expr | str
        loop_action = self.active_loop_actions.get(pc)
        if loop_action is not None:
            self._emit_loop_action(instruction, loop_action)
            return
        if name in {"NEWCLOSURE", "DUPCLOSURE"} and self._emit_planned_closure(
            instruction
        ):
            return
        if name in {"SETTABLEKS", "SETUDATAKS"} and self._emit_planned_method(
            instruction
        ):
            return
        if name in {"SETTABLEKS", "SETUDATAKS"} and self._emit_planned_field_function(
            instruction
        ):
            return
        if (
            name in {"NEWTABLE", "DUPTABLE"}
            and self.options.recover_classes
            and self._emit_recovered_class(instruction)
        ):
            return
        if (
            self.options.reconstruct_table_literals
            and is_table_write(instruction)
            and self._record_table_write(instruction)
        ):
            return
        rmw = self.rmw_plan.at_operation(pc)
        if rmw is not None:
            rhs = self._rmw_rhs_expression(instruction, rmw)
            if rmw.write_pc == pc:
                self._emit_rmw(instruction, rmw, rhs)
            else:
                self.pending_rmw_rhs[rmw.write_pc] = rhs
            return
        rmw = self.rmw_plan.at_write(pc)
        if rmw is not None:
            pending_rhs = self.pending_rmw_rhs.get(pc)
            if pending_rhs is not None:
                self.pending_rmw_rhs.pop(pc)
                self._emit_rmw(instruction, rmw, pending_rhs)
                return
        if name in {"NOP", "BREAK", "COVERAGE", "NATIVECALL", "PREPVARARGS"}:
            return
        if name == "LOADNIL":
            self._assign(instruction.a, "nil", pc)
        elif name == "LOADB":
            self._assign(instruction.a, "true" if instruction.b else "false", pc)
            if instruction.c:
                self.out.line(f"-- LOADB skips to L{_jump_target(instruction):04d}")
        elif name == "LOADN":
            self._assign(instruction.a, str(instruction.d), pc)
        elif name == "LOADK":
            self._assign(instruction.a, _constant_expr(self.proto, instruction.d), pc)
        elif name == "LOADKX":
            index = instruction.aux if instruction.aux is not None else 0
            self._assign(instruction.a, _constant_expr(self.proto, index), pc)
        elif name == "MOVE":
            if self._transfer_inline_callback(instruction):
                return
            if self.options.reconstruct_table_literals and self._transfer_pending_table(
                instruction
            ):
                return
            self._assign(instruction.a, self._ref_expr(instruction.b, pc), pc)
        elif name == "GETGLOBAL":
            self._assign(
                instruction.a,
                RawExpr(self._global_key(instruction), Precedence.POSTFIX),
                pc,
            )
        elif name == "SETGLOBAL":
            self.out.line(
                f"{self._global_key(instruction)} = {self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name == "GETIMPORT":
            self._assign(
                instruction.a,
                RawExpr(
                    _decode_import(self.proto, instruction.aux),
                    Precedence.POSTFIX,
                ),
                pc,
            )
        elif name == "GETUPVAL":
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
                    NameExpr(_sanitize_identifier(upvalue, f"upvalue_{instruction.b}")),
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
        elif name == "GETTABLE":
            expression = IndexExpr(
                self._ref_expr(instruction.b, pc),
                self._ref_expr(instruction.c, pc),
            )
            self._assign(instruction.a, expression, pc)
        elif name == "SETTABLE":
            self.out.line(
                f"{self._ref(instruction.b, pc)}"
                f"[{self._ref(instruction.c, pc)}] = "
                f"{self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name in {"GETTABLEKS", "GETUDATAKS"}:
            expression = FieldExpr(
                self._ref_expr(instruction.b, pc),
                self._table_key(instruction),
            )
            self._assign(instruction.a, expression, pc)
        elif name in {"SETTABLEKS", "SETUDATAKS"}:
            value = self._ref_expr(instruction.a, pc)
            self.out.line(
                f"{_field(self._ref(instruction.b, pc), self._table_key(instruction))} "
                f"= {render_expression(value, pretty_tables=True)}",
                statement=True,
            )
        elif name == "GETTABLEN":
            self._assign(
                instruction.a,
                IndexExpr(
                    self._ref_expr(instruction.b, pc),
                    LiteralExpr(str(instruction.c + 1)),
                ),
                pc,
            )
        elif name == "SETTABLEN":
            self.out.line(
                f"{self._ref(instruction.b, pc)}[{instruction.c + 1}] "
                f"= {self._ref(instruction.a, pc)}",
                statement=True,
            )
        elif name in _BINARY_OPS:
            expression = BinaryExpr(
                self._ref_expr(instruction.b, pc),
                _BINARY_OPS[name],
                self._ref_expr(instruction.c, pc),
            )
            self._assign(instruction.a, expression, pc)
        elif name in _BINARY_CONST_OPS:
            expression = BinaryExpr(
                self._ref_expr(instruction.b, pc),
                _BINARY_CONST_OPS[name],
                source_expr(_constant_expr(self.proto, instruction.c)),
            )
            self._assign(instruction.a, expression, pc)
        elif name in {"SUBRK", "DIVRK"}:
            operator = "-" if name == "SUBRK" else "/"
            expression = BinaryExpr(
                source_expr(_constant_expr(self.proto, instruction.b)),
                operator,
                self._ref_expr(instruction.c, pc),
            )
            self._assign(instruction.a, expression, pc)
        elif name in _UNARY_OPS:
            self._assign(
                instruction.a,
                UnaryExpr(
                    _UNARY_OPS[name].strip(),
                    self._ref_expr(instruction.b, pc),
                ),
                pc,
            )
        elif name == "CONCAT":
            expression = self._ref_expr(instruction.c, pc)
            for register in reversed(range(instruction.b, instruction.c)):
                expression = BinaryExpr(
                    self._ref_expr(register, pc),
                    "..",
                    expression,
                )
            self._assign(instruction.a, expression, pc)
        elif name in {"NEWTABLE", "DUPTABLE"}:
            if (
                self.options.reconstruct_table_literals
                and self._start_pending_table(instruction) is not None
            ):
                return
            if name == "DUPTABLE":
                self._assign(
                    instruction.a,
                    _constant_expr(self.proto, instruction.d),
                    pc,
                )
            else:
                self._assign(instruction.a, TableExpr(), pc)
        elif name == "SETLIST":
            semantics = setlist_semantics(instruction)
            if semantics is None:
                return
            if semantics.is_open:
                self.out.line(
                    f"-- set all stack values from "
                    f"{self._ref(semantics.first_value_register, pc)} "
                    f"into {self._ref(semantics.table_register, pc)} starting at "
                    f"{semantics.semantic_first_array_index}"
                )
            else:
                start_offset = semantics.legacy_emission_offset
                count = semantics.fixed_value_count or 0
                for offset in range(count):
                    self.out.line(
                        f"{self._ref(semantics.table_register, pc)}"
                        f"[{start_offset + offset + 1}] = "
                        f"{self._ref(semantics.first_value_register + offset, pc)}",
                        statement=True,
                    )
        elif name in {"NEWCLOSURE", "DUPCLOSURE"}:
            child_id = closure_proto_id(self.proto, instruction)
            closure_value = self.ssa.value_defined_at(pc, instruction.a)
            if (
                child_id is not None
                and closure_value is not None
                and closure_value in self.callback_plan.proto_by_value
            ):
                expression, dependencies = self._anonymous_function_expr(
                    child_id,
                    instruction,
                )
                self.callback_expressions[closure_value] = expression
                self.callback_dependencies[closure_value] = dependencies
                self.register_names.setdefault(instruction.a, f"v{instruction.a}")
                return
            expression = (
                self.proto_names.get(child_id, f"proto_{child_id}")
                if child_id is not None
                else "function() end"
            )
            self._assign(instruction.a, expression, pc)
        elif name in {"NAMECALL", "NAMECALLUDATA"}:
            base = self._ref_expr(instruction.b, pc)
            self.pending_namecalls[instruction.a] = (
                base,
                self._table_key(instruction),
            )
            self.register_names[instruction.a + 1] = render_expression(base)
        elif name in {"CALL", "CALLFB"}:
            if name == "CALLFB":
                slot = "sealed" if instruction.aux == 0xFFFFFFFF else str(instruction.aux)
                self.out.line(f"-- call feedback slot: {slot}")
            expression = self._call_expression(instruction)
            fastcall_result = self.call_frames.fastcall_result_at(pc)
            if (
                fastcall_result is not None
                and self.options.inline_single_use_temporaries
                and self.ssa.uses_of(fastcall_result) == 1
            ):
                self.inline_expressions[fastcall_result] = expression
                self.register_names.setdefault(instruction.a, f"v{instruction.a}")
                return
            if self.options.reconstruct_table_literals and self._capture_owned_table_call(
                instruction,
                expression,
            ):
                return
            if instruction.c == 1:
                self.out.line(render_expression(expression), statement=True)
            elif instruction.c == 0:
                if self.options.reconstruct_table_literals and self._capture_open_table_value(
                    instruction, expression
                ):
                    return
                self._assign(
                    instruction.a,
                    RawExpr(render_expression(expression) + " --[[ multiple returns ]]"),
                    pc,
                )
            else:
                registers = list(range(instruction.a, instruction.a + instruction.c - 1))
                self._assign_many(registers, expression, pc)
        elif name == "RETURN":
            if instruction.b == 1:
                self.out.line("return", statement=True)
            elif instruction.b == 0:
                self.out.line(
                    f"return {self._ref(instruction.a, pc)} "
                    "--[[ multiple returns through stack top ]]",
                    statement=True,
                )
            else:
                values = [
                    self._ref(instruction.a + index, pc) for index in range(instruction.b - 1)
                ]
                self.out.line("return " + ", ".join(values), statement=True)
        elif name == "GETVARARGS":
            if (
                instruction.b == 0
                and self.options.reconstruct_table_literals
                and self._capture_open_table_value(instruction, source_expr("..."))
            ):
                return
            if instruction.b <= 2:
                self._assign(instruction.a, "...", pc)
            else:
                registers = list(range(instruction.a, instruction.a + instruction.b - 1))
                self._assign_many(registers, "...", pc)
        elif name == "CAPTURE":
            if self.options.upvalue_comment:
                capture_kind = _CAPTURE_NAMES.get(
                    instruction.a,
                    f"type {instruction.a}",
                )
                source = (
                    f"upvalue_{instruction.b}"
                    if instruction.a == 2
                    else self._ref(instruction.b, pc)
                )
                self.out.line(f"-- capture {capture_kind}: {source}")
        elif self._handle_loop_prep(instruction):
            return
        elif name in {"FORNLOOP", "FORGLOOP"}:
            return
        elif name in _CONDITIONAL_OPS:
            guarded_phi = self.active_guarded_phi_regions.get(pc)
            if guarded_phi is not None:
                self._emit_guarded_phi_initializers(guarded_phi)
            target = _jump_target(instruction)
            condition_expression = self._conditional_expr(instruction)
            condition = (
                render_expression(condition_expression)
                if condition_expression is not None
                else None
            )
            phi_region = self.active_phi_headers.get(pc)
            if phi_region is not None:
                if phi_region.condition_operator is not None:
                    condition_expression = self._boolean_chain_expression(
                        phi_region.condition_pcs,
                        phi_region.condition_operator,
                    )
                if condition_expression is not None:
                    self.phi_conditions[pc] = condition_expression
                    return
            chain = self.active_boolean_chains.get(pc)
            if chain is not None:
                combined = self._boolean_chain_expression(
                    chain.condition_pcs,
                    chain.operator,
                )
                if combined is not None:
                    self.out.open(f"if {render_expression(combined)} then")
                    if chain.has_else:
                        self.else_transitions[chain.false_start] = chain.join
                    else:
                        self.block_closures[chain.join].append("end")
                    return
            region = self.if_else_regions.get(pc)
            if condition is None or target <= pc:
                self.out.line(f"-- {name} to L{target:04d}")
            elif region is not None:
                self.out.open(f"if {condition} then")
                self.else_transitions[region.else_pc] = region.end_pc
            elif not self._open_until(target, f"if {condition} then"):
                self.out.line(f"-- if {condition}, continue at L{target:04d}")
        elif name in {"JUMP", "JUMPBACK", "JUMPX"}:
            target = _jump_target(instruction)
            self.out.line(f"-- {name.lower()} to L{target:04d}")
        elif name == "CMPPROTO":
            target = _jump_target(instruction)
            proto_id = instruction.aux if instruction.aux is not None else -1
            proto_name = self.proto_names.get(proto_id, f"proto_{proto_id}")
            self.out.line(
                f"-- if {self._ref(instruction.a, pc)} is not {proto_name}, "
                f"continue at L{target:04d}"
            )
        elif name.startswith("FASTCALL"):
            target = _jump_target(instruction)
            friendly = builtin_name(instruction.a) or f"builtin_{instruction.a}"
            self.out.line(f"-- optimized call {friendly}; fallback continues at L{target:04d}")
        elif name == "NEWCLASS":
            if self.options.recover_classes and self._emit_recovered_class(instruction):
                return
            constant = _constant(self.proto, instruction.aux or 0)
            class_name = "AnonymousClass"
            if (
                constant
                and constant.kind == "class_shape"
                and isinstance(constant.value, ClassShapeConstant)
            ):
                class_name, _, _ = _class_shape_names(self.proto, constant.value)
            superclass = "nil" if instruction.b == 0xFF else self._ref(instruction.b, pc)
            self._assign(
                instruction.a,
                f"{{}} --[[ class {class_name}; superclass={superclass} ]]",
                pc,
            )
        elif name == "NEWCLASSMEMBER":
            key = self._table_key(instruction)
            self.out.line(
                f"{_field(self._ref(instruction.a, pc), key)} = {self._ref(instruction.c, pc)}",
                statement=True,
            )
        elif name == "CLOSEUPVALS":
            self.out.line(f"-- close upvalues from register {instruction.a}")
        else:
            self.out.line(f"-- unsupported {instruction.render()}")


def decompile_module(
    module: LuauBytecodeModule,
    options: dict[str, bool],
    filename: str | None,
) -> str:
    resolved = _Options.from_backend(options)
    module_analysis = build_module_analysis(module)
    out = _Emitter(resolved.semicolons)
    label = filename or "<bytecode>"
    out.line(f"-- LunaUX Next reconstructed output for {label}")
    out.line(
        "-- Reconstruction is semantic and conservative; comments, formatting, "
        "and optimized source choices are not stored in bytecode."
    )
    out.line(
        f"-- Luau bytecode v{module.version}, type info v{module.types_version}, "
        f"{len(module.protos)} prototype(s)"
    )
    if module.userdata_types:
        mapping = ", ".join(f"{index}={name}" for index, name in module.userdata_types)
        out.line("-- userdata types: " + mapping)
    if module.trailing_bytes:
        out.line(f"-- Warning: {module.trailing_bytes} trailing byte(s) were not parsed")
    out.line()

    names = _proto_names(module)
    legacy_inline_only_proto_ids = collect_inline_only_proto_ids(
        module,
        enabled=resolved.inline_roblox_callbacks,
        module_analysis=module_analysis,
    )
    class_method_proto_ids = (
        collect_class_method_proto_ids(
            module,
            recover_metatable_classes=resolved.recover_metatable_classes,
            module_analysis=module_analysis,
        )
        if resolved.recover_classes
        else frozenset()
    )
    contextual_contexts = collect_module_function_contexts(
        module,
        recover_metatable_classes=resolved.recover_metatable_classes,
        enabled=resolved.contextual_functions,
        module_analysis=module_analysis,
    )
    proto_emission_plan = build_proto_emission_plan(
        module,
        module_analysis,
        contextual_contexts,
        inline_callbacks=resolved.inline_roblox_callbacks,
    )
    inline_only_proto_ids = (
        legacy_inline_only_proto_ids | proto_emission_plan.owned_proto_ids
    )
    main_analysis = module_analysis.for_proto(module.main_proto)
    roblox_report = analyze_roblox_recovery(
        module,
        module.main_proto,
        main_analysis.instructions,
        main_analysis.ssa,
    )
    if resolved.recover_roblox_events and roblox_report.events:
        out.line("-- Roblox events: " + ", ".join(item.display for item in roblox_report.events))
    if resolved.recover_roblox_modules:
        if roblox_report.dependencies:
            out.line(
                "-- Roblox module dependencies: "
                + ", ".join(item.path for item in roblox_report.dependencies)
            )
        if roblox_report.export_kind is not None:
            out.line("-- Roblox ModuleScript export: " + roblox_report.export_kind)
    if (resolved.recover_roblox_events and roblox_report.events) or (
        resolved.recover_roblox_modules
        and (roblox_report.dependencies or roblox_report.export_kind is not None)
    ):
        out.line()

    for proto in module.protos:
        if (
            proto.proto_id == module.main_proto_id
            or proto.proto_id not in proto_emission_plan.preemit_proto_ids
            or proto.proto_id in legacy_inline_only_proto_ids
            or proto.proto_id in class_method_proto_ids
        ):
            continue
        context = contextual_contexts.get(proto.proto_id)
        _FunctionLifter(
            module,
            proto,
            names,
            resolved,
            out,
            inline_only_proto_ids=inline_only_proto_ids,
            parameter_name_overrides=(
                dict(context.parameter_names) if context is not None else None
            ),
            parameter_type_overrides=(
                dict(context.parameter_types) if context is not None else None
            ),
            return_type_override=context.return_type if context is not None else None,
            module_analysis=module_analysis,
            proto_emission_plan=proto_emission_plan,
        ).lift(
            as_function=True,
            function_name_override=(
                _sanitize_identifier(context.name, names[proto.proto_id])
                if context is not None
                else None
            ),
            local_function=context is None or context.kind != "global",
        )

    out.line("-- Main prototype")
    _FunctionLifter(
        module,
        module.main_proto,
        names,
        resolved,
        out,
        inline_only_proto_ids=inline_only_proto_ids,
        module_analysis=module_analysis,
        proto_emission_plan=proto_emission_plan,
    ).lift(as_function=False)
    return out.render()


def _describe_operand(
    module: LuauBytecodeModule,
    proto: LuauProto,
    instruction: DecodedInstruction,
) -> str:
    name = instruction.name
    descriptions: list[str] = []
    if name in {"LOADK", "DUPTABLE", "DUPCLOSURE"}:
        descriptions.append(_constant_description(proto, instruction.d))
    elif name == "LOADKX":
        index = instruction.aux if instruction.aux is not None else 0
        descriptions.append(_constant_description(proto, index))
    elif name in {
        "GETGLOBAL",
        "SETGLOBAL",
        "GETTABLEKS",
        "SETTABLEKS",
        "NAMECALL",
        "NEWCLASSMEMBER",
    }:
        index = instruction.aux if instruction.aux is not None else -1
        descriptions.append(f"key={_quote(_constant_string(proto, index) or '?')}")
    elif name in {"GETUDATAKS", "SETUDATAKS", "NAMECALLUDATA"}:
        index = instruction.userdata_constant_index or 0
        descriptions.append(f"key={_quote(_constant_string(proto, index) or '?')}")
        descriptions.append(f"cached_slot={instruction.userdata_slot}")
    elif name == "GETIMPORT":
        descriptions.append(f"import={_decode_import(proto, instruction.aux)}")
        descriptions.append(_constant_description(proto, instruction.d))
    elif name in _BINARY_CONST_OPS:
        descriptions.append(_constant_description(proto, instruction.c))
    elif name in {"SUBRK", "DIVRK"}:
        descriptions.append(_constant_description(proto, instruction.b))
    elif name == "FASTCALL2K":
        descriptions.append(_constant_description(proto, instruction.aux or 0))
    elif name in {"JUMPXEQKN", "JUMPXEQKS"}:
        descriptions.append(_constant_description(proto, (instruction.aux or 0) & 0xFFFFFF))
        descriptions.append(f"not={instruction.aux_not}")
    elif name == "JUMPXEQKB":
        descriptions.append(f"value={bool((instruction.aux or 0) & 1)}")
        descriptions.append(f"not={instruction.aux_not}")
    elif name == "JUMPXEQKNIL":
        descriptions.append(f"not={instruction.aux_not}")

    target = get_jump_target(instruction)
    if target is not None:
        descriptions.append(f"target=L{target:04d}")

    if name.startswith("FASTCALL"):
        descriptions.append(f"builtin={builtin_name(instruction.a) or f'builtin_{instruction.a}'}")
        if name == "FASTCALL3":
            descriptions.append(f"arg2=R{instruction.aux_a}")
            descriptions.append(f"arg3=R{instruction.aux_b}")
        elif name == "FASTCALL2":
            descriptions.append(f"arg2=R{instruction.aux_a}")
    elif name == "CAPTURE":
        descriptions.append(f"capture={_CAPTURE_NAMES.get(instruction.a, instruction.a)}")
    elif name == "FORGLOOP":
        descriptions.append(f"variables={(instruction.aux or 0) & 0xFF}")
        descriptions.append(f"ipairs={bool((instruction.aux or 0) & 0x80000000)}")
    elif name == "NEWTABLE":
        descriptions.append(f"array_size={instruction.aux or 0}")
        descriptions.append(f"hash_log2={instruction.b}")
    elif name == "SETLIST":
        semantics = setlist_semantics(instruction)
        if semantics is not None:
            descriptions.append(f"start={semantics.semantic_first_array_index}")
            descriptions.append(
                "count=top" if semantics.is_open else f"count={semantics.fixed_value_count}"
            )
    elif name == "CALLFB":
        slot = "sealed" if instruction.aux == 0xFFFFFFFF else instruction.aux
        descriptions.append(f"feedback_slot={slot}")
    elif name == "CMPPROTO":
        proto_id = instruction.aux if instruction.aux is not None else -1
        proto_name = (
            module.protos[proto_id].debug_name if 0 <= proto_id < len(module.protos) else None
        )
        descriptions.append(f"proto={proto_id}:{proto_name or '<anonymous>'}")
    elif name == "NEWCLASS":
        descriptions.append(_constant_description(proto, instruction.aux or 0))
        descriptions.append("super=nil" if instruction.b == 0xFF else f"super=R{instruction.b}")
    elif name == "COVERAGE":
        descriptions.append(f"hits={instruction.e}")

    return " ; " + " ; ".join(descriptions) if descriptions else ""


def _type_info_lines(
    module: LuauBytecodeModule,
    proto: LuauProto,
) -> list[str]:
    lines: list[str] = []
    if proto.function_type_info:
        lines.append(".function_types " + proto.function_type_info.hex())
    if proto.upvalue_types:
        rendered = ", ".join(
            f"U{index}:{format_type_tag(tag, module.userdata_type_map)}"
            for index, tag in enumerate(proto.upvalue_types)
        )
        lines.append(".upvalue_types " + rendered)
    if proto.typed_locals:
        lines.append(".typed_locals")
        for item in proto.typed_locals:
            type_name = format_type_tag(item.type_tag, module.userdata_type_map)
            lines.append(f"  R{item.register:<3} {type_name:<20} pc={item.start_pc}..{item.end_pc}")
    if proto.type_info_trailing:
        lines.append(".type_extension " + proto.type_info_trailing.hex())
    return lines


def disassemble_module(module: LuauBytecodeModule, filename: str | None) -> str:
    lines = [
        f"; LunaUX Next disassembly for {filename or '<bytecode>'}",
        (
            f"; bytecode={module.version} types={module.types_version} "
            f"protos={len(module.protos)} main={module.main_proto_id}"
        ),
    ]
    if module.userdata_types:
        lines.append(
            "; userdata=" + ", ".join(f"{index}:{name}" for index, name in module.userdata_types)
        )
    for proto in module.protos:
        flags = ",".join(proto.flag_names) or "none"
        lines.extend(
            [
                "",
                (
                    f".proto {proto.proto_id} "
                    f"name={proto.debug_name or '<anonymous>'!r} "
                    f"params={proto.num_params} "
                    f"upvalues={proto.num_upvalues} "
                    f"stack={proto.max_stack_size} "
                    f"flags={flags}"
                ),
                f".line {proto.line_defined}",
            ]
        )
        if proto.serialized_size is not None:
            lines.append(f".serialized_size {proto.serialized_size}")
        if proto.cost is not None:
            lines.append(f".cost {proto.cost}")
        lines.extend(_type_info_lines(module, proto))
        if proto.locals:
            lines.append(".locals")
            for item in proto.locals:
                lines.append(
                    f"  R{item.register:<3} {item.name or '<unnamed>'!r} "
                    f"pc={item.start_pc}..{item.end_pc}"
                )
        if proto.feedback_pcs:
            lines.append(".feedback " + ", ".join(str(pc) for pc in proto.feedback_pcs))
        for instruction in proto.instructions:
            line_number = (
                proto.line_info[instruction.pc] if instruction.pc < len(proto.line_info) else None
            )
            prefix = f"{line_number:5d} " if line_number is not None else "      "
            lines.append(
                prefix + instruction.render() + _describe_operand(module, proto, instruction)
            )
        if proto.constants:
            lines.append(".constants")
            for index, constant in enumerate(proto.constants):
                lines.append(
                    f"  K{index:<4} {constant.kind:<22} {_constant_description(proto, index)}"
                )
    return "\n".join(lines).rstrip() + "\n"
