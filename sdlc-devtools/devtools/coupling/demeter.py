"""Law of Demeter — CALLING a method on a stranger (bd 4bl.5, corrected by bd v3c.5).

"Talk to your friends, not to strangers." A method may use its OWN fields, its parameters, and things it
made; reaching *through* one of them to INVOKE something on a stranger — `self.store.config.reload()` —
couples this class to a type it never declared. That is the classic train wreck, and it is the one
architecture smell that needs no graph at all: it is visible inside a single expression.

ONLY CHAINS THAT END IN A CALL. The gate originally counted attribute hops and never looked at
`ast.Call` at all, which is the recurring mechanism-instead-of-concept error: hop depth is a proxy that
happens to correlate with the smell, not the smell. Measured on a consumer, 20 of its 22 findings were
reads of a nested config tree — `cfg.generator.synth.bg.mode` — where there is no stranger, no method, and
no coupling to an undeclared type, just data navigation. Worse, the only way to silence one is a
delegation wrapper, i.e. Fowler's MIDDLE MAN: the gate was trading one smell for another to satisfy a
proxy. Hydra/OmegaConf/pydantic settings trees are legitimately deep and are no longer findings.

DEPTH = attribute hops in the called chain. `self.store.get(k)` is 2 (own field, then talk to it) — fine.
`self.store.config.reload()` is 3 — that third hop is the reach-through, and it is what this gate names.

THIS RESTS ON `devtools.coupling.purity`. In Python a `@property` is a method call spelled as attribute access, so
"an attribute chain is only data" holds exactly as far as properties are pure reads. That is enforced, not
assumed — the purity gate ships alongside this one and blocks a `@property` that assigns to `self`.

NOT counted, because they are not object reach-through:
  - chains rooted at an IMPORTED MODULE (`np.linalg.norm`, `logging.handlers.X`) — a dotted module path,
    not a walk across objects. The file's own `import` statements say which roots those are.
  - chains rooted at a CLASS the file imported (`Path.home()`) — a namespace, not a friend's internals.

The ceiling is `[tool.structure] demeter_max_depth` (default 2), legislated like `file_max`: 2 is "use your
own field", 3 is already reaching past it.

Run: `python -m devtools.coupling.demeter [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import ast
import logging

from devtools.plumbing.cli import Cli
from devtools.plumbing.pyproject import Pyproject
from devtools.plumbing.resolve import Resolver
from devtools.plumbing.trees import Trees

log = logging.getLogger("devtools.coupling.demeter")


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

    @staticmethod
    def _friend(chain: ast.Attribute) -> str:
        """The FRIEND being reached through — who the fix should be asked of.

        For a chain rooted at `self` that is `self.<field>`, not `self`: telling someone to "ask self" for
        what they walked through `self._client` to get is not advice. For any other root the root itself is
        already the friend (a parameter, a local).
        """
        innermost = chain
        while isinstance(innermost.value, ast.Attribute):
            innermost = innermost.value
        return ast.unparse(innermost) if Resolver.is_self_attr(innermost) else ast.unparse(innermost.value)

    def _violations_in(self, tree: ast.Module, path: str) -> list[str]:
        """The over-deep chains in one module, outermost-first (an inner chain is the same train wreck)."""
        module_roots = self._module_roots(tree)
        out: list[str] = []
        seen: set[tuple[int, str]] = set()
        # CALLS, not attributes. Walking `ast.Call` and taking its `func` is the whole correction: the
        # chain has to be the thing being INVOKED, so a read of a deep config tree never enters the loop.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            root, depth = self._chain(node.func)
            name = self._root_name(root)
            if name is None or name in module_roots or depth <= self.max_depth:
                continue
            if (key := (node.lineno, name)) in seen:  # report the outermost chain once, not every prefix
                continue
            seen.add(key)
            out.append(
                f"{path}:{node.lineno}: `{ast.unparse(node.func)}()` calls {depth} deep (> {self.max_depth}) — "
                f"ask `{self._friend(node.func)}` to do it for you instead of reaching through it to a stranger"
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
