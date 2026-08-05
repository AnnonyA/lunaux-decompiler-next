from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable

_OPCODE_NAMES = (
    "NOP", "BREAK", "LOADNIL", "LOADB", "LOADN", "LOADK", "MOVE",
    "GETGLOBAL", "SETGLOBAL", "GETUPVAL", "SETUPVAL", "CLOSEUPVALS",
    "GETIMPORT", "GETTABLE", "SETTABLE", "GETTABLEKS", "SETTABLEKS",
    "GETTABLEN", "SETTABLEN", "NEWCLOSURE", "NAMECALL", "CALL", "RETURN",
    "JUMP", "JUMPBACK", "JUMPIF", "JUMPIFNOT", "JUMPIFEQ", "JUMPIFLE",
    "JUMPIFLT", "JUMPIFNOTEQ", "JUMPIFNOTLE", "JUMPIFNOTLT", "ADD", "SUB",
    "MUL", "DIV", "MOD", "POW", "ADDK", "SUBK", "MULK", "DIVK", "MODK",
    "POWK", "AND", "OR", "ANDK", "ORK", "CONCAT", "NOT", "MINUS", "LENGTH",
    "NEWTABLE", "DUPTABLE", "SETLIST", "FORNPREP", "FORNLOOP", "FORGLOOP",
    "FORGPREP_INEXT", "FASTCALL3", "FORGPREP_NEXT", "NATIVECALL", "GETVARARGS",
    "DUPCLOSURE", "PREPVARARGS", "LOADKX", "JUMPX", "FASTCALL", "COVERAGE",
    "CAPTURE", "SUBRK", "DIVRK", "FASTCALL1", "FASTCALL2", "FASTCALL2K",
    "FORGPREP", "JUMPXEQKNIL", "JUMPXEQKB", "JUMPXEQKN", "JUMPXEQKS", "IDIV",
    "IDIVK", "GETUDATAKS", "SETUDATAKS", "NAMECALLUDATA", "NEWCLASSMEMBER",
    "CALLFB", "CMPPROTO",
)

_AUX_OPS = frozenset(
    {
        "GETGLOBAL", "SETGLOBAL", "GETIMPORT", "GETTABLEKS", "SETTABLEKS",
        "NAMECALL", "JUMPIFEQ", "JUMPIFLE", "JUMPIFLT", "JUMPIFNOTEQ",
        "JUMPIFNOTLE", "JUMPIFNOTLT", "NEWTABLE", "SETLIST", "FORGLOOP",
        "FASTCALL3", "LOADKX", "FASTCALL2", "FASTCALL2K", "JUMPXEQKNIL",
        "JUMPXEQKB", "JUMPXEQKN", "JUMPXEQKS", "GETUDATAKS", "SETUDATAKS",
        "NAMECALLUDATA", "NEWCLASSMEMBER", "CALLFB", "CMPPROTO",
    }
)


@dataclass(frozen=True, slots=True)
class DecodedInstruction:
    pc: int
    word: int
    opcode: int
    name: str
    a: int
    b: int
    c: int
    d: int
    e: int
    aux: int | None = None

    @property
    def size(self) -> int:
        return 2 if self.aux is not None else 1

    def render(self) -> str:
        fields = f"A={self.a:<3} B={self.b:<3} C={self.c:<3} D={self.d:<7} E={self.e:<9}"
        if self.aux is not None:
            fields += f" AUX=0x{self.aux:08x}"
        return f"{self.pc:04d}  0x{self.word:08x}  {self.name:<18} {fields.rstrip()}"


def _sign(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def opcode_name(opcode: int) -> str:
    return _OPCODE_NAMES[opcode] if 0 <= opcode < len(_OPCODE_NAMES) else f"OP_{opcode}"


def decode_word(word: int, pc: int = 0, aux: int | None = None) -> DecodedInstruction:
    opcode = word & 0xFF
    return DecodedInstruction(
        pc=pc,
        word=word,
        opcode=opcode,
        name=opcode_name(opcode),
        a=(word >> 8) & 0xFF,
        b=(word >> 16) & 0xFF,
        c=(word >> 24) & 0xFF,
        d=_sign((word >> 16) & 0xFFFF, 16),
        e=_sign((word >> 8) & 0xFFFFFF, 24),
        aux=aux,
    )


def unpack_words(data: bytes) -> tuple[int, ...]:
    if len(data) % 4:
        raise ValueError("instruction stream size must be divisible by four")
    if not data:
        return ()
    return struct.unpack(f"<{len(data) // 4}I", data)


def decode_words(words: Iterable[int]) -> list[DecodedInstruction]:
    values = tuple(words)
    result: list[DecodedInstruction] = []
    pc = 0
    while pc < len(values):
        word = values[pc]
        name = opcode_name(word & 0xFF)
        aux = values[pc + 1] if name in _AUX_OPS and pc + 1 < len(values) else None
        instruction = decode_word(word, pc, aux)
        result.append(instruction)
        pc += instruction.size
    return result


def disassemble_words(data: bytes) -> str:
    instructions = decode_words(unpack_words(data))
    rendered = "\n".join(instruction.render() for instruction in instructions)
    return rendered + ("\n" if instructions else "")
