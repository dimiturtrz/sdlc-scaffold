"""Behavioural class->class arrows — who CALLS whom, and who CONSTRUCTS whom (bd 4bl.3).

The structural arrows (`arrows.py`) say what a class *knows*. This says what it *does*: the edge a rule
needs to talk about real dependency rather than import-noise.

RESOLVED TO THE DECLARED TYPE, never the concrete one. `self._store.get(k)` where `_store: Store` is an
edge to **Store** — the contract the code committed to — even when a `MemoryStore` is what runs at runtime.
That is not a limitation to apologise for: the declared type IS the architectural dependency. Chasing the
concrete would invent an edge the source never states.

The concrete coupling is not lost, it is just filed where it belongs. A concrete is *constructed*
somewhere — a factory, a wiring site — and that emits `via=construct`. So the two cuts partition it:

    calls      -> the INTERFACE   (behavioural contract)
    construct  -> the CONCRETE    (wiring, at the site that chose it)

A receiver resolves from the declared types already in scope: `self.<field>` through the class's field map,
a parameter through its annotation, a local through the constructor that made it. Anything else — a call on
a returned value, a reflective lookup — resolves to nothing and emits no edge. PRECISE BUT INCOMPLETE:
never a wrong edge, sometimes a missing one. Because our house style types every field and parameter, and
because we attribute to the DECLARED type instead of guessing the dispatch, that incompleteness is small
and, critically, one-directional — which is what lets a gate fire on an arrow's PRESENCE and still block.

Run: `python -m devtools.calls [pkgs...]` (report).
"""

from __future__ import annotations

import ast
import logging

from devtools.cli import Cli
from devtools.names import Names
from devtools.resolve import FileScope, Resolver
from devtools.trees import Trees

log = logging.getLogger("devtools.calls")

CALLS = "calls"
CONSTRUCT = "construct"


class CallArrows:
    """Behavioural class->class arrows (calls, and calls tagged `construct`) over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages
        self.resolver = Resolver(packages)

    @staticmethod
    def _methods(cls: ast.ClassDef) -> list[ast.FunctionDef]:
        return [n for n in cls.body if isinstance(n, ast.FunctionDef)]

    @staticmethod
    def _local_types(fn: ast.FunctionDef) -> dict[str, set[str]]:
        """{local name: type} for `x = T(...)` — a local's type is the constructor that made it."""
        out: dict[str, set[str]] = {}
        for node in ast.walk(fn):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            made = Names.trailing(node.value.func)
            for target in (t for t in node.targets if isinstance(t, ast.Name)):
                if made is not None:
                    out.setdefault(target.id, set()).add(made)
        return out

    @staticmethod
    def _param_types(fn: ast.FunctionDef) -> dict[str, set[str]]:
        return {a.arg: Resolver.annotation_names(a.annotation) for a in fn.args.args + fn.args.kwonlyargs}

    @staticmethod
    def _receiver_type_names(recv: ast.expr, fields: dict[str, set[str]], scope: dict[str, set[str]]) -> set[str]:
        """The DECLARED type names of a call's receiver, from what is already in scope.

        `self.x` -> the class's field map; a bare name -> a parameter annotation or a local's constructor.
        Anything else (a call's return value, a subscript, a reflective lookup) is not something the source
        declares here, so it yields nothing.
        """
        if Resolver.is_self_attr(recv):
            return fields.get(recv.attr, set())
        if isinstance(recv, ast.Name):
            return scope.get(recv.id, set())
        return set()

    def _edges_for_class(self, cls: ast.ClassDef, src: str, scope: FileScope) -> list[tuple[str, str, str, str]]:
        fields = Resolver.field_types(cls)
        out: list[tuple[str, str, str, str]] = []
        for fn in self._methods(cls):
            declared = self._param_types(fn) | self._local_types(fn)
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    out += self._edge_for_call(node, src, scope, fields, declared)
        return out

    def _edge_for_call(
        self,
        node: ast.Call,
        src: str,
        scope: FileScope,
        fields: dict[str, set[str]],
        declared: dict[str, set[str]],
    ) -> list[tuple[str, str, str, str]]:
        """The arrow one call site yields: a CONSTRUCT when the callee names a class, else a CALL to the
        receiver's declared type. Self-edges are dropped — a class calling itself is not a dependency."""
        if isinstance(node.func, ast.Name):
            target = self.resolver.resolve(node.func.id, scope)
            return [(src, target, CALLS, CONSTRUCT)] if target and target != src else []
        if not isinstance(node.func, ast.Attribute):
            return []
        names = self._receiver_type_names(node.func.value, fields, declared)
        return [(src, target, CALLS, "") for target in self.resolver.resolve_all(names, scope, src)]

    def edges(self) -> list[tuple[str, str, str, str]]:
        """[(source class, target class, kind, via)] — deduped; `via` is 'construct' or ''."""
        out: list[tuple[str, str, str, str]] = []
        for path, tree in Trees(self.packages).walk():
            scope = Resolver.scope_of(path, tree)
            for cls in Resolver.classes_in(tree):
                out += self._edges_for_class(cls, f"{scope.module}.{cls.name}", scope)
        return sorted(set(out))

    def report(self) -> str:
        """Calls split by what they reach: the CONTRACT (calls) versus the CONCRETE (construct)."""
        edges = self.edges()
        calls = sorted((s, d) for s, d, _, via in edges if not via)
        builds = sorted((s, d) for s, d, _, via in edges if via == CONSTRUCT)
        out = [f"call arrows: {len(edges)}", "", f"calls -> the declared type ({len(calls)}):"]
        out += [f"  {s} -> {d}" for s, d in calls]
        out += ["", f"construct -> the concrete ({len(builds)}):"]
        out += [f"  {s} -> {d}" for s, d in builds]
        return "\n".join(out)


def main():
    Cli(CallArrows, "Behavioural class->class arrows (calls / construct).").run()


if __name__ == "__main__":
    main()
