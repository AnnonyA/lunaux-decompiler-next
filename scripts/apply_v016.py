from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing marker: {label}")
    return text.replace(old, new, 1)


path = Path("src/lunaux/backends/lifter.py")
text = path.read_text(encoding="utf-8")

text = replace_once(
    text,
    "from lunaux.backends.classes import recover_classes\n",
    '''from lunaux.backends.classes import (
    ClassRecoveryPlan,
    collect_class_method_proto_ids,
    recover_classes,
)
from lunaux.backends.contextual_functions import (
    collect_module_function_contexts,
    plan_contextual_functions,
)
''',
    "lifter imports",
)

text = replace_once(
    text,
    '''    flow_sensitive_types: bool
    roblox_api_types: bool
    show_recovered_symbols: bool
''',
    '''    flow_sensitive_types: bool
    roblox_api_types: bool
    contextual_functions: bool
    show_recovered_symbols: bool
''',
    "contextual option field",
)
text = replace_once(
    text,
    '''    recover_roblox_modules: bool
    recover_classes: bool
''',
    '''    recover_roblox_modules: bool
    recover_classes: bool
    recover_metatable_classes: bool
''',
    "metatable option field",
)
text = replace_once(
    text,
    '''            flow_sensitive_types=options.get("FlowSensitiveTypes", True),
            roblox_api_types=options.get("RobloxAPITypes", True),
            show_recovered_symbols=options.get(
''',
    '''            flow_sensitive_types=options.get("FlowSensitiveTypes", True),
            roblox_api_types=options.get("RobloxAPITypes", True),
            contextual_functions=options.get("ContextualFunctions", True),
            show_recovered_symbols=options.get(
''',
    "contextual option parsing",
)
text = replace_once(
    text,
    '''            recover_roblox_modules=options.get("RecoverRobloxModules", True),
            recover_classes=options.get("RecoverClasses", True),
''',
    '''            recover_roblox_modules=options.get("RecoverRobloxModules", True),
            recover_classes=options.get("RecoverClasses", True),
            recover_metatable_classes=options.get("RecoverMetatableClasses", True),
''',
    "metatable option parsing",
)

text = replace_once(
    text,
    '''        upvalue_bindings: dict[int, Expr] | None = None,
        parameter_type_overrides: dict[int, str] | None = None,
    ) -> None:
''',
    '''        upvalue_bindings: dict[int, Expr] | None = None,
        parameter_name_overrides: dict[int, str] | None = None,
        parameter_type_overrides: dict[int, str] | None = None,
        return_type_override: str | None = None,
    ) -> None:
''',
    "function lifter signature",
)
text = replace_once(
    text,
    '''        self.upvalue_bindings = upvalue_bindings or {}
        self.parameter_type_overrides = parameter_type_overrides or {}
        self.scope_tree = build_scope_tree(proto)
''',
    '''        self.upvalue_bindings = upvalue_bindings or {}
        self.parameter_name_overrides = parameter_name_overrides or {}
        self.parameter_type_overrides = parameter_type_overrides or {}
        self.return_type_override = return_type_override
        self.scope_tree = build_scope_tree(proto)
''',
    "context override state",
)

old_class_plan = '''        self.class_plan = recover_classes(
            module,
            proto,
            self.instructions,
            self.ssa,
        )
        self.inline_plan = plan_expression_inlining(self.ssa, proto)
'''
new_class_plan = '''        self.class_plan = (
            recover_classes(
                module,
                proto,
                self.instructions,
                self.ssa,
                recover_metatable_classes=options.recover_metatable_classes,
            )
            if options.recover_classes
            else ClassRecoveryPlan.empty()
        )
        self.contextual_plan = plan_contextual_functions(
            module,
            proto,
            self.instructions,
            self.ssa,
            self.class_plan,
            callback_plan=self.callback_plan,
            enabled=options.contextual_functions,
        )
        self.inline_plan = plan_expression_inlining(self.ssa, proto)
'''
text = replace_once(text, old_class_plan, new_class_plan, "class/context plans")

old_callback = '''        callback_types = (
            self.callback_plan.parameter_types_by_value.get(closure_value, ())
            if closure_value is not None
            else ()
        )
        parameter_type_overrides = {
            index: type_name
            for index, type_name in enumerate(callback_types)
            if index < child.num_params and not type_name.startswith("...")
        }
'''
new_callback = '''        callback_types = (
            self.callback_plan.parameter_types_by_value.get(closure_value, ())
            if closure_value is not None and self.options.roblox_api_types
            else ()
        )
        context = self.contextual_plan.for_value(closure_value)
        parameter_name_overrides = dict(context.parameter_names) if context is not None else {}
        parameter_type_overrides = {
            index: type_name
            for index, type_name in enumerate(callback_types)
            if index < child.num_params and not type_name.startswith("...")
        }
        if context is not None:
            parameter_type_overrides.update(context.parameter_types)
'''
text = replace_once(text, old_callback, new_callback, "anonymous callback context")
text = replace_once(
    text,
    '''            upvalue_bindings=bindings,
            parameter_type_overrides=parameter_type_overrides,
        ).lift(as_function=True, anonymous_function=True)
''',
    '''            upvalue_bindings=bindings,
            parameter_name_overrides=parameter_name_overrides,
            parameter_type_overrides=parameter_type_overrides,
            return_type_override=context.return_type if context is not None else None,
        ).lift(as_function=True, anonymous_function=True)
''',
    "anonymous callback overrides",
)

text = replace_once(
    text,
    '''        if type_name is None and pc == 0 and self.options.roblox_api_types:
            type_name = self.parameter_type_overrides.get(register)
''',
    '''        if type_name is None and pc == 0:
            type_name = self.parameter_type_overrides.get(register)
''',
    "parameter type override gate",
)

text = replace_once(
    text,
    '''            recovered_name = (
                self.symbols.entry_names.get(register)
                if self.options.smart_variable_names and self.symbols is not None
                else None
            )
            name = _local_name(self.proto, register, 0) or recovered_name or f"arg{register + 1}"
''',
    '''            recovered_name = (
                self.symbols.entry_names.get(register)
                if self.options.smart_variable_names and self.symbols is not None
                else None
            )
            contextual_name = self.parameter_name_overrides.get(register)
            name = (
                _local_name(self.proto, register, 0)
                or contextual_name
                or recovered_name
                or f"arg{register + 1}"
            )
''',
    "parameter names",
)

old_return = '''            if (
                self.options.infer_types
                and self.symbols is not None
                and self.symbols.return_type
                and self.symbols.return_type != "any"
            ):
                header += f": {self.symbols.return_type}"
'''
new_return = '''            if self.options.infer_types:
                return_type = self.return_type_override
                if (
                    return_type is None
                    and self.symbols is not None
                    and self.symbols.return_type
                ):
                    return_type = self.symbols.return_type
                if return_type and return_type != "any":
                    header += f": {return_type}"
'''
text = replace_once(text, old_return, new_return, "function return override")

start = text.index("    def _emit_recovered_class(self, instruction: DecodedInstruction) -> bool:\n")
end = text.index("    def _lift_instruction(self, instruction: DecodedInstruction) -> None:\n", start)
new_emitter = '''    def _emit_recovered_class(self, instruction: DecodedInstruction) -> bool:
        declaration = self.class_plan.at(instruction.pc)
        if declaration is None:
            return False
        class_name = _sanitize_identifier(declaration.name, "AnonymousClass")
        self.register_names[instruction.a] = class_name
        self.declared.add(class_name)
        self.out.open(f"class {class_name}")
        if declaration.source_kind == "metatable":
            self.out.line("-- recovered from metatable __index pattern")
        if declaration.superclass_register is not None:
            superclass = self._ref(declaration.superclass_register, instruction.pc)
            self.out.line(f"-- superclass: {superclass}")
        elif declaration.superclass_name is not None:
            self.out.line(f"-- superclass: {declaration.superclass_name}")
        for property_name in declaration.properties:
            property_name = _sanitize_identifier(property_name, "property")
            self.out.line(f"public {property_name}")
        if declaration.properties and declaration.methods:
            self.out.line()
        for method in declaration.methods:
            method_name = _sanitize_identifier(method.name, "method")
            if method.proto_id is None:
                self.out.line(f"-- unresolved method {method_name}")
                continue
            if method.kind == "constructor":
                self.out.line("-- constructor")
            elif method.kind == "static_method":
                self.out.line("-- static method")
            elif method.kind == "metamethod":
                self.out.line("-- metamethod")
            child = self.module.protos[method.proto_id]
            _FunctionLifter(
                self.module,
                child,
                self.proto_names,
                self.options,
                self.out,
                inline_only_proto_ids=self.inline_only_proto_ids,
                parameter_name_overrides=dict(method.parameter_names),
                parameter_type_overrides=dict(method.parameter_types),
                return_type_override=method.return_type,
            ).lift(
                as_function=True,
                function_name_override=method_name,
                local_function=False,
            )
        self.out.close()
        return True

'''
text = text[:start] + new_emitter + text[end:]

text = replace_once(
    text,
    '''        expression: Expr | str
        if (
            self.options.reconstruct_table_literals
''',
    '''        expression: Expr | str
        if (
            name in {"NEWTABLE", "DUPTABLE"}
            and self.options.recover_classes
            and self._emit_recovered_class(instruction)
        ):
            return
        if (
            self.options.reconstruct_table_literals
''',
    "metatable class emission",
)

text = replace_once(
    text,
    '''    inline_only_proto_ids = collect_inline_only_proto_ids(
        module,
        enabled=resolved.inline_roblox_callbacks,
    )
    main_instructions = tuple(decode_words(module.main_proto.code))
''',
    '''    inline_only_proto_ids = collect_inline_only_proto_ids(
        module,
        enabled=resolved.inline_roblox_callbacks,
    )
    class_method_proto_ids = (
        collect_class_method_proto_ids(
            module,
            recover_metatable_classes=resolved.recover_metatable_classes,
        )
        if resolved.recover_classes
        else frozenset()
    )
    contextual_contexts = collect_module_function_contexts(
        module,
        recover_metatable_classes=resolved.recover_metatable_classes,
        enabled=resolved.contextual_functions,
    )
    main_instructions = tuple(decode_words(module.main_proto.code))
''',
    "module context collection",
)

old_loop = '''    for proto in module.protos:
        if proto.proto_id == module.main_proto_id or proto.proto_id in inline_only_proto_ids:
            continue
        _FunctionLifter(
            module,
            proto,
            names,
            resolved,
            out,
            inline_only_proto_ids=inline_only_proto_ids,
        ).lift(as_function=True)
'''
new_loop = '''    for proto in module.protos:
        if (
            proto.proto_id == module.main_proto_id
            or proto.proto_id in inline_only_proto_ids
            or proto.proto_id in class_method_proto_ids
        ):
            continue
        context = contextual_contexts.get(proto.proto_id)
        _FunctionLifter(
            module,
            proto,
            names,
            resolved,
            out,
            inline_only_proto_ids=inline_only_proto_ids,
            parameter_name_overrides=(
                dict(context.parameter_names) if context is not None else None
            ),
            parameter_type_overrides=(
                dict(context.parameter_types) if context is not None else None
            ),
            return_type_override=context.return_type if context is not None else None,
        ).lift(
            as_function=True,
            function_name_override=(
                _sanitize_identifier(context.name, names[proto.proto_id])
                if context is not None
                else None
            ),
            local_function=context is None or context.kind != "global",
        )
'''
text = replace_once(text, old_loop, new_loop, "module prototype loop")

path.write_text(text, encoding="utf-8")
