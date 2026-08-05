from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from lunaux.backends.bytecode import LuauProto


@dataclass(frozen=True, slots=True)
class Binding:
    name: str
    register: int
    start_pc: int
    end_pc: int
    type_tag: int | None = None

    def active_at(self, pc: int) -> bool:
        return self.start_pc <= pc < self.end_pc


@dataclass(frozen=True, slots=True)
class LexicalScope:
    scope_id: int
    start_pc: int
    end_pc: int
    parent_id: int | None
    child_ids: tuple[int, ...]
    bindings: tuple[Binding, ...]

    def contains(self, pc: int) -> bool:
        return self.start_pc <= pc < self.end_pc


@dataclass(frozen=True, slots=True)
class ScopeTree:
    scopes: Mapping[int, LexicalScope]
    root_id: int

    @property
    def root(self) -> LexicalScope:
        return self.scopes[self.root_id]

    def scope_at(self, pc: int) -> LexicalScope:
        candidates = [scope for scope in self.scopes.values() if scope.contains(pc)]
        if not candidates:
            return self.root
        return min(candidates, key=lambda scope: (scope.end_pc - scope.start_pc, -scope.start_pc))

    def ancestors(self, scope_id: int) -> tuple[LexicalScope, ...]:
        result: list[LexicalScope] = []
        current: int | None = scope_id
        while current is not None:
            scope = self.scopes[current]
            result.append(scope)
            current = scope.parent_id
        return tuple(result)

    def resolve(self, name: str, pc: int) -> Binding | None:
        scope = self.scope_at(pc)
        for candidate_scope in self.ancestors(scope.scope_id):
            active = [
                binding
                for binding in candidate_scope.bindings
                if binding.name == name and binding.active_at(pc)
            ]
            if active:
                return max(active, key=lambda binding: binding.start_pc)
        return None

    def binding_for_register(self, register: int, pc: int) -> Binding | None:
        scope = self.scope_at(pc)
        for candidate_scope in self.ancestors(scope.scope_id):
            active = [
                binding
                for binding in candidate_scope.bindings
                if binding.register == register and binding.active_at(pc)
            ]
            if active:
                return max(active, key=lambda binding: binding.start_pc)
        return None

    def visible_bindings(self, pc: int) -> tuple[Binding, ...]:
        scope = self.scope_at(pc)
        visible: dict[str, Binding] = {}
        for candidate_scope in self.ancestors(scope.scope_id):
            for binding in candidate_scope.bindings:
                if binding.active_at(pc) and binding.name not in visible:
                    visible[binding.name] = binding
        return tuple(sorted(visible.values(), key=lambda item: (item.register, item.name)))


@dataclass(slots=True)
class _ScopeBuilder:
    scope_id: int
    start_pc: int
    end_pc: int
    parent_id: int | None
    child_ids: list[int]
    bindings: list[Binding]


def _typed_local_tags(proto: LuauProto) -> dict[tuple[int, int, int], int]:
    return {
        (local.register, local.start_pc, local.end_pc): local.type_tag
        for local in proto.typed_locals
    }


def build_scope_tree(proto: LuauProto) -> ScopeTree:
    code_end = max(1, len(proto.code))
    intervals = {
        (max(0, local.start_pc), min(code_end, max(local.start_pc + 1, local.end_pc)))
        for local in proto.locals
        if local.name is not None and local.end_pc > local.start_pc
    }
    intervals.discard((0, code_end))
    ordered_intervals = sorted(intervals, key=lambda item: (item[0], -item[1]))

    builders: dict[int, _ScopeBuilder] = {
        0: _ScopeBuilder(
            scope_id=0,
            start_pc=0,
            end_pc=code_end,
            parent_id=None,
            child_ids=[],
            bindings=[],
        )
    }
    interval_to_scope: dict[tuple[int, int], int] = {(0, code_end): 0}

    for start_pc, end_pc in ordered_intervals:
        containing = [
            scope
            for scope in builders.values()
            if scope.start_pc <= start_pc
            and end_pc <= scope.end_pc
            and (scope.start_pc, scope.end_pc) != (start_pc, end_pc)
        ]
        parent = min(
            containing,
            key=lambda scope: (scope.end_pc - scope.start_pc, -scope.start_pc),
            default=builders[0],
        )
        scope_id = len(builders)
        builders[scope_id] = _ScopeBuilder(
            scope_id=scope_id,
            start_pc=start_pc,
            end_pc=end_pc,
            parent_id=parent.scope_id,
            child_ids=[],
            bindings=[],
        )
        parent.child_ids.append(scope_id)
        interval_to_scope[(start_pc, end_pc)] = scope_id

    type_tags = _typed_local_tags(proto)
    for local in proto.locals:
        if local.name is None or local.end_pc <= local.start_pc:
            continue
        start_pc = max(0, local.start_pc)
        end_pc = min(code_end, max(local.start_pc + 1, local.end_pc))
        scope_id = interval_to_scope.get((start_pc, end_pc), 0)
        builders[scope_id].bindings.append(
            Binding(
                name=local.name,
                register=local.register,
                start_pc=start_pc,
                end_pc=end_pc,
                type_tag=type_tags.get((local.register, local.start_pc, local.end_pc)),
            )
        )

    frozen = {
        scope_id: LexicalScope(
            scope_id=builder.scope_id,
            start_pc=builder.start_pc,
            end_pc=builder.end_pc,
            parent_id=builder.parent_id,
            child_ids=tuple(sorted(builder.child_ids)),
            bindings=tuple(
                sorted(
                    builder.bindings,
                    key=lambda binding: (
                        binding.start_pc,
                        binding.register,
                        binding.name,
                    ),
                )
            ),
        )
        for scope_id, builder in sorted(builders.items())
    }
    return ScopeTree(scopes=MappingProxyType(frozen), root_id=0)
