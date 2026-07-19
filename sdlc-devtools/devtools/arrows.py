"""Typed class->class arrows — the decomposition of an import edge into WHY it exists (bd 4bl.2).

`graph.py` graphs MODULES joined by imports. An import edge is the coarse OR of every reason one module
needs another, which is why import graphs are noisy: a type-only import and a real dependency look
identical. This engine emits the finer arrows, each at its native level, so a rule can name the reason:

  inherits   class -> class   is-a          (a base)
  holds      class -> class   has-a         (a field's type — composition, the object graph)
  references class -> class   API depends-on (a method signature's parameter / return type)

`calls` (uses-behaviour) is Batch 2 — it needs receiver resolution, and `holds` is its fuel: the field
annotation that makes `self.repo.save()` resolvable to `UserRepo.save` is the same one read here.

ROLL-UP: project any arrow's endpoints to their files and you land on the import edge — `import` is just
the coarsest fold. Cross-file arrows therefore ride an import (grimp agrees); INTRA-file arrows roll up to
a file self-loop, which the import graph legitimately drops and cannot represent at all.

RESOLUTION is annotation-driven and deliberately PRECISE-BUT-INCOMPLETE: a name resolves via the file's
own classes or its imports, and anything unresolvable (a builtin, a third-party type, a dynamic construct)
is simply not emitted. Never a wrong edge, sometimes a missing one — which is the honest trade for gates
that fire on the PRESENCE of an arrow.

Run: `python -m devtools.arrows [pkgs...]` (report).
"""

from __future__ import annotations

import argparse
import ast
import logging
from pathlib import Path

from devtools.names import Names
from devtools.trees import Trees

log = logging.getLogger("devtools.arrows")

INHERITS = "inherits"
HOLDS = "holds"
REFERENCES = "references"
_INIT = "__init__"


class ClassArrows:
    """Typed class->class arrows (inherits / holds / references) over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    # ---- naming -------------------------------------------------------------------------------------

    @staticmethod
    def module_of(path: Path) -> str:
        """The dotted module name backing a file (`pkg/sub/mod.py` -> `pkg.sub.mod`)."""
        parts = list(path.with_suffix("").parts)
        return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)

    @staticmethod
    def _imported_names(module: ast.Module) -> dict[str, str]:
        """{local name: home module} for `from X import Y [as Z]` — how a bare name reaches another file."""
        out: dict[str, str] = {}
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    out[alias.asname or alias.name] = node.module
        return out

    @staticmethod
    def _annotation_names(node: ast.expr | None) -> set[str]:
        """Every type name inside an annotation — unwraps `T | None`, `list[T]`, `Optional[T]`, strings."""
        if node is None:
            return set()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval").body
            except SyntaxError:  # a jaxtyping shape string is not a type expression — nothing to resolve
                return set()
        return {name for sub in ast.walk(node) if (name := Names.trailing(sub)) is not None}

    # ---- per-class extraction -----------------------------------------------------------------------

    @staticmethod
    def _init_of(cls: ast.ClassDef) -> ast.FunctionDef | None:
        return next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == _INIT), None)

    @staticmethod
    def _field_types(cls: ast.ClassDef) -> set[str]:
        """Type names this class HOLDS as instance state, from every way a field's type is declared:
        a class-body `x: T`, a `self.x: T`, an `__init__` param assigned to `self.x`, or `self.x = T(...)`.
        """
        held = {n.annotation for n in cls.body if isinstance(n, ast.AnnAssign)}
        names = {name for a in held for name in ClassArrows._annotation_names(a)}
        init = ClassArrows._init_of(cls)
        if init is None:
            return names
        params = {a.arg: a.annotation for a in init.args.args + init.args.kwonlyargs}
        for node in ast.walk(init):
            if isinstance(node, ast.AnnAssign) and ClassArrows._is_self_attr(node.target):
                names |= ClassArrows._annotation_names(node.annotation)
            if isinstance(node, ast.Assign) and any(ClassArrows._is_self_attr(t) for t in node.targets):
                names |= ClassArrows._assigned_type(node.value, params)
        return names

    @staticmethod
    def _is_self_attr(node: ast.expr) -> bool:
        return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"

    @staticmethod
    def _assigned_type(value: ast.expr, params: dict[str, ast.expr | None]) -> set[str]:
        """The type a `self.x = <value>` field holds — an annotated parameter passed in, or a direct
        construction `self.x = T(...)`. Both are the object graph; neither needs a call resolver."""
        if isinstance(value, ast.Name) and value.id in params:
            return ClassArrows._annotation_names(params[value.id])
        if isinstance(value, ast.Call):
            return {name} if (name := Names.trailing(value.func)) is not None else set()
        return set()

    @staticmethod
    def _signature_types(cls: ast.ClassDef) -> set[str]:
        """Type names this class REFERENCES through its method signatures (params + returns), minus the
        ones it already holds — the API-surface dependency, distinct from owning the object."""
        names: set[str] = set()
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            annotations = [a.annotation for a in fn.args.args + fn.args.kwonlyargs] + [fn.returns]
            names |= {n for a in annotations for n in ClassArrows._annotation_names(a)}
        return names

    # ---- graph --------------------------------------------------------------------------------------

    def _class_home(self) -> dict[tuple[str, str], str]:
        """{(module, class-name): qualified id} — every class we own, so an arrow can be resolved to one."""
        return {
            (self.module_of(path), cls.name): f"{self.module_of(path)}.{cls.name}"
            for path, tree in Trees(self.packages).walk()
            for cls in tree.body
            if isinstance(cls, ast.ClassDef)
        }

    def edges(self) -> list[tuple[str, str, str]]:
        """[(source class, target class, kind)] — every resolvable arrow between classes we own.

        A name resolves through the file's own classes first, then its imports. Anything else (builtin,
        third-party, dynamic) is dropped rather than guessed: precise, deliberately incomplete.
        """
        homes = self._class_home()
        out: list[tuple[str, str, str]] = []
        for path, tree in Trees(self.packages).walk():
            module = self.module_of(path)
            imports = self._imported_names(tree)
            local = {c.name for c in tree.body if isinstance(c, ast.ClassDef)}
            for cls in (c for c in tree.body if isinstance(c, ast.ClassDef)):
                src = f"{module}.{cls.name}"
                held = self._field_types(cls)
                for kind, names in (
                    (INHERITS, Names.bases(cls)),
                    (HOLDS, held),
                    (REFERENCES, self._signature_types(cls) - held),
                ):
                    out += [
                        (src, target, kind)
                        for name in sorted(names)
                        if (target := self._resolve(name, module, local, imports, homes)) is not None and target != src
                    ]
        return out

    @staticmethod
    def _resolve(
        name: str,
        module: str,
        local: set[str],
        imports: dict[str, str],
        homes: dict[tuple[str, str], str],
    ) -> str | None:
        """A bare name -> the qualified class it denotes: same-file first, then the file's imports."""
        if name in local:
            return homes.get((module, name))
        if name in imports:
            return homes.get((imports[name], name))
        return None

    def report(self) -> str:
        """Arrows grouped by kind — the explorer view of what an import edge actually decomposes into."""
        edges = self.edges()
        out = [f"class arrows: {len(edges)} over {len(self._class_home())} classes", ""]
        for kind in (INHERITS, HOLDS, REFERENCES):
            rows = sorted((s, d) for s, d, k in edges if k == kind)
            out.append(f"{kind} ({len(rows)}):")
            out += [f"  {s} -> {d}" for s, d in rows]
            out.append("")
        return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Typed class->class arrows (inherits / holds / references).")
    ap.add_argument("packages", nargs="+", help="root packages to scan")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log.info("\n%s", ClassArrows(args.packages).report())


if __name__ == "__main__":
    main()
