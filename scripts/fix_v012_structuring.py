from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


structuring = ROOT / "src/lunaux/backends/structuring.py"
replace_once(
    structuring,
    "from dataclasses import dataclass\n",
    "from dataclasses import dataclass, replace\n",
)
replace_once(
    structuring,
    """class PhiIfRegion:\n    condition_pc: int\n    join_pc: int\n""",
    """class PhiIfRegion:\n    condition_pc: int\n    condition_pcs: tuple[int, ...]\n    condition_operator: Literal[\"and\", \"or\"] | None\n    join_pc: int\n""",
)
replace_once(
    structuring,
    """            PhiIfRegion(\n                condition_pc=header.terminator.pc,\n                join_pc=join,\n""",
    """            PhiIfRegion(\n                condition_pc=header.terminator.pc,\n                condition_pcs=(header.terminator.pc,),\n                condition_operator=None,\n                join_pc=join,\n""",
)
replace_once(
    structuring,
    """        block = analysis.block_by_start[candidate.header]\n        if len(block.predecessors) != 1 or not _condition_only(block):\n            break\n""",
    """        block = analysis.block_by_start[candidate.header]\n        reachable_predecessors = block.predecessors & analysis.reachable\n        if len(reachable_predecessors) != 1 or not _condition_only(block):\n            break\n""",
)
replace_once(
    structuring,
    """    condition_pcs = tuple(\n        analysis.block_by_start[item.header].terminator.pc\n        for item in conditions\n        if analysis.block_by_start[item.header].terminator is not None\n    )\n""",
    """    condition_pcs_list: list[int] = []\n    for item in conditions:\n        terminator = analysis.block_by_start[item.header].terminator\n        if terminator is None:\n            return None\n        condition_pcs_list.append(terminator.pc)\n    condition_pcs = tuple(condition_pcs_list)\n""",
)
replace_once(
    structuring,
    """        block = analysis.block_by_start[candidate.header]\n        if len(block.predecessors) != 1 or not _condition_only(block):\n            break\n        candidate_success, candidate_skipped = _follow_trivial_jump(\n""",
    """        block = analysis.block_by_start[candidate.header]\n        reachable_predecessors = block.predecessors & analysis.reachable\n        if len(reachable_predecessors) != 1 or not _condition_only(block):\n            break\n        candidate_success, candidate_skipped = _follow_trivial_jump(\n""",
)
replace_once(
    structuring,
    """    condition_pcs = tuple(\n        analysis.block_by_start[item.header].terminator.pc\n        for item in conditions\n        if analysis.block_by_start[item.header].terminator is not None\n    )\n""",
    """    condition_pcs_list: list[int] = []\n    for item in conditions:\n        terminator = analysis.block_by_start[item.header].terminator\n        if terminator is None:\n            return None\n        condition_pcs_list.append(terminator.pc)\n    condition_pcs = tuple(condition_pcs_list)\n""",
)
replace_once(
    structuring,
    """def _boolean_chains(\n    analysis: ControlFlowAnalysis,\n    excluded_condition_pcs: frozenset[int],\n) -> tuple[BooleanChain, ...]:\n    branch_by_header = {branch.header: branch for branch in analysis.branches}\n    chains: list[BooleanChain] = []\n    claimed: set[int] = set(excluded_condition_pcs)\n""",
    """def _boolean_chains(\n    analysis: ControlFlowAnalysis,\n) -> tuple[BooleanChain, ...]:\n    branch_by_header = {branch.header: branch for branch in analysis.branches}\n    chains: list[BooleanChain] = []\n    claimed: set[int] = set()\n""",
)
replace_once(
    structuring,
    """def build_structured_recovery(program: SSAProgram) -> StructuredRecoveryPlan:\n    phi_regions = _phi_regions(program)\n    phi_headers = frozenset(region.condition_pc for region in phi_regions)\n    boolean_chains = _boolean_chains(program.analysis, phi_headers)\n\n    phi_by_join: dict[int, list[PhiIfRegion]] = defaultdict(list)\n""",
    """def _merge_phi_condition_chains(\n    phi_regions: tuple[PhiIfRegion, ...],\n    boolean_chains: tuple[BooleanChain, ...],\n) -> tuple[tuple[PhiIfRegion, ...], tuple[BooleanChain, ...]]:\n    consumed_roots: set[int] = set()\n    merged_regions: list[PhiIfRegion] = []\n    for region in phi_regions:\n        matching = next(\n            (\n                chain\n                for chain in boolean_chains\n                if chain.condition_pcs[-1] == region.condition_pc\n                and chain.body_start == region.then_block\n                and chain.false_start == region.else_block\n                and chain.join == region.join_pc\n            ),\n            None,\n        )\n        if matching is None:\n            merged_regions.append(region)\n            continue\n        consumed_roots.add(matching.root_pc)\n        merged_regions.append(\n            replace(\n                region,\n                condition_pc=matching.root_pc,\n                condition_pcs=matching.condition_pcs,\n                condition_operator=matching.operator,\n                skipped_pcs=region.skipped_pcs | matching.skipped_pcs,\n            )\n        )\n    remaining_chains = tuple(\n        chain for chain in boolean_chains if chain.root_pc not in consumed_roots\n    )\n    return tuple(merged_regions), remaining_chains\n\n\ndef build_structured_recovery(program: SSAProgram) -> StructuredRecoveryPlan:\n    phi_regions = _phi_regions(program)\n    boolean_chains = _boolean_chains(program.analysis)\n    phi_regions, boolean_chains = _merge_phi_condition_chains(\n        phi_regions,\n        boolean_chains,\n    )\n\n    phi_by_join: dict[int, list[PhiIfRegion]] = defaultdict(list)\n""",
)

lifter = ROOT / "src/lunaux/backends/lifter.py"
replace_once(
    lifter,
    """        for region in self.if_else_regions.values():\n            structured_targets.add(region.else_pc)\n            structured_targets.add(region.end_pc)\n        for region in self.active_phi_headers.values():\n            structured_targets.add(region.then_block)\n            structured_targets.add(region.else_block)\n            structured_targets.add(region.join_pc)\n""",
    """        for if_region in self.if_else_regions.values():\n            structured_targets.add(if_region.else_pc)\n            structured_targets.add(if_region.end_pc)\n        for phi_region in self.active_phi_headers.values():\n            structured_targets.add(phi_region.then_block)\n            structured_targets.add(phi_region.else_block)\n            structured_targets.add(phi_region.join_pc)\n""",
)
replace_once(
    lifter,
    """            else:\n                rhs = source_expr(\n""",
    """            else:\n                rhs: Expr = source_expr(\n""",
)
replace_once(
    lifter,
    """            phi_region = self.active_phi_headers.get(pc)\n            if phi_region is not None and condition_expression is not None:\n                self.phi_conditions[pc] = condition_expression\n                return\n""",
    """            phi_region = self.active_phi_headers.get(pc)\n            if phi_region is not None:\n                if phi_region.condition_operator is not None:\n                    condition_expression = self._boolean_chain_expression(\n                        phi_region.condition_pcs,\n                        phi_region.condition_operator,\n                    )\n                if condition_expression is not None:\n                    self.phi_conditions[pc] = condition_expression\n                    return\n""",
)
