from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from lunaux.backends.analysis import ControlFlowAnalysis, analyze_control_flow
from lunaux.backends.bytecode import LuauBytecodeModule, LuauProto
from lunaux.backends.opcodes import DecodedInstruction, decode_words
from lunaux.backends.scopes import ScopeTree, build_scope_tree
from lunaux.backends.ssa import SSAProgram, build_ssa
from lunaux.backends.symbols import SymbolRecovery, build_symbol_recovery


@dataclass(frozen=True, slots=True)
class SymbolAnalysisConfig:
    enabled: bool
    flow_sensitive_types: bool
    roblox_api_types: bool


@dataclass(frozen=True, slots=True)
class ProtoAnalysis:
    proto: LuauProto
    instructions: tuple[DecodedInstruction, ...]
    control_flow: ControlFlowAnalysis
    ssa: SSAProgram
    scope_tree: ScopeTree


class ModuleAnalysis:
    """Analysis owned by one ``decompile_module`` invocation."""

    __slots__ = ("_module", "_protos", "_symbol_cache")

    def __init__(
        self,
        module: LuauBytecodeModule,
        protos: Mapping[int, ProtoAnalysis],
    ) -> None:
        self._module = module
        self._protos = MappingProxyType(dict(protos))
        self._symbol_cache: dict[
            tuple[int, SymbolAnalysisConfig], SymbolRecovery
        ] = {}

    @property
    def protos(self) -> Mapping[int, ProtoAnalysis]:
        return self._protos

    def require_module(self, module: LuauBytecodeModule) -> None:
        if module != self._module:
            raise ValueError("ModuleAnalysis belongs to a different bytecode module")

    def for_proto(self, proto: LuauProto) -> ProtoAnalysis:
        result = self._protos.get(proto.proto_id)
        if result is None or result.proto != proto:
            raise ValueError(
                f"ModuleAnalysis has no structurally matching proto {proto.proto_id}"
            )
        return result

    def symbols_for(
        self,
        proto: LuauProto,
        config: SymbolAnalysisConfig,
    ) -> SymbolRecovery | None:
        if not config.enabled:
            return None
        analyzed = self.for_proto(proto)
        key = (proto.proto_id, config)
        result = self._symbol_cache.get(key)
        if result is None:
            result = build_symbol_recovery(
                self._module,
                proto,
                analyzed.instructions,
                analyzed.ssa,
                flow_sensitive_types=config.flow_sensitive_types,
                roblox_api_types=config.roblox_api_types,
            )
            self._symbol_cache[key] = result
        return result


def build_module_analysis(module: LuauBytecodeModule) -> ModuleAnalysis:
    protos: dict[int, ProtoAnalysis] = {}
    for proto in module.protos:
        if proto.proto_id in protos:
            raise ValueError(f"duplicate prototype id {proto.proto_id}")
        instructions = tuple(decode_words(proto.code))
        control_flow = analyze_control_flow(instructions, len(proto.code))
        ssa = build_ssa(
            instructions,
            len(proto.code),
            analysis=control_flow,
        )
        protos[proto.proto_id] = ProtoAnalysis(
            proto=proto,
            instructions=instructions,
            control_flow=control_flow,
            ssa=ssa,
            scope_tree=build_scope_tree(proto),
        )
    return ModuleAnalysis(module, protos)
