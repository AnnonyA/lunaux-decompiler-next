from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from lunaux.backends.opcodes import opcode_info, opcode_supported


@dataclass(frozen=True, slots=True)
class OpcodeNormalization:
    """A normalized instruction stream and the multiplier used to decode it."""

    words: tuple[int, ...]
    multiplier: int

    @property
    def label(self) -> str:
        return f"multiplicative:{self.multiplier}"


def _validate_multiplier(multiplier: int) -> None:
    if not 1 <= multiplier <= 0xFF:
        raise ValueError("opcode multiplier must be between 1 and 255")
    if multiplier % 2 == 0:
        raise ValueError("opcode multiplier must be odd to be invertible modulo 256")


def decode_multiplicative_opcode_words(
    words: Iterable[int],
    multiplier: int,
    *,
    bytecode_version: int,
) -> tuple[int, ...]:
    """Decode opcodes transformed as ``encoded = opcode * multiplier mod 256``.

    Only the least-significant opcode byte of each instruction word is changed.
    AUX words are copied byte-for-byte and are never interpreted as instructions.
    """

    _validate_multiplier(multiplier)
    inverse = pow(multiplier, -1, 256)
    values = tuple(words)
    normalized = list(values)
    pc = 0

    while pc < len(values):
        encoded_opcode = values[pc] & 0xFF
        opcode = (encoded_opcode * inverse) & 0xFF
        info = opcode_info(opcode)
        if info is None:
            raise ValueError(
                f"multiplier {multiplier} decodes opcode byte {encoded_opcode} "
                f"to unknown Luau opcode {opcode} at word {pc}"
            )
        if not opcode_supported(opcode, bytecode_version):
            raise ValueError(
                f"multiplier {multiplier} decodes an opcode that is not valid "
                f"for Luau bytecode v{bytecode_version} at word {pc}"
            )

        normalized[pc] = (values[pc] & 0xFFFFFF00) | opcode
        size = 2 if info.has_aux else 1
        if pc + size > len(values):
            raise ValueError(
                f"decoded opcode {info.name} at word {pc} is missing its AUX word"
            )
        pc += size

    return tuple(normalized)


def candidate_opcode_multipliers() -> tuple[int, ...]:
    """Return deterministic candidates, preferring Roblox's common multiplier."""

    preferred = 227
    return (
        preferred,
        *(value for value in range(3, 256, 2) if value != preferred),
    )
