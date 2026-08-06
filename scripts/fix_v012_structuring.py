from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one match in {path}, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


lifter = ROOT / "src/lunaux/backends/lifter.py"
replace_once(
    lifter,
    """        for region in self.if_else_regions.values():
            structured_targets.add(region.else_pc)
            structured_targets.add(region.end_pc)
        for region in self.active_phi_headers.values():
            structured_targets.add(region.then_block)
            structured_targets.add(region.else_block)
            structured_targets.add(region.join_pc)
""",
    """        for if_region in self.if_else_regions.values():
            structured_targets.add(if_region.else_pc)
            structured_targets.add(if_region.end_pc)
        for phi_region in self.active_phi_headers.values():
            structured_targets.add(phi_region.then_block)
            structured_targets.add(phi_region.else_block)
            structured_targets.add(phi_region.join_pc)
""",
)
replace_once(
    lifter,
    """            else:
                rhs = source_expr(
""",
    """            else:
                rhs: Expr = source_expr(
""",
)
replace_once(
    lifter,
    """            phi_region = self.active_phi_headers.get(pc)
            if phi_region is not None and condition_expression is not None:
                self.phi_conditions[pc] = condition_expression
                return
""",
    """            phi_region = self.active_phi_headers.get(pc)
            if phi_region is not None:
                if phi_region.condition_operator is not None:
                    condition_expression = self._boolean_chain_expression(
                        phi_region.condition_pcs,
                        phi_region.condition_operator,
                    )
                if condition_expression is not None:
                    self.phi_conditions[pc] = condition_expression
                    return
""",
)
