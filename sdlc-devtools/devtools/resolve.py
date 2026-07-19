"""Name -> class resolution over the source tree — the substrate both arrow engines stand on (bd 4bl.3).

Every typed arrow answers the same question first: *which class does this NAME denote, here?* A base, a
field annotation, a call receiver — all reduce to resolving a bare name in the context of one file. This is
that resolution, in one home, so `arrows.py` (structural) and `calls.py` (behavioural) share it rather than
each carrying a copy.

The rule is deliberately narrow: a name resolves through the file's OWN classes first, then through its
`from X import Y` bindings. Anything else — a builtin, a third-party type, something built dynamically —
resolves to nothing and the caller emits no edge. PRECISE BUT INCOMPLETE: never a wrong edge, sometimes a
missing one, which is what lets a gate fire on an arrow's PRESENCE and still block safely.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeGuard

from devtools.names import Names
from devtools.trees import Trees


@dataclass(frozen=True)
class FileScope:
    """What "here" means when resolving a name: the file's module, the classes it defines, and its import
    bindings. These three always travel together — passing them separately was a textbook data clump (and
    pushed the call resolver past the argument-count gate), so they are one value."""

    module: str
    local: frozenset[str] = frozenset()
    imports: dict[str, str] = field(default_factory=dict)


class Resolver:
    """Resolves bare names to the qualified classes they denote, per file, over the root packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages
        self._homes = self._class_homes()

    @staticmethod
    def module_of(path: Path) -> str:
        """The dotted module name backing a file (`pkg/sub/mod.py` -> `pkg.sub.mod`)."""
        parts = list(path.with_suffix("").parts)
        return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)

    @staticmethod
    def classes_in(tree: ast.Module) -> list[ast.ClassDef]:
        """The top-level classes of a module — the tier the class graph's nodes live at."""
        return [n for n in tree.body if isinstance(n, ast.ClassDef)]

    @staticmethod
    def imported_names(tree: ast.Module) -> dict[str, str]:
        """{local name: home module} for `from X import Y [as Z]` — how a bare name reaches another file."""
        return {
            alias.asname or alias.name: node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
            for alias in node.names
        }

    @staticmethod
    def annotation_names(node: ast.expr | None) -> set[str]:
        """Every type name inside an annotation — unwraps `T | None`, `list[T]`, `Optional[T]`, strings."""
        if node is None:
            return set()
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                node = ast.parse(node.value, mode="eval").body
            except SyntaxError:  # a jaxtyping shape string is not a type expression — nothing to resolve
                return set()
        return {name for sub in ast.walk(node) if (name := Names.trailing(sub)) is not None}

    def _class_homes(self) -> dict[tuple[str, str], str]:
        """{(module, class-name): qualified id} — every class we own, so a name can resolve to one."""
        return {
            (self.module_of(path), cls.name): f"{self.module_of(path)}.{cls.name}"
            for path, tree in Trees(self.packages).walk()
            for cls in self.classes_in(tree)
        }

    def qualified(self, module: str, name: str) -> str | None:
        """The qualified id of `name` if it is a class we own in `module`, else None."""
        return self._homes.get((module, name))

    @staticmethod
    def scope_of(path: Path, tree: ast.Module) -> FileScope:
        """The resolution context of one parsed file."""
        return FileScope(
            module=Resolver.module_of(path),
            local=frozenset(c.name for c in Resolver.classes_in(tree)),
            imports=Resolver.imported_names(tree),
        )

    def resolve(self, name: str, scope: FileScope) -> str | None:
        """A bare name -> the qualified class it denotes: same-file first, then the file's imports.

        Returns None for anything we do not own (builtin, third-party, dynamic) — the caller emits nothing
        rather than guessing.
        """
        if name in scope.local:
            return self.qualified(scope.module, name)
        if name in scope.imports:
            return self.qualified(scope.imports[name], name)
        return None

    def resolve_all(self, names: set[str], scope: FileScope, exclude: str = "") -> list[str]:
        """Every name in `names` that resolves to a class we own, sorted, minus `exclude` (a self-edge)."""
        return sorted(
            {target for name in names if (target := self.resolve(name, scope)) is not None and target != exclude}
        )

    # ---- declared types of a class's own state ------------------------------------------------------

    @staticmethod
    def init_of(cls: ast.ClassDef) -> ast.FunctionDef | None:
        return next((n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"), None)

    @staticmethod
    def is_self_attr(node: ast.expr) -> TypeGuard[ast.Attribute]:
        """`self.<name>` — a TypeGuard, not a bool, so callers may then read `.attr` SAFELY.

        As a plain bool this told the reader an invariant the type checker could not see, and every caller
        went on to touch `.attr` on a bare `ast.expr`. That is an AttributeError waiting for the first node
        shape we did not anticipate, in the resolver that maps everyone else's architecture."""
        return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self"

    @staticmethod
    def field_types(cls: ast.ClassDef) -> dict[str, set[str]]:
        """{field name: declared type names} for this class's instance state.

        Keyed by FIELD, not flattened, because the two engines need different cuts of it: the structural
        arrows want "what does this class hold" (the values), while the call resolver needs "what type is
        `self._store`" (the key) to bind a receiver. Reads every way a field's type is declared — a
        class-body `x: T`, a `self.x: T`, an `__init__` param kept as state, or `self.x = T(...)`.
        """
        fields: dict[str, set[str]] = {
            n.target.id: Resolver.annotation_names(n.annotation)
            for n in cls.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        init = Resolver.init_of(cls)
        if init is None:
            return fields
        params = {a.arg: a.annotation for a in init.args.args + init.args.kwonlyargs}
        for node in ast.walk(init):
            if isinstance(node, ast.AnnAssign) and Resolver.is_self_attr(node.target):
                fields.setdefault(node.target.attr, set()).update(Resolver.annotation_names(node.annotation))
            if isinstance(node, ast.Assign):
                for target in (t for t in node.targets if Resolver.is_self_attr(t)):
                    fields.setdefault(target.attr, set()).update(Resolver._assigned_type(node.value, params))
        return fields

    @staticmethod
    def _assigned_type(value: ast.expr, params: dict[str, ast.expr | None]) -> set[str]:
        """The type a `self.x = <value>` field holds — an annotated parameter passed in, or a direct
        construction `self.x = T(...)`. Both are the object graph."""
        if isinstance(value, ast.Name) and value.id in params:
            return Resolver.annotation_names(params[value.id])
        if isinstance(value, ast.Call):
            return {name} if (name := Names.trailing(value.func)) is not None else set()
        return set()
