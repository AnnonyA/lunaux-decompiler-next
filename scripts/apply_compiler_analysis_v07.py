from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path!r}, found {text.count(old)}"
        )
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "src/lunaux/backends/analysis.py",
        "from collections import defaultdict\n"
        "from dataclasses import dataclass\n"
        "from types import MappingProxyType\n"
        "from typing import Mapping\n",
        "from collections import defaultdict\n"
        "from collections.abc import Mapping\n"
        "from dataclasses import dataclass\n"
        "from types import MappingProxyType\n",
    )
    replace_once(
        "src/lunaux/backends/analysis.py",
        "    result = {node: set() for node in nodes}\n",
        "    result: dict[int, set[int]] = {node: set() for node in nodes}\n",
    )
    replace_once(
        "src/lunaux/backends/analysis.py",
        "    live_in = {block.start_pc: set() for block in blocks}\n"
        "    live_out = {block.start_pc: set() for block in blocks}\n",
        "    live_in: dict[int, set[int]] = {\n"
        "        block.start_pc: set() for block in blocks\n"
        "    }\n"
        "    live_out: dict[int, set[int]] = {\n"
        "        block.start_pc: set() for block in blocks\n"
        "    }\n",
    )
    replace_once(
        "src/lunaux/backends/__init__.py",
        "    \"DefUseChain\",\n"
        "    \"NaturalLoop\",\n"
        "    \"NativeModuleBackend\",\n",
        "    \"DefUseChain\",\n"
        "    \"NativeModuleBackend\",\n"
        "    \"NaturalLoop\",\n",
    )
    replace_once(
        "src/lunaux/backends/lifter.py",
        "from lunaux.backends.bytecode import (\n",
        "from lunaux.backends.analysis import analyze_control_flow\n"
        "from lunaux.backends.bytecode import (\n",
    )
    replace_once(
        "src/lunaux/backends/lifter.py",
        "        self.instructions = list(decode_words(proto.code))\n"
        "        self.instruction_by_pc = {\n",
        "        self.instructions = list(decode_words(proto.code))\n"
        "        self.analysis = analyze_control_flow(self.instructions, len(proto.code))\n"
        "        self.instruction_by_pc = {\n",
    )
    replace_once(
        "src/lunaux/backends/lifter.py",
        "        self._analyze_control_flow()\n"
        "        self.labels = self._collect_labels()\n",
        "        self._analyze_control_flow()\n"
        "        self._analyze_cfg_regions()\n"
        "        self.labels = self._collect_labels()\n",
    )
    replace_once(
        "src/lunaux/backends/lifter.py",
        "    def _collect_labels(self) -> set[int]:\n",
        '''    def _analyze_cfg_regions(self) -> None:
        for loop in self.analysis.loops:
            header_block = self.analysis.block_by_start[loop.header]
            latch_block = self.analysis.block_by_start[loop.latch]
            header = header_block.terminator
            latch = latch_block.terminator
            if header is None or latch is None:
                continue

            if (
                header.name in _CONDITIONAL_OPS
                and latch.name in {"JUMP", "JUMPBACK", "JUMPX"}
            ):
                exits = sorted(
                    target
                    for source, target in loop.exits
                    if source == loop.header
                )
                if exits:
                    self.while_headers.setdefault(
                        header.pc,
                        (exits[0], header),
                    )
                    self.while_back_pcs.add(latch.pc)

            if (
                latch.name in _CONDITIONAL_OPS
                and get_jump_target(latch) == loop.header
            ):
                self.repeat_starts.setdefault(loop.header, latch.pc)
                self.repeat_conditions.setdefault(latch.pc, latch)

        for branch in self.analysis.branches:
            header_block = self.analysis.block_by_start[branch.header]
            condition = header_block.terminator
            join = branch.join
            if (
                condition is None
                or condition.name not in _CONDITIONAL_OPS
                or join is None
                or branch.taken <= condition.pc
                or condition.pc in self.while_headers
                or condition.pc in self.repeat_conditions
            ):
                continue

            join_block = self.analysis.block_by_start.get(join)
            if join_block is None:
                continue
            skip_candidates: list[DecodedInstruction] = []
            for predecessor in join_block.predecessors:
                predecessor_block = self.analysis.block_by_start[predecessor]
                terminator = predecessor_block.terminator
                if (
                    terminator is not None
                    and terminator.name in {"JUMP", "JUMPX"}
                    and get_jump_target(terminator) == join
                    and self.analysis.dominates(branch.fallthrough, predecessor)
                ):
                    skip_candidates.append(terminator)
            if not skip_candidates:
                continue

            skip = max(skip_candidates, key=lambda item: item.pc)
            self.if_else_regions.setdefault(
                condition.pc,
                _IfElseRegion(
                    else_pc=branch.taken,
                    end_pc=join,
                    skip_jump_pc=skip.pc,
                ),
            )
            self.skip_jump_pcs.add(skip.pc)

    def _collect_labels(self) -> set[int]:
''',
    )

    Path(__file__).unlink()


if __name__ == "__main__":
    main()
