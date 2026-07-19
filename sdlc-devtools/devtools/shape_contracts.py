"""Shape-contract coverage gate (ML domain): any function whose parameter or return is an ARRAY/TENSOR
type must carry a jaxtyping annotation, so the shape is a CHECKED contract and not a silent assumption.
The mechanical ratchet behind a codebase-wide shape rollout — it SURFACES bare-array boundaries and the
author fixes each by giving it a jaxtyping type (a dtype-only `"..."` is the honest answer for a
shape-agnostic reduction).

What counts as an array annotation: `np.ndarray` / `numpy.ndarray`, `torch.Tensor` / `Tensor`, or a
repo's array aliases (`[tool.shape_contracts] array_aliases` — e.g. `Volume`/`Mask`/`Image`). What
SATISFIES the contract: a jaxtyping subscript (`Float`/`Int`/`Integer`/`Bool`/`Shaped`/… `[array, "…"]`).
A bare array annotation (or an array alias) is flagged.

Scope: EVERY function — class methods (public AND private) AND module-level functions (bd drn). Shapes are
unrelated to visibility: a bare tensor on a private helper is as unchecked as on a public boundary, so
public/private is not a shape axis. Only array/tensor slots are ever flagged, so a scalar-only signature
(a private int helper) is untouched — the backlog stays bounded to real array surfaces. Exempt: CLI
`add_args`/`run` dispatcher handlers (framework signatures — `args` is a Namespace). Ships ADVISORY
(report-only, exit 0). A repo opts into the blocking ratchet with `--assert` once its tree is clean — a
new bare-array boundary then fails the merge.

    python -m devtools.shape_contracts <packages>            # advisory report
    python -m devtools.shape_contracts <packages> --assert   # blocking (exit 1 on any bare boundary)
"""

from __future__ import annotations

import ast
import logging

from devtools.cli import Cli
from devtools.pyproject import Pyproject
from devtools.trees import Trees

log = logging.getLogger("devtools.shape_contracts")

# The universal array types every ML repo shares. Repo-specific aliases (core.types names that also denote
# an array — Volume/Mask/…) are additive via [tool.shape_contracts] array_aliases, read below.
_ARRAY_NAMES = {"ndarray", "Tensor"}
_JAXTYPING = {"Float", "Int", "Integer", "UInt", "UInt8", "Bool", "Shaped", "Num", "Inexact", "Complex"}
_EXEMPT = {"add_args", "run"}  # CLI dispatcher handlers (framework signature, args is a Namespace)


class ShapeContracts:
    """Flag array/tensor boundaries lacking a jaxtyping shape across the scanned packages — every function,
    methods and module-level alike, public and private (shapes are visibility-independent)."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    @staticmethod
    def array_names(pyproject: str = "pyproject.toml") -> set[str]:
        """The array-type names to flag: the builtin `ndarray`/`Tensor` plus the repo's `array_aliases` slot."""
        aliases = Pyproject.str_list(Pyproject.tool_section("shape_contracts", pyproject).get("array_aliases"))
        return _ARRAY_NAMES | set(aliases)

    @staticmethod
    def _is_array_anno(node: ast.expr | None, names: set[str]) -> bool:
        """True if the annotation names a bare array type (np.ndarray / Tensor / an array alias) — the thing
        that must instead carry a jaxtyping shape. Looks through `X | None` unions."""
        if node is None:
            return False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):  # T | None
            return ShapeContracts._is_array_anno(node.left, names) or ShapeContracts._is_array_anno(node.right, names)
        if isinstance(node, ast.Attribute):  # np.ndarray / torch.Tensor
            return node.attr in names
        if isinstance(node, ast.Name):  # Tensor / Volume / Mask …
            return node.id in names
        return False

    @staticmethod
    def _is_jaxtyping_anno(node: ast.expr | None) -> bool:
        """True if the annotation is a jaxtyping subscript (`Float[array, "…"]`) — a satisfied shape contract.
        Looks through `X | None` unions so an optional shaped tensor still counts."""
        if node is None:
            return False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return ShapeContracts._is_jaxtyping_anno(node.left) or ShapeContracts._is_jaxtyping_anno(node.right)
        if isinstance(node, ast.Subscript):
            head = node.value
            return isinstance(head, ast.Name) and head.id in _JAXTYPING
        return False

    @staticmethod
    def _annotations(fn: ast.FunctionDef) -> list[tuple[str, ast.expr | None]]:
        """(label, annotation) for every parameter + the return of a function."""
        a = fn.args
        params = [*a.posonlyargs, *a.args, *a.kwonlyargs]
        out: list[tuple[str, ast.expr | None]] = [(p.arg, p.annotation) for p in params]
        out.append(("->return", fn.returns))
        return out

    @staticmethod
    def _bare_array_slots(fn: ast.FunctionDef, names: set[str]) -> list[str]:
        """Param/return labels whose annotation is a bare array type without a jaxtyping shape."""
        return [
            label
            for label, anno in ShapeContracts._annotations(fn)
            if ShapeContracts._is_array_anno(anno, names) and not ShapeContracts._is_jaxtyping_anno(anno)
        ]

    @staticmethod
    def _functions(tree: ast.Module) -> list[tuple[str, ast.FunctionDef]]:
        """(qualname, fn) for every function shapes are enforced on: class methods (`Class.method`, public
        AND private) plus module-level functions (bd drn). CLI dispatcher handlers are the sole exemption."""
        out: list[tuple[str, ast.FunctionDef]] = []
        for cls in ast.walk(tree):
            if isinstance(cls, ast.ClassDef):
                out += [
                    (f"{cls.name}.{m.name}", m)
                    for m in cls.body
                    if isinstance(m, ast.FunctionDef) and m.name not in _EXEMPT
                ]
        out += [(f.name, f) for f in tree.body if isinstance(f, ast.FunctionDef) and f.name not in _EXEMPT]
        return out

    @staticmethod
    def _analyze(tree: ast.Module, names: set[str]) -> list[tuple[int, str, list[str]]]:
        """(lineno, qualname, bare-slots) for every function in a tree with a bare-array boundary."""
        out = []
        for qual, fn in ShapeContracts._functions(tree):
            slots = ShapeContracts._bare_array_slots(fn, names)
            if slots:
                out.append((fn.lineno, qual, slots))
        return out

    def scan(self, names: set[str] | None = None) -> list[tuple[str, int, str, list[str]]]:
        """(file, lineno, qualname, slots) for every bare-array boundary across the packages."""
        if names is None:
            names = self.array_names()
        rows = []
        for path, tree in Trees(self.packages).walk():
            rows.extend((str(path), ln, name, slots) for ln, name, slots in self._analyze(tree, names))
        return rows

    def report(self) -> str:
        """The findings as one text block — the uniform explorer view every engine answers to.

        `_render` formats ROWS the caller already has; this computes them, so a caller needs only
        the engine. Two report shapes across the engines is what made a shared CLI impossible.
        """
        rows = self.scan()
        return self._render(rows)

    def run_assert(self) -> int:
        """The gate: log the boundaries and return an exit code (1 when any bare array/tensor remains).

        This engine had `--assert` but no run_assert — it gated INLINE in main(), so the one thing every
        other gate engine exposes as a method was, here, only reachable by running the CLI (bd 0y9).
        """
        rows = self.scan()
        log.info("%s", self._render(rows))
        return 1 if rows else 0

    @staticmethod
    def _render(rows: list[tuple[str, int, str, list[str]]]) -> str:
        lines = [f"{len(rows)} bare-array boundaries (array-typed param/return without a jaxtyping shape):"]
        for path, ln, name, slots in rows:
            lines.append(f"  {path}:{ln}  {name}  [{', '.join(slots)}]")
        return "\n".join(lines)


def main():
    Cli(
        ShapeContracts,
        "Flag public array/tensor boundaries lacking a jaxtyping shape.",
        gate="exit 1 if any bare-array boundary remains (the blocking CI gate)",
    ).run()


if __name__ == "__main__":
    main()
