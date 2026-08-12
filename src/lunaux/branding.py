from __future__ import annotations

import os
from datetime import UTC, datetime

from lunaux import __version__
from lunaux.backends.bytecode import is_supported_bytecode_version

PRODUCT_NAME = "ByteWeft"


def _decompilation_time() -> datetime:
    source_date_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if source_date_epoch is not None:
        try:
            return datetime.fromtimestamp(int(source_date_epoch), UTC)
        except (OverflowError, ValueError):
            pass
    return datetime.now(UTC)


def decompilation_header(bytecode: bytes) -> str:
    timestamp = _decompilation_time().isoformat(timespec="seconds").replace("+00:00", "Z")
    if bytecode and is_supported_bytecode_version(bytecode[0]):
        bytecode_label = f"bytecode v{bytecode[0]}"
        if bytecode[0] >= 4 and len(bytecode) > 1:
            bytecode_label += f" | types v{bytecode[1]}"
    else:
        bytecode_label = "raw instruction stream"
    return (
        f"-- [[ {PRODUCT_NAME} v{__version__} | decompiled at {timestamp} | "
        f"{bytecode_label} ]]\n"
    )
