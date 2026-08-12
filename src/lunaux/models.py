from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DecompileOptions(BaseModel):
    """Formatting and reconstruction preferences passed to the backend.

    Both Python-style field names (``string_interpolation``) and the classic
    Legacy API names (``StringInterpolation``) are accepted.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    include_header: bool = Field(default=True, alias="IncludeHeader")
    semicolons: bool = Field(default=False, alias="Semicolons")
    string_interpolation: bool = Field(default=True, alias="StringInterpolation")
    upvalue_comment: bool = Field(default=True, alias="UpvalueComment")
    show_line_defined: bool = Field(default=True, alias="ShowLineDefined")
    show_function_id: bool = Field(default=False, alias="ShowFunctionId")
    preserve_for_step: bool = Field(default=False, alias="PreserveForStep")
    use_if_expression: bool = Field(default=True, alias="UseIfExpression")
    recover_phi_expressions: bool = Field(
        default=True,
        alias="RecoverPhiExpressions",
    )
    combine_boolean_conditions: bool = Field(
        default=True,
        alias="CombineBooleanConditions",
    )
    advanced_loops: bool = Field(default=True, alias="AdvancedLoops")
    unflatten_state_machines: bool = Field(
        default=True,
        alias="UnflattenStateMachines",
    )
    reconstruct_table_literals: bool = Field(
        default=True,
        alias="ReconstructTableLiterals",
    )
    inline_single_use_temporaries: bool = Field(
        default=True,
        alias="InlineSingleUseTemporaries",
    )
    smart_variable_names: bool = Field(default=True, alias="SmartVariableNames")
    infer_types: bool = Field(default=True, alias="InferTypes")
    flow_sensitive_types: bool = Field(
        default=True,
        alias="FlowSensitiveTypes",
    )
    roblox_api_types: bool = Field(
        default=True,
        alias="RobloxAPITypes",
    )
    contextual_functions: bool = Field(
        default=True,
        alias="ContextualFunctions",
    )
    show_recovered_symbols: bool = Field(
        default=False,
        alias="ShowRecoveredSymbols",
    )
    recover_roblox_events: bool = Field(
        default=True,
        alias="RecoverRobloxEvents",
    )
    inline_roblox_callbacks: bool = Field(
        default=True,
        alias="InlineRobloxCallbacks",
    )
    recover_roblox_modules: bool = Field(
        default=True,
        alias="RecoverRobloxModules",
    )
    recover_classes: bool = Field(default=True, alias="RecoverClasses")
    recover_metatable_classes: bool = Field(
        default=True,
        alias="RecoverMetatableClasses",
    )
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
            "RecoverPhiExpressions": self.recover_phi_expressions,
            "CombineBooleanConditions": self.combine_boolean_conditions,
            "AdvancedLoops": self.advanced_loops,
            "UnflattenStateMachines": self.unflatten_state_machines,
            "ReconstructTableLiterals": self.reconstruct_table_literals,
            "InlineSingleUseTemporaries": self.inline_single_use_temporaries,
            "SmartVariableNames": self.smart_variable_names,
            "InferTypes": self.infer_types,
            "FlowSensitiveTypes": self.flow_sensitive_types,
            "RobloxAPITypes": self.roblox_api_types,
            "ContextualFunctions": self.contextual_functions,
            "ShowRecoveredSymbols": self.show_recovered_symbols,
            "RecoverRobloxEvents": self.recover_roblox_events,
            "InlineRobloxCallbacks": self.inline_roblox_callbacks,
            "RecoverRobloxModules": self.recover_roblox_modules,
            "RecoverClasses": self.recover_classes,
            "RecoverMetatableClasses": self.recover_metatable_classes,
        }
