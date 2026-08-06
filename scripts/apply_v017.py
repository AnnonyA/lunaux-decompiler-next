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
    "from lunaux.backends.analysis import analyze_control_flow\n",
    '''from lunaux.backends.advanced_loops import (
    AdvancedLoopRegion,
    LoopJumpAction,
    analyze_advanced_loops,
)
from lunaux.backends.analysis import analyze_control_flow
''',
    "advanced loop imports",
)
text = replace_once(
    text,
    "from lunaux.backends.ssa import SSAValue, build_ssa\n",
    '''from lunaux.backends.ssa import SSAValue, build_ssa
from lunaux.backends.state_machine import StateMachineRegion, recover_state_machines
''',
    "state machine imports",
)

text = replace_once(
    text,
    '''    recover_phi_expressions: bool
    combine_boolean_conditions: bool
    reconstruct_table_literals: bool
''',
    '''    recover_phi_expressions: bool
    combine_boolean_conditions: bool
    advanced_loops: bool
    unflatten_state_machines: bool
    reconstruct_table_literals: bool
''',
    "option fields",
)
text = replace_once(
    text,
    '''            combine_boolean_conditions=options.get(
                "CombineBooleanConditions",
                True,
            ),
            reconstruct_table_literals=options.get(
''',
    '''            combine_boolean_conditions=options.get(
                "CombineBooleanConditions",
                True,
            ),
            advanced_loops=options.get("AdvancedLoops", True),
            unflatten_state_machines=options.get("UnflattenStateMachines", True),
            reconstruct_table_literals=options.get(
''',
    "option parsing",
)

text = replace_once(
    text,
    '''        self.callback_expressions: dict[SSAValue, Expr] = {}
        self.callback_dependencies: dict[SSAValue, frozenset[SSAValue]] = {}
        self.structured_plan = build_structured_recovery(self.ssa)
''',
    '''        self.callback_expressions: dict[SSAValue, Expr] = {}
        self.callback_dependencies: dict[SSAValue, frozenset[SSAValue]] = {}
        self.state_machine_plan = recover_state_machines(
            proto,
            self.instructions,
            self.analysis,
            enabled=options.unflatten_state_machines,
        )
        self.advanced_loop_plan = analyze_advanced_loops(
            self.analysis,
            self.instructions,
            enabled=options.advanced_loops,
        )
        self.structured_plan = build_structured_recovery(self.ssa)
''',
    "control flow plans",
)

text = replace_once(
    text,
    '''        self._analyze_control_flow()
        self._analyze_cfg_regions()
        loop_condition_pcs = set(self.while_headers) | set(self.repeat_conditions)
        phi_enabled = options.use_if_expression and options.recover_phi_expressions
        self.active_phi_headers = dict(self.structured_plan.phi_by_header) if phi_enabled else {}
        self.active_phi_joins = dict(self.structured_plan.phi_by_join) if phi_enabled else {}
''',
    '''        self._analyze_control_flow()
        self._analyze_cfg_regions()
        machine_pcs = self.state_machine_plan.skipped_pcs
        self.active_advanced_loops = {
            pc: region
            for pc, region in self.advanced_loop_plan.by_open_pc.items()
            if not (machine_pcs & {
                instruction.pc
                for block_start in region.body_blocks
                for instruction in self.analysis.block_by_start[block_start].instructions
            })
        }
        self.active_advanced_repeat_conditions = {
            pc: region
            for pc, region in self.advanced_loop_plan.repeat_by_condition_pc.items()
            if region.header in self.active_advanced_loops
        }
        active_loop_headers = set(self.active_advanced_loops)
        self.active_loop_actions = {
            pc: action
            for pc, action in self.advanced_loop_plan.actions.items()
            if action.loop_header in active_loop_headers and pc not in machine_pcs
        }
        self.active_loop_skip_pcs = {
            pc
            for pc in self.advanced_loop_plan.skipped_pcs
            if pc not in machine_pcs
            and any(
                pc in region.backedge_pcs
                for region in self.active_advanced_loops.values()
            )
        }
        loop_condition_pcs = (
            set(self.while_headers)
            | set(self.repeat_conditions)
            | {
                region.condition_pc
                for region in self.active_advanced_loops.values()
                if region.condition_pc is not None
            }
        )
        phi_enabled = options.use_if_expression and options.recover_phi_expressions
        self.active_phi_headers = (
            {
                pc: region
                for pc, region in self.structured_plan.phi_by_header.items()
                if not (region.skipped_pcs & machine_pcs)
            }
            if phi_enabled
            else {}
        )
        self.active_phi_joins = (
            {
                join: tuple(
                    region
                    for region in regions
                    if region.condition_pc in self.active_phi_headers
                )
                for join, regions in self.structured_plan.phi_by_join.items()
                if any(region.condition_pc in self.active_phi_headers for region in regions)
            }
            if phi_enabled
            else {}
        )
''',
    "active control flow plans",
)

text = replace_once(
    text,
    '''                if not (set(chain.condition_pcs) & loop_condition_pcs)
''',
    '''                if not (set(chain.condition_pcs) & loop_condition_pcs)
                and not (set(chain.condition_pcs) & machine_pcs)
''',
    "boolean machine exclusion",
)

text = replace_once(
    text,
    '''        structured_targets = set(self.while_headers)
        structured_targets.update(self.repeat_starts)
''',
    '''        structured_targets = set(self.while_headers)
        structured_targets.update(self.repeat_starts)
        structured_targets.update(self.advanced_loop_plan.structured_targets)
        structured_targets.update(self.state_machine_plan.structured_targets)
''',
    "structured label targets",
)
text = replace_once(
    text,
    '''        for instruction in self.instructions:
            target = get_jump_target(instruction)
''',
    '''        for instruction in self.instructions:
            if instruction.pc in self.state_machine_plan.skipped_pcs:
                continue
            target = get_jump_target(instruction)
''',
    "skip machine labels",
)

old_open_loop = '''    def _open_structured_loop(self, instruction: DecodedInstruction) -> bool:
        if instruction.pc in self.repeat_starts:
            self.out.open("repeat")
        if instruction.pc not in self.while_headers:
            return False
        end_pc, condition_instruction = self.while_headers[instruction.pc]
        condition = self._conditional_body(condition_instruction)
        if condition is None:
            return False
        self.out.open(f"while {condition} do")
        self.block_closures[end_pc].append("end")
        return True
'''
new_open_loop = '''    def _open_structured_loop(self, instruction: DecodedInstruction) -> bool:
        advanced = self.active_advanced_loops.get(instruction.pc)
        if advanced is not None:
            if advanced.kind == "repeat":
                self.out.open("repeat")
                return True
            if advanced.kind == "infinite":
                self.out.open("while true do")
                self.block_closures[advanced.close_pc].append("end")
                return True
            condition_instruction = (
                self.instruction_by_pc.get(advanced.condition_pc)
                if advanced.condition_pc is not None
                else None
            )
            condition = (
                self._conditional_body(condition_instruction)
                if condition_instruction is not None
                else None
            )
            if condition is None:
                return False
            self.out.open(f"while {condition} do")
            self.block_closures[advanced.close_pc].append("end")
            return True

        if instruction.pc in self.repeat_starts:
            self.out.open("repeat")
        if instruction.pc not in self.while_headers:
            return False
        end_pc, condition_instruction = self.while_headers[instruction.pc]
        condition = self._conditional_body(condition_instruction)
        if condition is None:
            return False
        self.out.open(f"while {condition} do")
        self.block_closures[end_pc].append("end")
        return True

    def _emit_loop_action(
        self,
        instruction: DecodedInstruction,
        action: LoopJumpAction,
    ) -> None:
        if action.edge == "always":
            self.out.line(action.kind, statement=True)
            return
        condition = self._conditional_expr(instruction)
        if condition is None:
            self.out.line(
                f"-- unresolved {action.kind} edge to L{action.target:04d}"
            )
            return
        if action.edge == "taken":
            condition = UnaryExpr("not", condition)
        self.out.open(f"if {render_expression(condition)} then")
        self.out.line(action.kind, statement=True)
        self.out.close()

    def _emit_state_machine(self, region: StateMachineRegion) -> None:
        self.out.line(
            f"-- unflattened state machine R{region.state_register}; "
            f"initial={region.initial_state!r}"
        )
        if region.kind == "cycle":
            self.out.open("while true do")
        for case in region.cases:
            for pc in case.body_pcs:
                instruction = self.instruction_by_pc.get(pc)
                if instruction is None:
                    continue
                self._flush_tables_before(instruction)
                if instruction.pc in self.callback_plan.capture_pcs:
                    continue
                if instruction.pc in self.class_plan.skipped_instruction_pcs:
                    continue
                self._lift_instruction(instruction)
        if region.kind == "cycle":
            self.out.close()
'''
text = replace_once(text, old_open_loop, new_open_loop, "advanced loop emitter")

text = replace_once(
    text,
    '''            self._close_blocks(instruction.pc)
            opened_loop = self._open_structured_loop(instruction)
            if instruction.pc in self.labels:
''',
    '''            self._close_blocks(instruction.pc)
            state_machine = self.state_machine_plan.at(instruction.pc)
            if state_machine is not None:
                self._emit_state_machine(state_machine)
                continue
            if instruction.pc in self.state_machine_plan.skipped_pcs:
                continue
            opened_loop = self._open_structured_loop(instruction)
            if instruction.pc in self.labels:
''',
    "state machine lift hook",
)
text = replace_once(
    text,
    '''            if instruction.pc in self.repeat_conditions:
                condition = self._conditional_body(instruction)
                self.out.close(f"until {condition or 'false'}")
                continue
            if instruction.pc in self.while_back_pcs:
                continue
''',
    '''            advanced_repeat = self.active_advanced_repeat_conditions.get(instruction.pc)
            if advanced_repeat is not None:
                condition = self._conditional_body(instruction)
                self.out.close(f"until {condition or 'false'}")
                continue
            if instruction.pc in self.repeat_conditions:
                condition = self._conditional_body(instruction)
                self.out.close(f"until {condition or 'false'}")
                continue
            if instruction.pc in self.active_loop_skip_pcs:
                continue
            if instruction.pc in self.while_back_pcs:
                continue
''',
    "advanced loop close and skips",
)

text = replace_once(
    text,
    '''        name = instruction.name
        pc = instruction.pc
        expression: Expr | str
''',
    '''        name = instruction.name
        pc = instruction.pc
        expression: Expr | str
        loop_action = self.active_loop_actions.get(pc)
        if loop_action is not None:
            self._emit_loop_action(instruction, loop_action)
            return
''',
    "loop jump actions",
)

path.write_text(text, encoding="utf-8")
