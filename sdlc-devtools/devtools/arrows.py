"""Typed class->class arrows — the decomposition of an import edge into WHY it exists (bd 4bl.2).

`graph.py` graphs MODULES joined by imports. An import edge is the coarse OR of every reason one module
needs another, which is why import graphs are noisy: a type-only import and a real dependency look
identical. This engine emits the STRUCTURAL arrows, so a rule can name the reason:

  inherits   class -> class   is-a          (a base)
  holds      class -> class   has-a         (a field's type — composition, the object graph)
  references class -> class   API depends-on (a method signature's parameter / return type)

`calls` (uses-behaviour) lives in `calls.py`, and `holds` is its fuel: the field annotation read here is
exactly what makes `self.repo.save()` resolvable to `UserRepo.save`. Both engines share `resolve.py`.

ROLL-UP: project any arrow's endpoints to their files and you land on the import edge — `import` is just
the coarsest fold. Cross-file arrows therefore ride an import (grimp agrees); INTRA-file arrows roll up to
a file self-loop, which the import graph legitimately drops and cannot represent at all.

Run: `python -m devtools.arrows [pkgs...]` (report).
"""

from __future__ import annotations

import ast
import logging

from devtools.cli import Cli
from devtools.names import Names
from devtools.resolve import Resolver
from devtools.trees import Trees

log = logging.getLogger("devtools.arrows")

INHERITS = "inherits"
HOLDS = "holds"
REFERENCES = "references"
_INIT = "__init__"


class ClassArrows:
    """Structural class->class arrows (inherits / holds / references) over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages
        self.resolver = Resolver(packages)

    @staticmethod
    def field_types(cls: ast.ClassDef) -> set[str]:
        """Type NAMES this class holds as instance state — the values of the shared per-field map, since
        composition asks WHAT is held, not under which attribute name (that cut is the call resolver's)."""
        return set().union(*Resolver.field_types(cls).values(), set())

    @staticmethod
    def signature_types(cls: ast.ClassDef) -> set[str]:
        """Type names this class REFERENCES through its method signatures (params + returns) — the
        API-surface dependency, distinct from owning the object."""
        names: set[str] = set()
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            annotations = [a.annotation for a in fn.args.args + fn.args.kwonlyargs] + [fn.returns]
            names |= {n for a in annotations for n in Resolver.annotation_names(a)}
        return names

    def edges(self) -> list[tuple[str, str, str]]:
        """[(source class, target class, kind)] — every resolvable structural arrow between classes we own."""
        out: list[tuple[str, str, str]] = []
        for path, tree in Trees(self.packages).walk():
            scope = Resolver.scope_of(path, tree)
            for cls in Resolver.classes_in(tree):
                src = f"{scope.module}.{cls.name}"
                held = self.field_types(cls)
                for kind, names in (
                    (INHERITS, Names.bases(cls)),
                    (HOLDS, held),
                    (REFERENCES, self.signature_types(cls) - held),
                ):
                    out += [(src, target, kind) for target in self.resolver.resolve_all(names, scope, src)]
        return out

    def report(self) -> str:
        """Arrows grouped by kind — the explorer view of what an import edge actually decomposes into."""
        edges = self.edges()
        out = [f"class arrows: {len(edges)}", ""]
        for kind in (INHERITS, HOLDS, REFERENCES):
            rows = sorted((s, d) for s, d, k in edges if k == kind)
            out.append(f"{kind} ({len(rows)}):")
            out += [f"  {s} -> {d}" for s, d in rows]
            out.append("")
        return "\n".join(out)


def main():
    Cli(ClassArrows, "Typed class->class arrows (inherits / holds / references).").run()


if __name__ == "__main__":
    main()
