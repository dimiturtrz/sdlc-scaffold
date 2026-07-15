"""Cyclomatic-complexity gate + explorer, built on radon's CC (McCabe 1976).

radon does the measurement (the mature, correct CC engine); this adds the two things radon and xenon lack:
a ranked report AND the freeze-the-floor RATCHET. ruff `C901`/`PLR09xx` already own the FIXED floor (CC>10
blocks), so a fixed-threshold gate here would be pure duplication. The value is the ratchet BELOW that
floor: a repo whose worst function is CC 7 freezes 7 as the ceiling, and a new CC-9 function fails the merge
long before ruff's 10 would fire. Advisory (ranked report, never bites) until `[tool.complexity]
max_complexity` is set to the repo's current max (shown in the report); then it ratchets (bd 85l.4).

    python -m devtools.complexity mypackage                        # advisory report (current max CC)
    python -m devtools.complexity mypackage --max-complexity 7     # ratchet: fail if any function exceeds 7
"""

from __future__ import annotations

import argparse
import logging

from radon.complexity import cc_visit

from devtools._common import Ratchet, Trees

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
            for name, complexity, lineno in self._functions(path.read_text(encoding="utf-8")):
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
        description="cyclomatic complexity (radon CC) ranked report + max-CC ratchet",
    )
    ap.add_argument("packages", nargs="+", help="package dirs to scan (>=1 required, no 'src' fallback)")
    ap.add_argument(
        "--max-complexity",
        type=int,
        default=None,
        help="regression ratchet: exit 1 if any function's cyclomatic complexity exceeds this ceiling",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    rows = Complexity(args.packages).scan()
    log.info("%s", Complexity.report(rows))
    # Ratchet the single worst CC (shared freeze-the-floor primitive): CLI flag wins over the
    # [tool.complexity] max_complexity FACT; absent everywhere -> advisory report, never bites.
    max_cc = rows[0][0] if rows else 0
    Ratchet("complexity").enforce({"complexity": max_cc}, {"complexity": args.max_complexity}, log)


if __name__ == "__main__":
    main()
