"""Law of Demeter — reach-through depth inside a method body (bd 4bl.5).

"Talk to your friends, not to strangers." A method may use its OWN fields, its parameters, and things it
made; reaching *through* one of them into a stranger — `self.store.config.namespace` — couples this class
to a type it never declared. That is the classic train wreck, and it is the one architecture smell that
needs no graph at all: it is visible inside a single expression.

DEPTH = attribute hops in a chain. `self.store.get(k)` is 2 (own field, then talk to it) — fine.
`self.store.config.name` is 3 — that third hop is the reach-through, and it is what this gate names.

NOT counted, because they are not object reach-through:
  - chains rooted at an IMPORTED MODULE (`np.linalg.norm`, `logging.handlers.X`) — a dotted module path,
    not a walk across objects. The file's own `import` statements say which roots those are.
  - chains rooted at a CLASS the file imported (`Path.home()`) — a namespace, not a friend's internals.

The ceiling is `[tool.structure] demeter_max_depth` (default 2), legislated like `file_max`: 2 is "use your
own field", 3 is already reaching past it.

Run: `python -m devtools.demeter [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import ast
import logging

from devtools.cli import Cli
from devtools.pyproject import Pyproject
from devtools.trees import Trees

log = logging.getLogger("devtools.demeter")


class Demeter:
    """Reach-through (Law of Demeter) violations over the root packages."""

    def __init__(self, packages: list[str], max_depth: int | None = None) -> None:
        self.packages = packages
        self.max_depth = max_depth if max_depth is not None else self.load_max_depth()

    @staticmethod
    def load_max_depth(pyproject: str = "pyproject.toml") -> int:
        """The attribute-hop ceiling from `[tool.structure] demeter_max_depth`, defaulted when absent."""
        return int(Pyproject.structure_cfg(pyproject)["demeter_max_depth"])

    @staticmethod
    def _module_roots(module: ast.Module) -> set[str]:
        """Names bound to an imported MODULE or an imported CLASS — roots whose dots are a namespace path,
        not a walk across objects (`np.linalg.norm`, `Path.home()`)."""
        roots: set[str] = set()
        for node in ast.walk(module):
            if isinstance(node, ast.Import):
                roots |= {(a.asname or a.name).split(".")[0] for a in node.names}
            if isinstance(node, ast.ImportFrom):
                roots |= {a.asname or a.name for a in node.names}
        return roots

    @staticmethod
    def _chain(node: ast.Attribute) -> tuple[ast.expr, int]:
        """Walk an attribute chain to its root, returning (root expression, attribute-hop count)."""
        depth = 0
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            depth += 1
            current = current.value
        return current, depth

    @staticmethod
    def _root_name(root: ast.expr) -> str | None:
        return root.id if isinstance(root, ast.Name) else None

    def _violations_in(self, tree: ast.Module, path: str) -> list[str]:
        """The over-deep chains in one module, outermost-first (an inner chain is the same train wreck)."""
        module_roots = self._module_roots(tree)
        out: list[str] = []
        seen: set[tuple[int, str]] = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            root, depth = self._chain(node)
            name = self._root_name(root)
            if name is None or name in module_roots or depth <= self.max_depth:
                continue
            if (key := (node.lineno, name)) in seen:  # report the outermost chain once, not every prefix
                continue
            seen.add(key)
            out.append(
                f"{path}:{node.lineno}: `{ast.unparse(node)}` reaches {depth} deep (> {self.max_depth}) — "
                f"ask `{name}` for what you need instead of walking through it"
            )
        return out

    def violations(self) -> list[str]:
        """Every reach-through in the root packages."""
        return [msg for path, tree in Trees(self.packages).walk() for msg in self._violations_in(tree, path.as_posix())]

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        found = self.violations()
        return "\n".join([f"law of demeter (max depth {self.max_depth}): {len(found)}", *found])

    def run_assert(self) -> int:
        """The gate: log violations and return an exit code (1 when any chain reaches too deep)."""
        found = self.violations()
        if found:
            log.error("law of demeter — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("law of demeter: clean (no chain reaches past depth %d)", self.max_depth)
        return 0


def main():
    Cli(Demeter, "Law of Demeter — reach-through chain depth.", gate="exit 1 on a reach-through").run()


if __name__ == "__main__":
    main()
