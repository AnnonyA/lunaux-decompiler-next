from __future__ import annotations

import re

import lunaux.backends.quality_lifter as quality

_INSTALLED = False
_SCALAR_LITERAL = re.compile(
    r"(?:nil|true|false|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\"(?:\\.|[^\"])*\"|'(?:\\.|[^'])*')"
)
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _normalize_operand(expression: str) -> str:
    expression = expression.strip()
    while expression.startswith("(") and expression.endswith(")"):
        expression = expression[1:-1].strip()
    return expression


def _replace_identifier(expression: str, name: str, replacement: str) -> str:
    """Replace a standalone identifier in a generated pure expression."""

    return re.sub(rf"(?<![A-Za-z0-9_.:]){re.escape(name)}(?![A-Za-z0-9_])", replacement, expression)


def _rewrite_extended_boolean_ladders(text: str) -> str:
    """Recover short-circuit ladders whose final predicate uses scalar temporaries.

    Legacy Luau can materialize a comparison constant in a temporary inside the final
    guarded edge. The simpler ladder recovery intentionally rejects that extra line.
    Accept only straight-line scalar-literal temporaries followed by the result write,
    inline those temporaries into the final predicate, and collapse the same complete
    short-circuit CFG shape. Calls, table reads, writes, and nested control flow remain
    untouched.
    """

    lines = text.splitlines()
    result: list[str] = []
    index = 0
    while index < len(lines):
        outer = re.fullmatch(r"(?P<indent>\s*)if\s+(.+)\s+then", lines[index])
        if outer is None or index + 9 >= len(lines):
            result.append(lines[index])
            index += 1
            continue

        indent = outer.group("indent")
        child = indent + "    "
        grandchild = child + "    "
        first = re.fullmatch(
            rf"{re.escape(child)}(?:local\s+)?"
            r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*not\s+(.+)",
            lines[index + 1],
        )
        if first is None:
            result.append(lines[index])
            index += 1
            continue

        name = first.group("name")
        if lines[index + 2] != f"{child}if not {name} then" or lines[index + 3] != f"{child}end":
            result.append(lines[index])
            index += 1
            continue

        second = re.fullmatch(
            rf"{re.escape(child)}{re.escape(name)}\s*=\s*(.+)",
            lines[index + 4],
        )
        if second is None or lines[index + 5] != f"{child}if {name} then":
            result.append(lines[index])
            index += 1
            continue

        inner_end = index + 6
        while inner_end < len(lines) and lines[inner_end] != f"{child}end":
            inner_end += 1
        if inner_end >= len(lines) or inner_end + 1 >= len(lines):
            result.append(lines[index])
            index += 1
            continue
        if lines[inner_end + 1] != f"{indent}end":
            result.append(lines[index])
            index += 1
            continue

        body = lines[index + 6 : inner_end]
        if len(body) < 2:
            result.append(lines[index])
            index += 1
            continue
        final = re.fullmatch(
            rf"{re.escape(grandchild)}{re.escape(name)}\s*=\s*(.+)",
            body[-1],
        )
        if final is None:
            result.append(lines[index])
            index += 1
            continue

        replacements: list[tuple[str, str]] = []
        valid = True
        for line in body[:-1]:
            temporary = re.fullmatch(
                rf"{re.escape(grandchild)}(?:local\s+)?"
                r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.+)",
                line,
            )
            if temporary is None:
                valid = False
                break
            temporary_name = temporary.group("name")
            temporary_value = temporary.group("value").strip()
            if temporary_name == name or _SCALAR_LITERAL.fullmatch(temporary_value) is None:
                valid = False
                break
            if any(previous_name == temporary_name for previous_name, _ in replacements):
                valid = False
                break
            replacements.append((temporary_name, temporary_value))
        if not valid:
            result.append(lines[index])
            index += 1
            continue

        negated_operand = _normalize_operand(first.group(2))
        second_operand = _normalize_operand(second.group(1))
        if negated_operand != second_operand:
            result.append(lines[index])
            index += 1
            continue

        tail = final.group(1).strip()
        for temporary_name, temporary_value in replacements:
            if _IDENTIFIER.search(tail) is None:
                valid = False
                break
            tail = _replace_identifier(tail, temporary_name, f"({temporary_value})")
        if not valid:
            result.append(lines[index])
            index += 1
            continue

        declared = any(
            re.search(rf"\blocal\b[^\n]*\b{re.escape(name)}\b", previous)
            for previous in lines[:index]
        )
        prefix = "" if declared else "local "
        condition = outer.group(2).strip()
        result.append(
            f"{indent}{prefix}{name} = "
            f"({condition} and not ({second_operand})) or "
            f"({second_operand} and ({tail}))"
        )
        index = inner_end + 2

    return "\n".join(result).rstrip() + "\n"


def install_final_semantics_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original_clean_output = quality._clean_output

    def _clean_output(text: str) -> str:
        return _rewrite_extended_boolean_ladders(original_clean_output(text))

    setattr(quality, "_clean_output", _clean_output)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_final_semantics_fix"]
