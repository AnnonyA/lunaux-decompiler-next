from __future__ import annotations

from lunaux.backends.legacy_repeat_fix import _rewrite_terminal_repeat_guard_temporaries


def test_terminal_inner_while_becomes_repeat_guard() -> None:
    lines = [
        "while true do",
        "    value = value + 1",
        "    while remainder ~= zero do",
        "        value2 = limit",
        "        if value2 <= steps then",
        "            break",
        "        end",
        "    end",
        "end",
        "print(value)",
    ]

    assert _rewrite_terminal_repeat_guard_temporaries(lines) == [
        "repeat",
        "    value = value + 1",
        "until remainder == zero or limit <= steps",
        "print(value)",
    ]


def test_repeat_rewrite_rejects_side_effectful_temporary() -> None:
    lines = [
        "while true do",
        "    update()",
        "    while flag do",
        "        value2 = nextLimit()",
        "        if value2 <= steps then",
        "            break",
        "        end",
        "    end",
        "end",
    ]

    assert _rewrite_terminal_repeat_guard_temporaries(lines) == lines
