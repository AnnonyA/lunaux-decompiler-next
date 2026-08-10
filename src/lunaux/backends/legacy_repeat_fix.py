from __future__ import annotations

import re

import lunaux.backends.quality_lifter as quality

_INSTALLED = False
_TEMPORARY_NAME = re.compile(r"^(?:value|v|r|reg|temp|tmp)\d+$", re.IGNORECASE)
_ATOMIC_RHS = re.compile(
    r"^(?:nil|true|false|-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|"
    r"[A-Za-z_][A-Za-z0-9_]*)$"
)
_ASSIGNMENT = re.compile(
    r"^(?P<lhs>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<rhs>.+?)\s*$"
)


def _identifier_occurs(text: str, name: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])", text) is not None


def _replace_identifier(text: str, name: str, replacement: str) -> str:
    """Replace a plain identifier in a condition while preserving field selectors."""

    pattern = re.compile(
        rf"(?<![A-Za-z0-9_.:]){re.escape(name)}(?![A-Za-z0-9_])"
    )
    return pattern.sub(replacement, text)


def _rewrite_terminal_repeat_guard_temporaries(lines: list[str]) -> list[str]:
    """Recover repeat-until ladders misidentified as terminal nested while loops.

    Legacy Luau v3/v6 can lower ``until left or right`` into a conditional ladder whose
    backedge targets the *outer* repeat body.  The generic loop structurer can interpret
    that backedge as belonging to a terminal inner ``while`` instead, which turns a
    finite repeat into an infinite outer loop.  At source level this has a distinctive,
    conservative shape: the inner loop is the last statement of ``while true``, and its
    body contains only generated temporary assignments plus ``if condition then break``
    guards.  Fold side-effect-free temporary assignments into those guards and recover
    a single ``repeat ... until`` condition.
    """

    result = list(lines)
    index = 0
    while index < len(result):
        if not re.match(r"^\s*while true do$", result[index]):
            index += 1
            continue

        outer_end = quality._find_matching_end(result, index)
        if outer_end is None:
            index += 1
            continue

        outer_indent = result[index][
            : len(result[index]) - len(result[index].lstrip())
        ]
        inner_indent = outer_indent + "    "
        candidate = outer_end - 1
        while candidate > index and not result[candidate].strip():
            candidate -= 1

        while_start: int | None = None
        for probe in range(candidate, index, -1):
            if not re.match(
                rf"^{re.escape(inner_indent)}while\s+.+\s+do$",
                result[probe],
            ):
                continue
            if quality._find_matching_end(result, probe) == candidate:
                while_start = probe
                break
        if while_start is None:
            index = outer_end + 1
            continue

        header = re.match(
            rf"^{re.escape(inner_indent)}while\s+(?P<cond>.+)\s+do$",
            result[while_start],
        )
        if header is None:
            index = outer_end + 1
            continue

        child_indent = inner_indent + "    "
        body = result[while_start + 1 : candidate]
        substitutions: dict[str, str] = {}
        substitution_used: set[str] = set()
        exit_conditions = [
            quality._simplify_not_comparisons(f"not ({header.group('cond')})")
        ]
        guard_count = 0
        cursor = 0
        valid = True

        while cursor < len(body):
            line = body[cursor]
            if not line.strip():
                cursor += 1
                continue
            if not line.startswith(child_indent):
                valid = False
                break
            relative = line[len(child_indent) :]

            assignment = _ASSIGNMENT.fullmatch(relative)
            if assignment is not None:
                lhs = assignment.group("lhs")
                rhs = assignment.group("rhs").strip()
                if not _TEMPORARY_NAME.fullmatch(lhs) or not _ATOMIC_RHS.fullmatch(rhs):
                    valid = False
                    break
                for previous_name, previous_value in substitutions.items():
                    rhs = _replace_identifier(rhs, previous_name, previous_value)
                substitutions[lhs] = rhs
                cursor += 1
                continue

            guard = re.match(r"^if\s+(?P<cond>.+)\s+then$", relative)
            if (
                guard is None
                or cursor + 2 >= len(body)
                or body[cursor + 1] != child_indent + "    break"
                or body[cursor + 2] != child_indent + "end"
            ):
                valid = False
                break

            condition = guard.group("cond")
            for temporary, replacement in substitutions.items():
                if _identifier_occurs(condition, temporary):
                    substitution_used.add(temporary)
                condition = _replace_identifier(condition, temporary, replacement)
            exit_conditions.append(quality._simplify_not_comparisons(condition))
            guard_count += 1
            cursor += 3

        if (
            not valid
            or guard_count == 0
            or set(substitutions) != substitution_used
        ):
            index = outer_end + 1
            continue

        result[index] = outer_indent + "repeat"
        del result[while_start : candidate + 1]
        outer_end -= candidate + 1 - while_start
        deduped = list(dict.fromkeys(exit_conditions))
        result[outer_end] = outer_indent + "until " + " or ".join(deduped)
        index = outer_end + 1

    return result


def install_legacy_repeat_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    original = quality._rewrite_terminal_repeat_guards

    def _rewrite(lines: list[str]) -> list[str]:
        return _rewrite_terminal_repeat_guard_temporaries(original(lines))

    setattr(quality, "_rewrite_terminal_repeat_guards", _rewrite)  # noqa: B010
    _INSTALLED = True


__all__ = ["install_legacy_repeat_fix"]
