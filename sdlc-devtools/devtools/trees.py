"""The package-tree AST walk shared by every scanning engine — one home for 'iterate the source'.

Every engine previously re-globbed `*.py` and re-parsed each file; this is that logic in exactly one
place, so a change to what counts as source (ordering, encoding, which roots) lands once.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from devtools._common import ENCODING


class Trees:
    """The source-tree AST walk shared by every engine that scans packages."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def walk(self) -> Iterator[tuple[Path, ast.Module]]:
        """(path, parsed-AST) for every `*.py` under each root package, sorted within a package."""
        for pkg in self.packages:
            for path in sorted(Path(pkg).rglob("*.py")):
                yield path, ast.parse(path.read_text(encoding=ENCODING))

    def files(self) -> list[Path]:
        """Every `*.py` path under the root packages (no parse) — for line-count / path-only scans."""
        return [p for pkg in self.packages for p in sorted(Path(pkg).rglob("*.py"))]
