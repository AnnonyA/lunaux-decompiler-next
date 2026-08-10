from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from lunaux.backends.opcodes import DecodedInstruction


class EffectKind(StrEnum):
    LITERAL = "literal"
    REFERENCE = "reference"
    PURE = "pure"
    MUTABLE_READ = "mutable_read"
    CALL = "call"
    MUTATION = "mutation"
    CONTROL = "control"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class InstructionEffect:
    kind: EffectKind
    reads_mutable_state: bool = False
    writes_state: bool = False
    may_call: bool = False
    may_throw: bool = False
    may_invoke_metamethod: bool = False
    changes_control_flow: bool = False

    @property
    def expression_capable(self) -> bool:
        return (
            not self.writes_state
            and not self.changes_control_flow
            and self.kind
            not in {
                EffectKind.UNKNOWN,
                EffectKind.MUTATION,
                EffectKind.CONTROL,
            }
        )

    @property
    def transparent(self) -> bool:
        return self.kind == EffectKind.PURE and not (
            self.reads_mutable_state
            or self.writes_state
            or self.may_call
            or self.may_throw
            or self.may_invoke_metamethod
            or self.changes_control_flow
        )


_LITERALS = frozenset({"LOADNIL", "LOADB", "LOADN", "LOADK", "LOADKX"})
_REFERENCES = frozenset({"MOVE", "GETGLOBAL", "GETIMPORT", "GETUPVAL"})
_TABLE_READS = frozenset({"GETTABLE", "GETTABLEKS", "GETUDATAKS", "GETTABLEN"})
_ARITHMETIC = frozenset(
    {
        "ADD",
        "SUB",
        "MUL",
        "DIV",
        "MOD",
        "POW",
        "IDIV",
        "AND",
        "OR",
        "ADDK",
        "SUBK",
        "MULK",
        "DIVK",
        "MODK",
        "POWK",
        "IDIVK",
        "ANDK",
        "ORK",
        "SUBRK",
        "DIVRK",
        "NOT",
        "MINUS",
        "LENGTH",
        "CONCAT",
    }
)
_ALLOCATIONS = frozenset({"NEWTABLE", "DUPTABLE", "NEWCLOSURE", "DUPCLOSURE"})
_CALLS = frozenset({"CALL", "CALLFB"})
_MUTATIONS = frozenset(
    {
        "SETGLOBAL",
        "SETUPVAL",
        "SETTABLE",
        "SETTABLEKS",
        "SETUDATAKS",
        "SETTABLEN",
        "SETLIST",
        "NEWCLASSMEMBER",
        "CLOSEUPVALS",
    }
)
_CONTROL = frozenset(
    {
        "RETURN",
        "JUMP",
        "JUMPBACK",
        "JUMPIF",
        "JUMPIFNOT",
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "FORNPREP",
        "FORNLOOP",
        "FORGPREP",
        "FORGPREP_INEXT",
        "FORGPREP_NEXT",
        "FORGLOOP",
        "BREAK",
    }
)


def classify_instruction(instruction: DecodedInstruction) -> InstructionEffect:
    name = instruction.name
    if name in _LITERALS:
        return InstructionEffect(EffectKind.LITERAL)
    if name in _REFERENCES:
        return InstructionEffect(
            EffectKind.REFERENCE,
            reads_mutable_state=name == "GETGLOBAL",
        )
    if name in _TABLE_READS:
        return InstructionEffect(
            EffectKind.MUTABLE_READ,
            reads_mutable_state=True,
            may_throw=True,
            may_invoke_metamethod=True,
        )
    if name in _ARITHMETIC:
        return InstructionEffect(
            EffectKind.PURE,
            may_throw=True,
            may_invoke_metamethod=True,
        )
    if name in _ALLOCATIONS:
        return InstructionEffect(EffectKind.PURE)
    if name in _CALLS:
        return InstructionEffect(
            EffectKind.CALL,
            reads_mutable_state=True,
            writes_state=True,
            may_call=True,
            may_throw=True,
        )
    if name in _MUTATIONS:
        return InstructionEffect(
            EffectKind.MUTATION,
            writes_state=True,
            may_call=name.startswith("SETTABLE") or name.startswith("SETUDATA"),
            may_throw=name.startswith("SETTABLE") or name.startswith("SETUDATA"),
            may_invoke_metamethod=name.startswith("SETTABLE") or name.startswith("SETUDATA"),
        )
    if name in _CONTROL or name.startswith("JUMP") or name.endswith("LOOP"):
        return InstructionEffect(EffectKind.CONTROL, changes_control_flow=True)
    if name in {"NOP", "COVERAGE", "PREPVARARGS", "NATIVECALL"}:
        return InstructionEffect(EffectKind.PURE)
    return InstructionEffect(EffectKind.UNKNOWN)


def is_transparent_instruction(instruction: DecodedInstruction) -> bool:
    return instruction.name in {
        "NOP",
        "COVERAGE",
        "LOADNIL",
        "LOADB",
        "LOADN",
        "LOADK",
        "LOADKX",
        "MOVE",
    }


__all__ = [
    "EffectKind",
    "InstructionEffect",
    "classify_instruction",
    "is_transparent_instruction",
]
