from __future__ import annotations

from lunaux.backends.ast import (
    Assignment,
    BinaryExpr,
    Block,
    CallExpr,
    FieldExpr,
    FunctionStatement,
    IfStatement,
    IndexExpr,
    LiteralExpr,
    LuauPrinter,
    MethodCallExpr,
    NameExpr,
    RawStatement,
    ReturnStatement,
    UnaryExpr,
    render_expression,
    source_expr,
)


def name(value: str) -> NameExpr:
    return NameExpr(value)


def test_binary_precedence_avoids_redundant_parentheses() -> None:
    expression = BinaryExpr(
        name("a"),
        "+",
        BinaryExpr(name("b"), "*", name("c")),
    )

    assert render_expression(expression) == "a + b * c"


def test_binary_precedence_preserves_grouping() -> None:
    expression = BinaryExpr(
        BinaryExpr(name("a"), "+", name("b")),
        "*",
        name("c"),
    )

    assert render_expression(expression) == "(a + b) * c"


def test_left_associative_right_child_is_parenthesized() -> None:
    expression = BinaryExpr(
        name("a"),
        "-",
        BinaryExpr(name("b"), "-", name("c")),
    )

    assert render_expression(expression) == "a - (b - c)"


def test_power_is_right_associative() -> None:
    natural = BinaryExpr(
        name("a"),
        "^",
        BinaryExpr(name("b"), "^", name("c")),
    )
    forced_left = BinaryExpr(
        BinaryExpr(name("a"), "^", name("b")),
        "^",
        name("c"),
    )

    assert render_expression(natural) == "a ^ b ^ c"
    assert render_expression(forced_left) == "(a ^ b) ^ c"


def test_unary_and_power_follow_luau_precedence() -> None:
    negative_power = UnaryExpr("-", BinaryExpr(name("x"), "^", LiteralExpr("2")))
    powered_negative = BinaryExpr(UnaryExpr("-", name("x")), "^", LiteralExpr("2"))

    assert render_expression(negative_power) == "-x ^ 2"
    assert render_expression(powered_negative) == "(-x) ^ 2"


def test_postfix_nodes_parenthesize_complex_bases() -> None:
    base = BinaryExpr(name("left"), "or", name("right"))
    field = FieldExpr(base, "value")
    index = IndexExpr(base, LiteralExpr("1"))
    call = CallExpr(base, (LiteralExpr("42"),))

    assert render_expression(field) == "(left or right).value"
    assert render_expression(index) == "(left or right)[1]"
    assert render_expression(call) == "(left or right)(42)"


def test_method_call_prints_colon_syntax() -> None:
    expression = MethodCallExpr(name("object"), "run", (name("argument"),))

    assert render_expression(expression) == "object:run(argument)"


def test_source_expr_classifies_atomic_values() -> None:
    assert source_expr("value") == NameExpr("value")
    assert source_expr("42") == LiteralExpr("42")
    assert source_expr("true") == LiteralExpr("true")


def test_statement_printer_renders_nested_blocks() -> None:
    program = Block(
        (
            Assignment((name("answer"),), (LiteralExpr("42"),), local=True),
            IfStatement(
                BinaryExpr(name("answer"), ">", LiteralExpr("0")),
                Block((ReturnStatement((name("answer"),)),)),
                Block((RawStatement("error(\"invalid\")"),)),
            ),
        )
    )

    assert LuauPrinter().render(program) == (
        "local answer = 42\n"
        "if answer > 0 then\n"
        "    return answer\n"
        "else\n"
        "    error(\"invalid\")\n"
        "end\n"
    )


def test_function_printer_supports_varargs_and_semicolons() -> None:
    program = Block(
        (
            FunctionStatement(
                "collect",
                ("first",),
                Block((ReturnStatement((name("first"),)),)),
                vararg=True,
            ),
        )
    )

    assert LuauPrinter(semicolons=True).render(program) == (
        "local function collect(first, ...)\n"
        "    return first;\n"
        "end\n"
    )


def test_nested_unary_never_becomes_a_comment() -> None:
    expression = UnaryExpr("-", UnaryExpr("-", name("value")))

    assert render_expression(expression) == "-(-value)"
