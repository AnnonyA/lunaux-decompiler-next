from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "src/lunaux/backends/bytecode.py"
text = path.read_text(encoding="utf-8")

replacements = (
    (
        "from dataclasses import dataclass\nfrom typing import TypeAlias, cast\n\nfrom lunaux.backends.opcodes import (",
        "from dataclasses import dataclass, replace\nfrom typing import TypeAlias, cast\n\nfrom lunaux.backends.opcode_encoding import (\n    candidate_opcode_multipliers,\n    decode_multiplicative_opcode_words,\n)\nfrom lunaux.backends.opcodes import (",
    ),
    (
        "    userdata_types: tuple[tuple[int, str], ...] = ()\n\n    @property\n    def main_proto(self) -> LuauProto:",
        "    userdata_types: tuple[tuple[int, str], ...] = ()\n    opcode_encoding: str | None = None\n\n    @property\n    def main_proto(self) -> LuauProto:",
    ),
    (
        "def _validate_module(module: LuauBytecodeModule) -> None:\n    for proto in module.protos:\n        _validate_constant_graph(proto, len(module.protos))\n        _validate_proto_code(proto, module.version, module.protos)\n\n\ndef parse_bytecode(data: bytes) -> LuauBytecodeModule:",
        '''def _validate_module(module: LuauBytecodeModule) -> None:\n    for proto in module.protos:\n        _validate_constant_graph(proto, len(module.protos))\n        _validate_proto_code(proto, module.version, module.protos)\n\n\ndef _contains_nonstandard_opcode_stream(module: LuauBytecodeModule) -> bool:\n    for proto in module.protos:\n        try:\n            decode_words(\n                proto.code,\n                strict=True,\n                bytecode_version=module.version,\n            )\n        except ValueError:\n            return True\n    return False\n\n\ndef _module_with_opcode_multiplier(\n    module: LuauBytecodeModule,\n    multiplier: int,\n) -> LuauBytecodeModule:\n    protos = tuple(\n        replace(\n            proto,\n            code=decode_multiplicative_opcode_words(\n                proto.code,\n                multiplier,\n                bytecode_version=module.version,\n            ),\n        )\n        for proto in module.protos\n    )\n    return replace(\n        module,\n        protos=protos,\n        opcode_encoding=f"multiplicative:{multiplier}",\n    )\n\n\ndef _recover_opcode_encoding(\n    module: LuauBytecodeModule,\n) -> LuauBytecodeModule | None:\n    if not _contains_nonstandard_opcode_stream(module):\n        return None\n\n    inferred: list[LuauBytecodeModule] = []\n    for multiplier in candidate_opcode_multipliers():\n        try:\n            candidate = _module_with_opcode_multiplier(module, multiplier)\n            _validate_module(candidate)\n        except (BytecodeFormatError, ValueError):\n            continue\n\n        if multiplier == 227:\n            return candidate\n        inferred.append(candidate)\n        if len(inferred) > 1:\n            return None\n\n    return inferred[0] if len(inferred) == 1 else None\n\n\ndef parse_bytecode(data: bytes) -> LuauBytecodeModule:''',
    ),
    (
        "    _validate_module(module)\n    return module\n",
        "    try:\n        _validate_module(module)\n    except BytecodeFormatError:\n        recovered = _recover_opcode_encoding(module)\n        if recovered is None:\n            raise\n        module = recovered\n    return module\n",
    ),
)

for old, new in replacements:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match, found {count}: {old[:80]!r}")
    text = text.replace(old, new, 1)

path.write_text(text, encoding="utf-8")
