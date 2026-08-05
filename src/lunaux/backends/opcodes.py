from __future__ import annotations

import struct
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class InstructionEncoding(StrEnum):
    NONE = "none"
    A = "A"
    ABC = "ABC"
    AD = "AD"
    E = "E"


@dataclass(frozen=True, slots=True)
class OpcodeInfo:
    name: str
    encoding: InstructionEncoding
    has_aux: bool
    min_version: int


_OPCODE_NAMES = (
    "NOP",
    "BREAK",
    "LOADNIL",
    "LOADB",
    "LOADN",
    "LOADK",
    "MOVE",
    "GETGLOBAL",
    "SETGLOBAL",
    "GETUPVAL",
    "SETUPVAL",
    "CLOSEUPVALS",
    "GETIMPORT",
    "GETTABLE",
    "SETTABLE",
    "GETTABLEKS",
    "SETTABLEKS",
    "GETTABLEN",
    "SETTABLEN",
    "NEWCLOSURE",
    "NAMECALL",
    "CALL",
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
    "ADD",
    "SUB",
    "MUL",
    "DIV",
    "MOD",
    "POW",
    "ADDK",
    "SUBK",
    "MULK",
    "DIVK",
    "MODK",
    "POWK",
    "AND",
    "OR",
    "ANDK",
    "ORK",
    "CONCAT",
    "NOT",
    "MINUS",
    "LENGTH",
    "NEWTABLE",
    "DUPTABLE",
    "SETLIST",
    "FORNPREP",
    "FORNLOOP",
    "FORGLOOP",
    "FORGPREP_INEXT",
    "FASTCALL3",
    "FORGPREP_NEXT",
    "NATIVECALL",
    "GETVARARGS",
    "DUPCLOSURE",
    "PREPVARARGS",
    "LOADKX",
    "JUMPX",
    "FASTCALL",
    "COVERAGE",
    "CAPTURE",
    "SUBRK",
    "DIVRK",
    "FASTCALL1",
    "FASTCALL2",
    "FASTCALL2K",
    "FORGPREP",
    "JUMPXEQKNIL",
    "JUMPXEQKB",
    "JUMPXEQKN",
    "JUMPXEQKS",
    "IDIV",
    "IDIVK",
    "GETUDATAKS",
    "SETUDATAKS",
    "NAMECALLUDATA",
    "NEWCLASSMEMBER",
    "CALLFB",
    "CMPPROTO",
    "NEWCLASS",
)

_AUX_OPS = frozenset(
    {
        "GETGLOBAL",
        "SETGLOBAL",
        "GETIMPORT",
        "GETTABLEKS",
        "SETTABLEKS",
        "NAMECALL",
        "JUMPIFEQ",
        "JUMPIFLE",
        "JUMPIFLT",
        "JUMPIFNOTEQ",
        "JUMPIFNOTLE",
        "JUMPIFNOTLT",
        "NEWTABLE",
        "SETLIST",
        "FORGLOOP",
        "FASTCALL3",
        "LOADKX",
        "FASTCALL2",
        "FASTCALL2K",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "GETUDATAKS",
        "SETUDATAKS",
        "NAMECALLUDATA",
        "NEWCLASSMEMBER",
        "CALLFB",
        "CMPPROTO",
        "NEWCLASS",
    }
)

_AD_OPS = frozenset(
    {
        "LOADN",
        "LOADK",
        "GETIMPORT",
        "NEWCLOSURE",
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
        "DUPTABLE",
        "FORNPREP",
        "FORNLOOP",
        "FORGLOOP",
        "FORGPREP_INEXT",
        "FORGPREP_NEXT",
        "DUPCLOSURE",
        "FORGPREP",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "CMPPROTO",
    }
)
_E_OPS = frozenset({"JUMPX", "COVERAGE"})
_A_OPS = frozenset({"LOADNIL", "CLOSEUPVALS", "PREPVARARGS", "LOADKX"})
_NONE_OPS = frozenset({"NOP", "BREAK", "NATIVECALL"})

_JUMP_D_OPS = frozenset(
    {
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
        "FORNPREP",
        "FORNLOOP",
        "FORGPREP",
        "FORGLOOP",
        "FORGPREP_INEXT",
        "FORGPREP_NEXT",
        "JUMPXEQKNIL",
        "JUMPXEQKB",
        "JUMPXEQKN",
        "JUMPXEQKS",
        "CMPPROTO",
    }
)
_FASTCALL_OPS = frozenset({"FASTCALL", "FASTCALL1", "FASTCALL2", "FASTCALL2K", "FASTCALL3"})
_NON_FALLTHROUGH_OPS = frozenset({"RETURN", "JUMP", "JUMPBACK", "JUMPX"})
_LOOP_JUMPS = frozenset({"JUMPBACK", "FORGLOOP", "FORNLOOP"})

_MIN_VERSION = {
    "IDIV": 4,
    "IDIVK": 4,
    "SUBRK": 5,
    "DIVRK": 5,
    "FASTCALL3": 6,
    "GETUDATAKS": 9,
    "SETUDATAKS": 9,
    "NAMECALLUDATA": 9,
    "NEWCLASSMEMBER": 10,
    "CALLFB": 11,
    "CMPPROTO": 11,
    "NEWCLASS": 100,
}

_BUILTIN_NAMES = (
    "none",
    "assert",
    "math.abs",
    "math.acos",
    "math.asin",
    "math.atan2",
    "math.atan",
    "math.ceil",
    "math.cosh",
    "math.cos",
    "math.deg",
    "math.exp",
    "math.floor",
    "math.fmod",
    "math.frexp",
    "math.ldexp",
    "math.log10",
    "math.log",
    "math.max",
    "math.min",
    "math.modf",
    "math.pow",
    "math.rad",
    "math.sinh",
    "math.sin",
    "math.sqrt",
    "math.tanh",
    "math.tan",
    "bit32.arshift",
    "bit32.band",
    "bit32.bnot",
    "bit32.bor",
    "bit32.bxor",
    "bit32.btest",
    "bit32.extract",
    "bit32.lrotate",
    "bit32.lshift",
    "bit32.replace",
    "bit32.rrotate",
    "bit32.rshift",
    "type",
    "string.byte",
    "string.char",
    "string.len",
    "typeof",
    "string.sub",
    "math.clamp",
    "math.sign",
    "math.round",
    "rawset",
    "rawget",
    "rawequal",
    "table.insert",
    "table.unpack",
    "vector.create",
    "bit32.countlz",
    "bit32.countrz",
    "select",
    "rawlen",
    "bit32.extract",
    "getmetatable",
    "setmetatable",
    "tonumber",
    "tostring",
    "bit32.byteswap",
    "buffer.readi8",
    "buffer.readu8",
    "buffer.writeu8",
    "buffer.readi16",
    "buffer.readu16",
    "buffer.writeu16",
    "buffer.readi32",
    "buffer.readu32",
    "buffer.writeu32",
    "buffer.readf32",
    "buffer.writef32",
    "buffer.readf64",
    "buffer.writef64",
    "vector.magnitude",
    "vector.normalize",
    "vector.cross",
    "vector.dot",
    "vector.floor",
    "vector.ceil",
    "vector.abs",
    "vector.sign",
    "vector.clamp",
    "vector.min",
    "vector.max",
    "math.lerp",
    "vector.lerp",
    "math.isnan",
    "math.isinf",
    "math.isfinite",
    "integer.create",
    "integer.tonumber",
    "integer.neg",
    "integer.add",
    "integer.sub",
    "integer.mul",
    "integer.div",
    "integer.min",
    "integer.max",
    "integer.rem",
    "integer.idiv",
    "integer.udiv",
    "integer.urem",
    "integer.mod",
    "integer.clamp",
    "integer.band",
    "integer.bor",
    "integer.bnot",
    "integer.bxor",
    "integer.lt",
    "integer.le",
    "integer.ult",
    "integer.ule",
    "integer.gt",
    "integer.ge",
    "integer.ugt",
    "integer.uge",
    "integer.lshift",
    "integer.rshift",
    "integer.arshift",
    "integer.lrotate",
    "integer.rrotate",
    "integer.extract",
    "integer.btest",
    "integer.countrz",
    "integer.countlz",
    "integer.bswap",
    "buffer.readinteger",
    "buffer.writeinteger",
)


def _encoding_for(name: str) -> InstructionEncoding:
    if name in _NONE_OPS:
        return InstructionEncoding.NONE
    if name in _A_OPS:
        return InstructionEncoding.A
    if name in _AD_OPS:
        return InstructionEncoding.AD
    if name in _E_OPS:
        return InstructionEncoding.E
    return InstructionEncoding.ABC


_OPCODE_INFO = tuple(
    OpcodeInfo(
        name=name,
        encoding=_encoding_for(name),
        has_aux=name in _AUX_OPS,
        min_version=_MIN_VERSION.get(name, 3),
    )
    for name in _OPCODE_NAMES
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
    def info(self) -> OpcodeInfo | None:
        return opcode_info(self.opcode)

    @property
    def encoding(self) -> InstructionEncoding:
        info = self.info
        return info.encoding if info else InstructionEncoding.ABC

    @property
    def expects_aux(self) -> bool:
        info = self.info
        return bool(info and info.has_aux)

    @property
    def size(self) -> int:
        return 2 if self.expects_aux else 1

    @property
    def jump_target(self) -> int | None:
        return get_jump_target(self)

    @property
    def builtin_id(self) -> int | None:
        return self.a if self.name in _FASTCALL_OPS else None

    @property
    def builtin_name(self) -> str | None:
        return builtin_name(self.a) if self.name in _FASTCALL_OPS else None

    @property
    def aux_kv(self) -> int | None:
        return None if self.aux is None else self.aux & 0xFFFFFF

    @property
    def aux_not(self) -> bool:
        return bool(self.aux is not None and self.aux >> 31)

    @property
    def aux_a(self) -> int | None:
        return None if self.aux is None else self.aux & 0xFF

    @property
    def aux_b(self) -> int | None:
        return None if self.aux is None else (self.aux >> 8) & 0xFF

    @property
    def userdata_constant_index(self) -> int | None:
        return None if self.aux is None else self.aux & 0xFFFF

    @property
    def userdata_slot(self) -> int | None:
        return None if self.aux is None else self.aux >> 16

    def operand_text(self) -> str:
        if self.encoding is InstructionEncoding.NONE:
            text = ""
        elif self.encoding is InstructionEncoding.A:
            text = f"A={self.a}"
        elif self.encoding is InstructionEncoding.AD:
            text = f"A={self.a} D={self.d}"
        elif self.encoding is InstructionEncoding.E:
            text = f"E={self.e}"
        else:
            text = f"A={self.a} B={self.b} C={self.c}"
        if self.expects_aux:
            aux = "<missing>" if self.aux is None else f"0x{self.aux:08x}"
            text = f"{text} AUX={aux}".strip()
        return text

    def render(self) -> str:
        operands = self.operand_text()
        suffix = f" {operands}" if operands else ""
        return f"{self.pc:04d}  0x{self.word:08x}  {self.name:<18}{suffix}"


def _sign(value: int, bits: int) -> int:
    sign = 1 << (bits - 1)
    return (value ^ sign) - sign


def opcode_info(opcode: int) -> OpcodeInfo | None:
    return _OPCODE_INFO[opcode] if 0 <= opcode < len(_OPCODE_INFO) else None


def opcode_name(opcode: int) -> str:
    info = opcode_info(opcode)
    return info.name if info else f"OP_{opcode}"


def opcode_count() -> int:
    return len(_OPCODE_INFO)


def opcode_names() -> tuple[str, ...]:
    return _OPCODE_NAMES


def builtin_count() -> int:
    return len(_BUILTIN_NAMES)


def opcode_supported(opcode: int, bytecode_version: int) -> bool:
    info = opcode_info(opcode)
    if info is None:
        return False
    if info.min_version == 100:
        return bytecode_version == 100
    return bytecode_version == 100 or bytecode_version >= info.min_version


def has_aux_word(opcode: int | str) -> bool:
    name = opcode if isinstance(opcode, str) else opcode_name(opcode)
    return name in _AUX_OPS


def is_fastcall(opcode: int | str) -> bool:
    name = opcode if isinstance(opcode, str) else opcode_name(opcode)
    return name in _FASTCALL_OPS


def is_fallthrough(opcode: int | str) -> bool:
    name = opcode if isinstance(opcode, str) else opcode_name(opcode)
    return name not in _NON_FALLTHROUGH_OPS


def is_loop_jump(opcode: int | str) -> bool:
    name = opcode if isinstance(opcode, str) else opcode_name(opcode)
    return name in _LOOP_JUMPS


def builtin_name(identifier: int) -> str | None:
    if 0 <= identifier < len(_BUILTIN_NAMES):
        return _BUILTIN_NAMES[identifier]
    return None


def get_jump_target(instruction: DecodedInstruction) -> int | None:
    if instruction.name in _JUMP_D_OPS:
        return instruction.pc + instruction.d + 1
    if instruction.name in _FASTCALL_OPS:
        return instruction.pc + instruction.c + 2
    if instruction.name == "LOADB" and instruction.c:
        return instruction.pc + instruction.c + 1
    if instruction.name == "JUMPX":
        return instruction.pc + instruction.e + 1
    return None


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


def decode_words(
    words: Iterable[int],
    *,
    strict: bool = False,
    bytecode_version: int | None = None,
) -> list[DecodedInstruction]:
    values = tuple(words)
    result: list[DecodedInstruction] = []
    pc = 0
    while pc < len(values):
        word = values[pc]
        opcode = word & 0xFF
        info = opcode_info(opcode)
        if strict and info is None:
            raise ValueError(f"unknown Luau opcode {opcode} at word {pc}")
        if strict and bytecode_version is not None and not opcode_supported(
            opcode, bytecode_version
        ):
            name = opcode_name(opcode)
            raise ValueError(
                f"opcode {name} is not valid for Luau bytecode v{bytecode_version} "
                f"at word {pc}"
            )
        expects_aux = bool(info and info.has_aux)
        if expects_aux and pc + 1 >= len(values):
            if strict:
                raise ValueError(
                    f"opcode {opcode_name(opcode)} at word {pc} is missing its AUX word"
                )
            aux = None
        else:
            aux = values[pc + 1] if expects_aux else None
        instruction = decode_word(word, pc, aux)
        result.append(instruction)
        pc += instruction.size
    return result


def disassemble_words(data: bytes) -> str:
    instructions = decode_words(unpack_words(data))
    rendered = "\n".join(instruction.render() for instruction in instructions)
    return rendered + ("\n" if instructions else "")
