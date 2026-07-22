"""A `@property` must not mutate — a read dressed as an attribute has to BE a read (bd v3c.4).

`obj.total` looks like a field. If evaluating it changes the object, then reading is writing, and every
reader becomes a writer without saying so: a debugger watch, a log line, a test assertion, an `if` that
short-circuits. Nothing in the toolbox enforces this. Ruff's six property rules are PLR0206 (no
parameters), RUF066 (no return statement) and B009/B010/B043 (constant getattr/setattr/delattr); none of
them says "do not assign to self".

IT IS ALSO THE PREMISE `demeter` RESTS ON. That gate flags only chains ending in a CALL, on the grounds
that `a.b.c` is data navigation. In Python a property is a method call spelled as attribute access — so if
properties may mutate, "skip attribute chains" silently lets real reach-through through. These two ship
together or the cheaper Demeter rule is not honest.

THE SETTER IS THE EXCEPTION, and it is the whole point of one: `@x.setter` is the place where assigning to
`self` is the declared contract. Same for `@x.deleter`.

PRECISE BUT INCOMPLETE, as everywhere else here. This sees assignment to `self` inside the property body.
A property that calls a method which mutates elsewhere is not caught, and proving purity in general is not
attempted — the common, checkable case is the one worth a gate.

Run: `python -m devtools.purity [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import ast
import logging
from collections.abc import Iterator
from pathlib import Path

from devtools.plumbing.cli import Cli
from devtools.plumbing.resolve import Resolver
from devtools.plumbing.trees import Trees

log = logging.getLogger("devtools.purity")

# `@x.setter` / `@x.deleter` — the decorators whose entire job is to mutate. Matched on the ATTRIBUTE half
# so any property name works, which is also why this cannot be a plain name set.
MUTATORS = frozenset({"setter", "deleter"})


class PropertyPurity:
    """Assignments to `self` inside a `@property` body, over the root packages."""

    def __init__(self, packages: list[str], trees: list[tuple[Path, ast.Module]] | None = None) -> None:
        self.packages = packages
        # Takes the TREES rather than a Resolver (bd 5cg): this reads one function body at a time and never
        # resolves a name, so asking for a resolver would make a standalone run build an index it never opens.
        self.trees = trees if trees is not None else list(Trees(packages).walk())

    @staticmethod
    def is_property(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """Decorated `@property` (or `@cached_property`) and NOT `@x.setter`/`@x.deleter`.

        `functools.cached_property` is included deliberately. Its caching is done by the DESCRIPTOR, not by
        the body, so a cached_property whose body assigns to self is a hand-rolled second cache on top of
        the real one — the exact confusion this gate exists to name.
        """
        names = {
            d.attr if isinstance(d, ast.Attribute) else d.id
            for d in func.decorator_list
            if isinstance(d, ast.Attribute | ast.Name)
        }
        return bool(names & {"property", "cached_property"}) and not (names & MUTATORS)

    @staticmethod
    def assigned_selves(func: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.Attribute]:
        """Every `self.<field>` written anywhere in this body — assigned, augmented, annotated or deleted.

        The four statement kinds keep their targets in three differently-shaped fields, so they are
        normalised to one stream of targets here rather than branched on at the call site.
        """
        for node in ast.walk(func):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AugAssign | ast.AnnAssign):
                targets = [node.target]
            elif isinstance(node, ast.Delete):
                targets = node.targets
            yield from (t for t in targets if Resolver.is_self_attr(t))

    def _violations_in(self, tree: ast.Module, path: str) -> list[str]:
        """The mutating properties in one module."""
        return [
            f"{path}:{write.lineno}: `{cls.name}.{func.name}` is a @property that assigns "
            f"`self.{write.attr}` — reading it changes the object; make it a method, or cache with "
            f"`functools.cached_property`"
            for cls in ast.walk(tree)
            if isinstance(cls, ast.ClassDef)
            for func in cls.body
            if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef) and self.is_property(func)
            for write in self.assigned_selves(func)
        ]

    def violations(self) -> list[str]:
        """Every mutating property in the root packages."""
        return [msg for path, tree in self.trees for msg in self._violations_in(tree, path.as_posix())]

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        found = self.violations()
        return "\n".join([f"mutating properties: {len(found)}", *found])

    def run_assert(self) -> int:
        """The gate: log every mutating property and return an exit code."""
        found = self.violations()
        if found:
            log.error("mutating properties — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("property purity: clean (no @property writes to self)")
        return 0


def main():
    Cli(
        PropertyPurity,
        "Property purity — a @property must not mutate.",
        gate="exit 1 on a @property that assigns to self",
    ).run()


if __name__ == "__main__":
    main()
