from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DecompileOptions(BaseModel):
    """Formatting and reconstruction preferences passed to the backend.

    Both Python-style field names (``string_interpolation``) and the classic
    LunaUX API names (``StringInterpolation``) are accepted.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    semicolons: bool = Field(default=False, alias="Semicolons")
    string_interpolation: bool = Field(default=True, alias="StringInterpolation")
    upvalue_comment: bool = Field(default=True, alias="UpvalueComment")
    show_line_defined: bool = Field(default=True, alias="ShowLineDefined")
    show_function_id: bool = Field(default=False, alias="ShowFunctionId")
    preserve_for_step: bool = Field(default=False, alias="PreserveForStep")
    use_if_expression: bool = Field(default=True, alias="UseIfExpression")
    max_output_characters: int = Field(
        default=4_000_000,
        alias="MaxOutputCharacters",
        ge=1_000,
        le=20_000_000,
    )

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
