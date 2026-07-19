"""Dotted-name resolution over AST expressions — one home for 'what is this expression called'.

Every engine that reasons about class bases, decorators, or metaclass keywords needs the same reduction:
an `ast.expr` that may be a bare `Name` or a dotted `Attribute` down to the trailing identifier, so
`abc.ABC` and `ABC` compare equal against a vocabulary.
"""

from __future__ import annotations

import ast


class Names:
    """Dotted-name resolution shared by the AST engines."""

    @staticmethod
    def trailing(node: ast.expr) -> str | None:
        """The trailing name of a Name/Attribute node (`abc.ABC` -> 'ABC'), else None."""
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    @staticmethod
    def bases(cls: ast.ClassDef) -> set[str]:
        """The trailing names of a class's bases (`class A(x.B, C)` -> {'B', 'C'})."""
        return {name for b in cls.bases if (name := Names.trailing(b)) is not None}

    @staticmethod
    def decorator(node: ast.expr) -> str | None:
        """A decorator's name, unwrapping the CALL form — `@dataclass` and `@dataclass(frozen=True)` both
        reduce to 'dataclass'. A decorator factory is still that decorator, so the two must not diverge."""
        return Names.trailing(node.func if isinstance(node, ast.Call) else node)
