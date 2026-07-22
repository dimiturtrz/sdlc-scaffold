"""Cyclomatic-complexity explorer, built on radon's CC (McCabe 1976).

radon does the measurement (the mature, correct CC engine); this ranks it and prints the current max as
reviewer signal. ADVISORY only — the FIXED complexity gate is ruff `C901`/`PLR09xx` (CC>10 blocks), a
legislated house number. This surfaces the ranking so a reviewer sees drift below that floor; it never
blocks. A repo that wants a tighter legislated ceiling adds a config knob at that point, not speculatively.

    python -m devtools.complexity mypackage    # advisory ranked report, always exit 0
"""

from __future__ import annotations

import logging

from radon.complexity import cc_visit

from devtools.plumbing._common import ENCODING
from devtools.plumbing.cli import Cli
from devtools.plumbing.trees import Trees

log = logging.getLogger("devtools.cohesion.complexity")

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

    def report(self) -> str:
        """The findings as one text block — the uniform explorer view every engine answers to.

        `_render` formats inputs the caller already computed; this computes them, so a caller needs
        only the engine. THREE report shapes across the engines is what made a shared CLI
        impossible: instance, static-taking-rows, and static-taking-an-artifact (bd 0y9).
        """
        return self._render(self.scan())

    @staticmethod
    def _render(rows: list[tuple[int, str, str]], limit: int = 15) -> str:
        """The ranked table of the most cyclomatically complex functions + the current max."""
        max_cc = rows[0][0] if rows else 0
        lines = [f"{len(rows)} functions; max cyclomatic complexity {max_cc} (radon CC / McCabe):"]
        lines.extend(f"  {cc:>3}  {loc}  {name}" for cc, loc, name in rows[:limit])
        return "\n".join(lines)


def main():
    Cli(Complexity, "cyclomatic complexity (radon CC) ranked report (advisory)").run()


if __name__ == "__main__":
    main()
