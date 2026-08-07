from __future__ import annotations

import difflib
import re

from lunaux.benchmark_quality_models import ReadabilityMetrics

_FALLBACK_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"failed to decompile",
        r"could not parse .* bytecode",
        r"unsupported",
        r"unknown (?:luau )?opcode",
        r"stack top",
        r"jumpback",
        r"\bgoto\b",
        r"\blabel[_ ]?\d+\b",
        r"--\s*(?:pc|opcode|jump)\b",
        r"compatibility representation",
        r"raw instruction stream",
    )
)
_GENERATED_IDENTIFIER_RE = re.compile(
    r"\b(?:r|reg|v|var|temp|tmp|local|arg|num|bool|str|tbl|table|"
    r"func|function|upvalue|upval)_?\d+\b",
    re.IGNORECASE,
)
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_STRUCTURE_TOKEN_RE = re.compile(
    r"\b(?:if|then|elseif|else|end|while|repeat|until|for|in|do|"
    r"function|local|return|break|continue|and|or|not)\b|"
    r"==|~=|<=|>=|\.\.|[(){}\[\],;:+\-*/%^#<>.=]"
)


def readability_metrics(output: str, source: str | None = None) -> ReadabilityMetrics:
    fallback_count = sum(len(pattern.findall(output)) for pattern in _FALLBACK_PATTERNS)
    identifiers = _IDENTIFIER_RE.findall(output)
    generated = _GENERATED_IDENTIFIER_RE.findall(output)
    generated_ratio = len(generated) / len(identifiers) if identifiers else 1.0

    output_tokens = _STRUCTURE_TOKEN_RE.findall(output)
    source_tokens = _STRUCTURE_TOKEN_RE.findall(source or "")
    structural_similarity = (
        difflib.SequenceMatcher(a=source_tokens, b=output_tokens).ratio()
        if source_tokens
        else (1.0 if output_tokens else 0.0)
    )

    lines = output.splitlines()
    if lines:
        long_lines = sum(len(line) > 120 for line in lines)
        trailing = sum(line.rstrip() != line for line in lines)
        style_score = max(0.0, 1.0 - (long_lines + trailing) / len(lines))
    else:
        style_score = 0.0

    fallback_score = max(0.0, 1.0 - fallback_count / 5.0)
    score = 100.0 * (
        0.35 * structural_similarity
        + 0.25 * (1.0 - min(generated_ratio, 1.0))
        + 0.25 * fallback_score
        + 0.15 * style_score
    )
    return ReadabilityMetrics(
        round(max(0.0, min(score, 100.0)), 4),
        fallback_count,
        round(generated_ratio, 6),
        round(structural_similarity, 6),
        round(style_score, 6),
    )
