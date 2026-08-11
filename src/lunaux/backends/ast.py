from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

_IDENTIFIER: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NUMBER: Final[re.Pattern[str]] = re.compile(
    r"^(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$|^0[xX][0-9A-Fa-f]+$"
)
_RESERVED: Final[frozenset[str]] = frozenset(
    {
        "and",
        "break",
        "continue",
        "do",
        "else",
        "elseif",
        "end",
        "export",
        "false",
        "for",
        "function",
        "if",
        "in",
        "local",
        "nil",
        "not",
        "or",
        "repeat",
        "return",
        "then",
        "true",
        "type",
        "typeof",
        "until",
        "while",
    }
)


class Precedence(IntEnum):
    LOWEST = 0
    OR = 10
    AND = 20
    COMPARISON = 30
    CONCAT = 40
    ADDITIVE = 50
    MULTIPLICATIVE = 60
    UNARY = 70
    POWER = 80
    POSTFIX = 90
    ATOM = 100


_BINARY_PRECEDENCE: Final[dict[str, Precedence]] = {
    "or": Precedence.OR,
    "and": Precedence.AND,
    "<": Precedence.COMPARISON,
    "<=": Precedence.COMPARISON,
    ">": Precedence.COMPARISON,
    ">=": Precedence.COMPARISON,
    "==": Precedence.COMPARISON,
    "~=": Precedence.COMPARISON,
    "..": Precedence.CONCAT,
    "+": Precedence.ADDITIVE,
    "-": Precedence.ADDITIVE,
    "*": Precedence.MULTIPLICATIVE,
    "/": Precedence.MULTIPLICATIVE,
    "//": Precedence.MULTIPLICATIVE,
    "%": Precedence.MULTIPLICATIVE,
    "^": Precedence.POWER,
}
_RIGHT_ASSOCIATIVE: Final[frozenset[str]] = frozenset({"..", "^"})
_COMPARISONS: Final[frozenset[str]] = frozenset({"<", "<=", ">", ">=", "==", "~="})


class Expr:
    @property
    def precedence(self) -> Precedence:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class RawExpr(Expr):
    text: str
    level: Precedence = Precedence.LOWEST

    @property
    def precedence(self) -> Precedence:
        return self.level


@dataclass(frozen=True, slots=True)
class NameExpr(Expr):
    name: str

    @property
    def precedence(self) -> Precedence:
        return Precedence.ATOM


@dataclass(frozen=True, slots=True)
class LiteralExpr(Expr):
    text: str

    @property
    def precedence(self) -> Precedence:
        return Precedence.ATOM


@dataclass(frozen=True, slots=True)
class VarargExpr(Expr):
    @property
    def precedence(self) -> Precedence:
        return Precedence.ATOM


@dataclass(frozen=True, slots=True)
class UnaryExpr(Expr):
    operator: str
    operand: Expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.UNARY


@dataclass(frozen=True, slots=True)
class BinaryExpr(Expr):
    left: Expr
    operator: str
    right: Expr

    def __post_init__(self) -> None:
        if self.operator not in _BINARY_PRECEDENCE:
            raise ValueError(f"unsupported Luau binary operator: {self.operator}")

    @property
    def precedence(self) -> Precedence:
        return _BINARY_PRECEDENCE[self.operator]


@dataclass(frozen=True, slots=True)
class FieldExpr(Expr):
    base: Expr
    field: str

    @property
    def precedence(self) -> Precedence:
        return Precedence.POSTFIX


@dataclass(frozen=True, slots=True)
class IndexExpr(Expr):
    base: Expr
    index: Expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.POSTFIX


@dataclass(frozen=True, slots=True)
class CallExpr(Expr):
    function: Expr
    arguments: tuple[Expr, ...]

    @property
    def precedence(self) -> Precedence:
        return Precedence.POSTFIX


@dataclass(frozen=True, slots=True)
class MethodCallExpr(Expr):
    base: Expr
    method: str
    arguments: tuple[Expr, ...]

    @property
    def precedence(self) -> Precedence:
        return Precedence.POSTFIX


@dataclass(frozen=True, slots=True)
class TableField:
    key: Expr | None
    value: Expr
    name: str | None = None


@dataclass(frozen=True, slots=True)
class TableExpr(Expr):
    fields: tuple[TableField, ...] = ()

    @property
    def precedence(self) -> Precedence:
        return Precedence.ATOM


@dataclass(frozen=True, slots=True)
class IfExpr(Expr):
    condition: Expr
    then_value: Expr
    else_value: Expr

    @property
    def precedence(self) -> Precedence:
        return Precedence.LOWEST


class Statement:
    pass


@dataclass(frozen=True, slots=True)
class ExpressionStatement(Statement):
    expression: Expr


@dataclass(frozen=True, slots=True)
class Assignment(Statement):
    targets: tuple[Expr, ...]
    values: tuple[Expr, ...]
    local: bool = False


@dataclass(frozen=True, slots=True)
class CompoundAssignment(Statement):
    target: Expr
    operator: str
    value: Expr

    def __post_init__(self) -> None:
        if self.operator not in {"+", "-", "*", "/", "//", "%", "^", ".."}:
            raise ValueError(f"unsupported Luau compound operator: {self.operator}")


@dataclass(frozen=True, slots=True)
class ReturnStatement(Statement):
    values: tuple[Expr, ...] = ()


@dataclass(frozen=True, slots=True)
class BreakStatement(Statement):
    pass


@dataclass(frozen=True, slots=True)
class ContinueStatement(Statement):
    pass


@dataclass(frozen=True, slots=True)
class RawStatement(Statement):
    text: str


@dataclass(frozen=True, slots=True)
class Block:
    statements: tuple[Statement, ...] = ()


@dataclass(frozen=True, slots=True)
class IfStatement(Statement):
    condition: Expr
    then_block: Block
    else_block: Block | None = None


@dataclass(frozen=True, slots=True)
class WhileStatement(Statement):
    condition: Expr
    body: Block


@dataclass(frozen=True, slots=True)
class RepeatStatement(Statement):
    body: Block
    condition: Expr


@dataclass(frozen=True, slots=True)
class FunctionStatement(Statement):
    name: str
    parameters: tuple[str, ...]
    body: Block
    local: bool = True
    vararg: bool = False


def source_expr(text: str) -> Expr:
    stripped = text.strip()
    if stripped == "...":
        return VarargExpr()
    if stripped in {"nil", "true", "false"}:
        return LiteralExpr(stripped)
    if _NUMBER.fullmatch(stripped):
        return LiteralExpr(stripped)
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {'"', "'"}:
        return LiteralExpr(stripped)
    if _IDENTIFIER.fullmatch(stripped) and stripped not in _RESERVED:
        return NameExpr(stripped)
    return RawExpr(stripped)


def ensure_expr(value: Expr | str) -> Expr:
    return value if isinstance(value, Expr) else source_expr(value)


def _identifier(value: str) -> bool:
    return bool(_IDENTIFIER.fullmatch(value)) and value not in _RESERVED


def _needs_parentheses(
    child: Expr,
    parent_precedence: Precedence,
    *,
    side: str | None = None,
    parent_operator: str | None = None,
) -> bool:
    if child.precedence < parent_precedence:
        return True
    if child.precedence > parent_precedence:
        return False
    if not isinstance(child, BinaryExpr) or parent_operator is None:
        return False
    if parent_operator in _COMPARISONS:
        return True
    if parent_operator in _RIGHT_ASSOCIATIVE:
        return side == "left"
    return side == "right"


def _render_child(
    child: Expr,
    parent_precedence: Precedence,
    *,
    side: str | None = None,
    parent_operator: str | None = None,
) -> str:
    rendered = render_expression(child)
    if _needs_parentheses(
        child,
        parent_precedence,
        side=side,
        parent_operator=parent_operator,
    ):
        return f"({rendered})"
    return rendered


def render_expression(
    expression: Expr,
    *,
    pretty_tables: bool = False,
    indent: int = 0,
) -> str:
    if isinstance(expression, RawExpr):
        return expression.text
    if isinstance(expression, NameExpr):
        return expression.name
    if isinstance(expression, LiteralExpr):
        return expression.text
    if isinstance(expression, VarargExpr):
        return "..."
    if isinstance(expression, UnaryExpr):
        operand = _render_child(expression.operand, Precedence.UNARY)
        if isinstance(expression.operand, UnaryExpr):
            operand = f"({render_expression(expression.operand)})"
        separator = " " if expression.operator == "not" else ""
        return f"{expression.operator}{separator}{operand}"
    if isinstance(expression, BinaryExpr):
        left = _render_child(
            expression.left,
            expression.precedence,
            side="left",
            parent_operator=expression.operator,
        )
        right = _render_child(
            expression.right,
            expression.precedence,
            side="right",
            parent_operator=expression.operator,
        )
        return f"{left} {expression.operator} {right}"
    if isinstance(expression, FieldExpr):
        base = _render_child(expression.base, Precedence.POSTFIX)
        if _identifier(expression.field):
            return f"{base}.{expression.field}"
        return f"{base}[{render_expression(LiteralExpr(repr(expression.field)))}]"
    if isinstance(expression, IndexExpr):
        base = _render_child(expression.base, Precedence.POSTFIX)
        return f"{base}[{render_expression(expression.index)}]"
    if isinstance(expression, CallExpr):
        function = _render_child(expression.function, Precedence.POSTFIX)
        arguments = ", ".join(render_expression(item) for item in expression.arguments)
        return f"{function}({arguments})"
    if isinstance(expression, MethodCallExpr):
        base = _render_child(expression.base, Precedence.POSTFIX)
        arguments = ", ".join(render_expression(item) for item in expression.arguments)
        if _identifier(expression.method):
            return f"{base}:{expression.method}({arguments})"
        method = render_expression(LiteralExpr(repr(expression.method)))
        return f"{base}[{method}]({arguments})"
    if isinstance(expression, TableExpr):
        fields: list[str] = []
        for field in expression.fields:
            value = render_expression(field.value)
            if field.name is not None and _identifier(field.name):
                fields.append(f"{field.name} = {value}")
            elif field.key is None:
                fields.append(value)
            else:
                fields.append(f"[{render_expression(field.key)}] = {value}")
        compact = "{" + ", ".join(fields) + "}"
        if (
            not pretty_tables
            or not expression.fields
            or (
                len(expression.fields) <= 3
                and len(compact) <= 88
                and not any(
                    isinstance(field.value, TableExpr)
                    and len(field.value.fields) > 3
                    for field in expression.fields
                )
            )
        ):
            return compact
        rendered_fields: list[str] = []
        prefix = "    " * (indent + 1)
        for field in expression.fields:
            value = render_expression(
                field.value,
                pretty_tables=True,
                indent=indent + 1,
            )
            if field.name is not None and _identifier(field.name):
                item = f"{field.name} = {value}"
            elif field.key is None:
                item = value
            else:
                item = f"[{render_expression(field.key)}] = {value}"
            rendered_fields.append(prefix + item + ",")
        return "{\n" + "\n".join(rendered_fields) + "\n" + "    " * indent + "}"
    if isinstance(expression, IfExpr):
        return (
            f"if {render_expression(expression.condition)} then "
            f"{render_expression(expression.then_value)} else "
            f"{render_expression(expression.else_value)}"
        )
    raise TypeError(f"unsupported expression node: {type(expression).__name__}")


def render_statement(statement: Statement) -> str:
    if isinstance(statement, ExpressionStatement):
        return render_expression(statement.expression)
    if isinstance(statement, Assignment):
        targets = ", ".join(render_expression(item) for item in statement.targets)
        values = ", ".join(render_expression(item) for item in statement.values)
        prefix = "local " if statement.local else ""
        return f"{prefix}{targets} = {values}"
    if isinstance(statement, CompoundAssignment):
        return (
            f"{render_expression(statement.target)} "
            f"{statement.operator}= {render_expression(statement.value)}"
        )
    if isinstance(statement, ReturnStatement):
        if not statement.values:
            return "return"
        return "return " + ", ".join(render_expression(item) for item in statement.values)
    if isinstance(statement, BreakStatement):
        return "break"
    if isinstance(statement, ContinueStatement):
        return "continue"
    if isinstance(statement, RawStatement):
        return statement.text
    raise TypeError(f"statement requires block-aware rendering: {type(statement).__name__}")


class LuauPrinter:
    def __init__(self, *, semicolons: bool = False, indent: str = "    ") -> None:
        self.semicolons = semicolons
        self.indent_text = indent
        self.lines: list[str] = []
        self.depth = 0

    def _line(self, text: str = "", *, statement: bool = False) -> None:
        suffix = ";" if statement and self.semicolons and text else ""
        self.lines.append(self.indent_text * self.depth + text + suffix)

    def _block(self, block: Block) -> None:
        for statement in block.statements:
            self._statement(statement)

    def _statement(self, statement: Statement) -> None:
        if isinstance(statement, ExpressionStatement):
            self._line(render_expression(statement.expression), statement=True)
            return
        if isinstance(statement, Assignment):
            self._line(render_statement(statement), statement=True)
            return
        if isinstance(statement, CompoundAssignment):
            self._line(render_statement(statement), statement=True)
            return
        if isinstance(statement, ReturnStatement):
            if statement.values:
                values = ", ".join(render_expression(item) for item in statement.values)
                suffix = " " + values
            else:
                suffix = ""
            self._line("return" + suffix, statement=True)
            return
        if isinstance(statement, BreakStatement):
            self._line("break", statement=True)
            return
        if isinstance(statement, ContinueStatement):
            self._line("continue", statement=True)
            return
        if isinstance(statement, RawStatement):
            self._line(statement.text)
            return
        if isinstance(statement, IfStatement):
            self._line(f"if {render_expression(statement.condition)} then")
            self.depth += 1
            self._block(statement.then_block)
            self.depth -= 1
            if statement.else_block is not None:
                self._line("else")
                self.depth += 1
                self._block(statement.else_block)
                self.depth -= 1
            self._line("end")
            return
        if isinstance(statement, WhileStatement):
            self._line(f"while {render_expression(statement.condition)} do")
            self.depth += 1
            self._block(statement.body)
            self.depth -= 1
            self._line("end")
            return
        if isinstance(statement, RepeatStatement):
            self._line("repeat")
            self.depth += 1
            self._block(statement.body)
            self.depth -= 1
            self._line(f"until {render_expression(statement.condition)}")
            return
        if isinstance(statement, FunctionStatement):
            parameters = list(statement.parameters)
            if statement.vararg:
                parameters.append("...")
            prefix = "local " if statement.local else ""
            self._line(f"{prefix}function {statement.name}({', '.join(parameters)})")
            self.depth += 1
            self._block(statement.body)
            self.depth -= 1
            self._line("end")
            return
        raise TypeError(f"unsupported statement node: {type(statement).__name__}")

    def render(self, block: Block) -> str:
        self.lines.clear()
        self.depth = 0
        self._block(block)
        return "\n".join(self.lines).rstrip() + ("\n" if self.lines else "")
