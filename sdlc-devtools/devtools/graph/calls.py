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

An arrow terminates on the METHOD it invokes, found by walking the project MRO up from the receiver's
declared type to whichever class actually DEFINES that method (bd f1u.2). One rule covers every case:
inherited from a project base lands on the base, a Protocol receiver lands on the Protocol, and a chain
that leaves the project is an honest drop. `construct` is the deliberate exception — constructing is
`__init__`, i.e. the class as a whole — so behavioural coupling lands INSIDE the box and wiring lands ON it.

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
from dataclasses import dataclass

from devtools.plumbing.cli import Cli
from devtools.plumbing.names import Names
from devtools.plumbing.resolve import FileScope, Resolver

log = logging.getLogger("devtools.calls")

CALLS = "calls"
CONSTRUCT = "construct"


@dataclass(frozen=True, order=True)
class CallEdge:
    """One behavioural arrow, carrying BOTH method endpoints (bd f1u.2).

    Both were always in hand at walk time and both used to be thrown away: the target method is the
    attribute name in `self.repo.save()`, and the source method is the enclosing FunctionDef the per-class
    aggregation collapsed. Keeping them is what lets the method tier be a graph instead of a wall of
    labels — and the class-level view is recovered by projection (`source`/`target`), so nothing that read
    the coarse arrow lost anything.

    `target_method` is empty exactly for CONSTRUCT. Constructing is `__init__`, i.e. the class as a whole,
    so the partition is: behavioural coupling lands INSIDE the box, wiring lands ON it.
    """

    source: str
    target: str
    kind: str
    source_method: str
    target_method: str = ""

    @property
    def source_id(self) -> str:
        """The node this arrow leaves — always a method, since only a method body can make a call."""
        return f"{self.source}.{self.source_method}"

    @property
    def target_id(self) -> str:
        """The node this arrow lands on: the method for a call, the class itself for a construction."""
        return f"{self.target}.{self.target_method}" if self.target_method else self.target


@dataclass(frozen=True)
class CallSite:
    """Where a call is being read FROM: the enclosing class and method, plus every type declared in scope.

    These five always travel together — the same data clump that produced `FileScope`, one tier down. They
    arrived as five separate parameters threaded through three functions, which pushed `_edge_for_call`
    past the argument-count gate this package enforces on everyone else. That gate was right: the clump is
    a value, and naming it is what lets the receiver rule below read as one question rather than a
    parameter list.
    """

    cls: str
    method: str
    scope: FileScope
    fields: dict[str, set[str]]
    declared: dict[str, set[str]]

    @property
    def source_id(self) -> str:
        """The method node any arrow from this site leaves."""
        return f"{self.cls}.{self.method}"

    def receiver_type_names(self, recv: ast.expr) -> set[str]:
        """The DECLARED type names of a call's receiver, from what is already in scope.

        `self.x` -> the class's field map; a bare name -> a parameter annotation or a local's constructor.
        Two further shapes are just as precisely stated by the source, and leaving them out was costing
        most of the method tier's cross-class connectivity:

        * `Trees(pkgs).walk()` — the receiver is a CONSTRUCTION, so its type is the class being built. The
          value is unnamed, not undeclared, and a fluent call like this says exactly which class it is.
        * `Resolver.field_types(cls)` — the receiver is the CLASS ITSELF (a static/classmethod call). The
          name is not a parameter or a local, so the declared-types map is rightly empty for it; the name
          simply denotes a class, which is the resolver's ordinary question. Returning it unresolved lets
          the caller answer that in the usual way, and a name we do not own still yields nothing.

        Anything else (a subscript, a reflective lookup, a call on an untyped return) is not something the
        source declares here, so it yields nothing.
        """
        if Resolver.is_self_attr(recv):
            return self.fields.get(recv.attr, set())
        if isinstance(recv, ast.Call):
            return {name} if (name := Names.trailing(recv.func)) is not None else set()
        if isinstance(recv, ast.Name):
            # a local/param shadows a class name, so the declared type wins where there is one
            return self.declared.get(recv.id) or {recv.id}
        return set()


class CallArrows:
    """Behavioural arrows (calls, and calls tagged `construct`) over the root packages."""

    def __init__(self, packages: list[str], resolver: Resolver | None = None) -> None:
        self.packages = packages
        # An engine may be handed a Resolver that a sibling already built (bd 5cg) — it carries the parsed
        # trees, so sharing it turns four walks of the source into one.
        self.resolver = resolver if resolver is not None else Resolver(packages)
        self.misses: list[str] = []

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

    def _receiver_classes(self, recv: ast.expr, site: CallSite) -> list[str]:
        """The qualified classes a call's receiver may denote.

        `self` needs no resolution at all — the receiver IS the enclosing class. That case used to fall
        through every branch and yield nothing, which is why a class's own internals were invisible: a
        public method calling its private helper is real internal structure, and it is the reason the
        deepest depth stop exists.
        """
        if isinstance(recv, ast.Name) and recv.id == "self":
            return [site.cls]
        return self.resolver.resolve_all(site.receiver_type_names(recv), site.scope)

    def _edges_for_class(self, cls: ast.ClassDef, src: str, scope: FileScope) -> list[CallEdge]:
        fields = Resolver.field_types(cls)
        out: list[CallEdge] = []
        for fn in self._methods(cls):
            site = CallSite(src, fn.name, scope, fields, self._param_types(fn) | self._local_types(fn))
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    out += self._edge_for_call(node, site)
        return out

    def _edge_for_call(self, node: ast.Call, site: CallSite) -> list[CallEdge]:
        """The arrow one call site yields: a CONSTRUCT when the callee names a class, else a CALL landing on
        the method that the receiver's declared type actually DEFINES."""
        if isinstance(node.func, ast.Name):
            target = self.resolver.resolve(node.func.id, site.scope)
            # A class constructing itself is not a dependency between classes, and the arrow would point at
            # its own containing box. The behavioural coupling that matters here is what it CALLS.
            return [CallEdge(site.cls, target, CONSTRUCT, site.method)] if target and target != site.cls else []
        if not isinstance(node.func, ast.Attribute):
            return []
        method = node.func.attr
        # `self.<field>()` invokes the OBJECT held in that field — it is not a call to a method named after
        # it. `Cli.run` doing `self.engine(...)` constructs whatever class `engine` holds, and asking which
        # class defines a method called `engine` is simply the wrong question. The field's declared type is
        # what would name the callee, and for a `type`-valued field the source never says which one, so
        # there is nothing to emit and nothing to report. (Found by f1u.3's own miss channel, on our code.)
        if Resolver.is_self_attr(node.func) and method in site.fields:
            return []
        out = []
        for receiver in self._receiver_classes(node.func.value, site):
            definer = self.resolver.definer(receiver, method)
            if definer is None:
                self._miss(receiver, method, site)
                continue
            if definer == site.cls and method == site.method:
                continue  # direct recursion — a method calling itself is not an arrow between two things
            out.append(CallEdge(site.cls, definer, CALLS, site.method, method))
        return out

    def _miss(self, receiver: str, method: str, site: CallSite) -> None:
        """Record a resolved receiver whose method we could not find (bd f1u.3).

        Now that a call resolves to a DEFINER, a miss is mechanically meaningful rather than imprecision to
        hedge against. If the receiver's chain leaves the project the method is plausibly defined out there
        and we drop it quietly, by the same decision that stops us tracking into stdlib. If every ancestor
        is ours, one of two things is true and both are worth saying out loud: our MRO walk has a gap, or
        the repo has a missing attribute that a type checker would also flag.

        Reported, never gated — pyrefly is still landing across the consumer repos, so the clean-repo
        premise this would need is not yet true everywhere.
        """
        if not self.resolver.leaves_project(receiver):
            self.misses.append(f"{site.source_id} -> {receiver}.{method} — no such method on an in-project chain")

    def edges(self) -> list[CallEdge]:
        """Every behavioural arrow, deduped and sorted, with both method endpoints intact."""
        self.misses = []
        out: list[CallEdge] = []
        for path, tree in self.resolver.trees:
            scope = Resolver.scope_of(path, tree)
            for cls in Resolver.classes_in(tree):
                out += self._edges_for_class(cls, f"{scope.module}.{cls.name}", scope)
        return sorted(set(out))

    def class_edges(self) -> list[tuple[str, str, str]]:
        """The class-level projection: (source, target, kind), deduped.

        The coarse view every existing consumer reads. Intra-class calls project to a self-pair and are
        dropped here — at the class tier they are internal detail, not a dependency between two classes,
        and this is the same fold the import graph performs on an intra-file arrow.
        """
        return sorted({(e.source, e.target, e.kind) for e in self.edges() if e.source != e.target})

    def report(self) -> str:
        """Calls split by what they reach: the CONTRACT (calls) versus the CONCRETE (construct)."""
        edges = self.edges()
        calls = sorted((e.source_id, e.target_id) for e in edges if e.kind == CALLS)
        builds = sorted((e.source_id, e.target_id) for e in edges if e.kind == CONSTRUCT)
        out = [f"call arrows: {len(edges)}", "", f"calls -> the defining method ({len(calls)}):"]
        out += [f"  {s} -> {d}" for s, d in calls]
        out += ["", f"construct -> the concrete class ({len(builds)}):"]
        out += [f"  {s} -> {d}" for s, d in builds]
        if self.misses:
            out += ["", f"unresolved on an in-project chain ({len(self.misses)}):"]
            out += [f"  {m}" for m in sorted(set(self.misses))]
        return "\n".join(out)


def main():
    Cli(CallArrows, "Behavioural class->class arrows (calls / construct).").run()


if __name__ == "__main__":
    main()
