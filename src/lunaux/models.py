from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DecompileOptions(BaseModel):
    """Formatting and reconstruction preferences passed to the backend."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    semicolons: bool = False
    string_interpolation: bool = True
    upvalue_comment: bool = True
    show_line_defined: bool = True
    show_function_id: bool = False
    preserve_for_step: bool = False
    use_if_expression: bool = True
    max_output_characters: int = Field(default=4_000_000, ge=1_000, le=20_000_000)

    def to_backend_dict(self) -> dict[str, bool]:
        return {
            "Semicolons": self.semicolons,
            "StringInterpolation": self.string_interpolation,
            "UpvalueComment": self.upvalue_comment,
            "ShowLineDefined": self.show_line_defined,
            "ShowFunctionId": self.show_function_id,
            "PreserveForStep": self.preserve_for_step,
            "UseIfExpression": self.use_if_expression,
        }
