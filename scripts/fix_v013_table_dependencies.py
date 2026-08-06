from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "src/lunaux/backends/lifter.py"
text = PATH.read_text(encoding="utf-8")

if "def _dependencies_for_value(" in text:
    print("v0.13 table dependency correction already applied")
    raise SystemExit(0)

marker = '''    def _capture_register_expression(
        self,
        owner: PendingTableLiteral,
'''
methods = '''    def _dependencies_for_value(
        self,
        value: SSAValue,
        seen: frozenset[SSAValue] = frozenset(),
    ) -> frozenset[SSAValue]:
        if value in seen or value.kind != "instruction":
            return frozenset({value})
        if value not in self.inline_expressions or value.origin_pc is None:
            return frozenset({value})
        instruction = self.ssa.instruction_at(value.origin_pc)
        if instruction is None:
            return frozenset({value})
        dependencies: set[SSAValue] = set()
        next_seen = seen | frozenset({value})
        for use in instruction.uses:
            dependencies.update(
                self._dependencies_for_value(use.value, next_seen)
            )
        return frozenset(dependencies)

    def _table_value_can_inline(
        self,
        child: PendingTableLiteral,
        consumer_pc: int,
    ) -> bool:
        accounted_uses = 0
        for ssa_instruction in self.ssa.instructions.values():
            matching_uses = tuple(
                use
                for use in ssa_instruction.uses
                if use.value == child.value
            )
            if not matching_uses:
                continue
            accounted_uses += len(matching_uses)
            instruction = ssa_instruction.instruction
            target = table_write_target_register(instruction)
            if instruction.pc == consumer_pc:
                if (
                    not is_table_write(instruction)
                    or child.register
                    not in table_write_source_registers(instruction)
                ):
                    return False
                continue
            if (
                not is_table_write(instruction)
                or target != child.register
                or self.ssa.value_at_use(instruction.pc, target) != child.value
            ):
                return False
        return accounted_uses == self.ssa.uses_of(child.value)

'''
if text.count(marker) != 1:
    raise RuntimeError(f"capture marker count is {text.count(marker)}")
text = text.replace(marker, methods + marker, 1)

old_inline = '''                and value is not None
                and self.ssa.uses_of(value) == 1
                and owner.can_adopt(child)
'''
new_inline = '''                and value is not None
                and self._table_value_can_inline(child, pc)
                and owner.can_adopt(child)
'''
if text.count(old_inline) != 1:
    raise RuntimeError(f"nested-use condition count is {text.count(old_inline)}")
text = text.replace(old_inline, new_inline, 1)

old_dependencies = '''        expression = self._ref_expr(register, pc)
        dependencies = frozenset({value}) if value is not None else frozenset()
        return expression, dependencies
'''
new_dependencies = '''        expression = self._ref_expr(register, pc)
        dependencies = (
            self._dependencies_for_value(value)
            if value is not None
            else frozenset()
        )
        return expression, dependencies
'''
if text.count(old_dependencies) != 1:
    raise RuntimeError(f"dependency block count is {text.count(old_dependencies)}")
text = text.replace(old_dependencies, new_dependencies, 1)

PATH.write_text(text, encoding="utf-8")
print("corrected v0.13 table dependencies and nested ownership")
