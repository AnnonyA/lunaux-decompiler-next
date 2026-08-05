from __future__ import annotations

import argparse
import re
from pathlib import Path

from lunaux.backends.bytecode import (
    CONSTANT_TAG_NAMES,
    SUPPORTED_BYTECODE_VERSIONS,
)
from lunaux.backends.opcodes import builtin_count, opcode_names

_OPCODE = re.compile(r"^\s*LOP_([A-Z0-9_]+)\s*(?:=\s*[^,]+)?\s*,")
_BUILTIN = re.compile(r"^\s*LBF_([A-Z0-9_]+)\s*(?:=\s*[^,]+)?\s*,")
_CONSTANT = re.compile(r"^\s*LBC_CONSTANT_([A-Z0-9_]+)\s*(?:=\s*[^,]+)?\s*,")
_VALUE = re.compile(r"^\s*(LBC_VERSION_[A-Z]+)\s*=\s*(\d+)\s*,")


def _enum_values(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    return tuple(
        match.group(1)
        for line in text.splitlines()
        if (match := pattern.match(line))
    )


def check_header(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []

    upstream_opcodes = tuple(
        name for name in _enum_values(_OPCODE, text) if name != "_COUNT"
    )
    if upstream_opcodes != opcode_names():
        missing = [name for name in upstream_opcodes if name not in opcode_names()]
        extra = [name for name in opcode_names() if name not in upstream_opcodes]
        errors.append(
            "opcode table differs from upstream"
            f"; missing={missing or 'none'}; extra={extra or 'none'}"
        )

    upstream_constants = tuple(
        name for name in _enum_values(_CONSTANT, text) if name != "_COUNT"
    )
    if upstream_constants != CONSTANT_TAG_NAMES:
        errors.append(
            "constant tag table differs from upstream"
            f"; upstream={upstream_constants}; local={CONSTANT_TAG_NAMES}"
        )

    upstream_builtins = tuple(
        name for name in _enum_values(_BUILTIN, text) if name != "_COUNT"
    )
    if len(upstream_builtins) != builtin_count():
        errors.append(
            f"builtin count differs: upstream={len(upstream_builtins)} "
            f"local={builtin_count()}"
        )

    versions = {
        match.group(1): int(match.group(2))
        for line in text.splitlines()
        if (match := _VALUE.match(line))
    }
    minimum = versions.get("LBC_VERSION_MIN")
    maximum = versions.get("LBC_VERSION_MAX")
    classes = versions.get("LBC_VERSION_CLASSES")
    if minimum is None or maximum is None:
        errors.append("could not read LBC_VERSION_MIN/MAX")
    else:
        expected = set(range(minimum, maximum + 1))
        if classes is not None:
            expected.add(classes)
        unsupported = expected - SUPPORTED_BYTECODE_VERSIONS
        if unsupported:
            errors.append(
                "upstream bytecode versions are not supported locally: "
                + ", ".join(str(item) for item in sorted(unsupported))
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check LunaUX opcode metadata against Luau Bytecode.h."
    )
    parser.add_argument("header", type=Path)
    arguments = parser.parse_args()

    errors = check_header(arguments.header)
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        return 1
    print("LunaUX bytecode metadata matches the supplied Luau Bytecode.h.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
