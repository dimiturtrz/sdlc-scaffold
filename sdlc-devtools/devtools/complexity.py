"""Cyclomatic-complexity explorer, built on radon's CC (McCabe 1976).

radon does the measurement (the mature, correct CC engine); this ranks it and prints the current max as
reviewer signal. ADVISORY only — the FIXED complexity gate is ruff `C901`/`PLR09xx` (CC>10 blocks), a
legislated house number. This surfaces the ranking so a reviewer sees drift below that floor; it never
blocks. A repo that wants a tighter legislated ceiling adds a config knob at that point, not speculatively.

    python -m devtools.complexity mypackage    # advisory ranked report, always exit 0
"""

from __future__ import annotations

import argparse
import logging

from radon.complexity import cc_visit

from devtools._common import ENCODING, Trees

log = logging.getLogger("devtools.complexity")

_FUNCTION = "Function"  # radon block type for a function/method (vs a "Class" aggregate we skip)


class Complexity:
    """Cyclomatic-complexity ranking + max-CC ratchet over the scanned packages, via radon's CC visitor."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    @staticmethod
    def _functions(source: str) -> list[tuple[str, int, int]]:
        """(name, complexity, lineno) for every function/method — radon flattens methods into the block list
        as `Function`s alongside a `Class` aggregate for the same methods, so keep only the Functions."""
        return [(b.name, b.complexity, b.lineno) for b in cc_visit(source) if type(b).__name__ == _FUNCTION]

    def scan(self) -> list[tuple[int, str, str]]:
        """(complexity, 'path:line', name) for every function across the packages, most complex first."""
        rows = []
        for path in Trees(self.packages).files():
            for name, complexity, lineno in self._functions(path.read_text(encoding=ENCODING)):
                rows.append((complexity, f"{path}:{lineno}", name))
        return sorted(rows, key=lambda r: -r[0])

    @staticmethod
    def report(rows: list[tuple[int, str, str]], limit: int = 15) -> str:
        """The ranked table of the most cyclomatically complex functions + the current max."""
        max_cc = rows[0][0] if rows else 0
        lines = [f"{len(rows)} functions; max cyclomatic complexity {max_cc} (radon CC / McCabe):"]
        lines.extend(f"  {cc:>3}  {loc}  {name}" for cc, loc, name in rows[:limit])
        return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(
        prog="python -m devtools.complexity",
        description="cyclomatic complexity (radon CC) ranked report (advisory)",
    )
    ap.add_argument("packages", nargs="+", help="package dirs to scan (>=1 required, no 'src' fallback)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # ADVISORY: a ranked CC report, always exit 0. The FIXED complexity gate is ruff C901 (CC>10, legislated
    # in ruff_select) — this just surfaces the ranking + current max as reviewer signal. A repo that wants a
    # tighter legislated ceiling adds a config knob at that point, not speculatively.
    log.info("%s", Complexity.report(Complexity(args.packages).scan()))


if __name__ == "__main__":
    main()
