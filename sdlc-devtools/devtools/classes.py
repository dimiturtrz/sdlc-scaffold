"""Class-level containment + role classification — the layer the typed class graph is built on (bd 4bl.1).

`graph.py` works at MODULE granularity (grimp import edges). The class graph needs the level below it:
which classes each file defines, and which of them is the file's SUBJECT versus a subordinate companion.
That distinction is what makes "one file = one class" enforceable without outlawing the idiomatic
`Config`/`Error` companions that legitimately share a module.

A class is a SATELLITE when it is:
  - an ERROR — its name or a base ends in `Error`/`Exception`. Name-matching is reliable HERE because the
    shipped ruff select carries pep8-naming `N818`, which forces every exception name to end in `Error`;
    one gate makes the other's heuristic sound.
  - a DECLARED DATA CONTAINER or an ENUM — a value/config object, not behaviour. "Declared" is the test,
    not any single library: `@dataclass`, attrs (`@define`/`@frozen`), pydantic `BaseModel`, `NamedTuple`
    and `TypedDict` are one concept behind different syntax. Naming vocabularies (`*Cfg`, `*Config`) are
    deliberately NOT used — see `_is_data_container`.
  - a SUBCLASS OF A SAME-FILE CLASS — a local specialisation, not an independent peer.
Everything else is a PRIMARY. Two primaries in one file = two subjects = the split gate fires; zero is
fine (a pure error/config module has no subject of its own).

Run: `python -m devtools.classes [pkgs...]` (report) | `--assert` (gate on multi-primary files).
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

from devtools.cli import Cli
from devtools.names import Names
from devtools.trees import Trees

log = logging.getLogger("devtools.classes")

PRIMARY = "primary"
SATELLITE = "satellite"
_ERROR_SUFFIXES = ("Error", "Exception")  # N818 guarantees the convention this leans on
_ENUM_BASES = {"Enum", "StrEnum", "IntEnum", "Flag", "IntFlag", "ReprEnum"}
# A data container is DECLARED, and the declaration is what identifies it — not any one library's spelling.
# `dataclass` covers the stdlib and pydantic.dataclasses; define/frozen/mutable/attrs are the attrs API.
# attrs' legacy `@attr.s` is deliberately absent: it reduces to the trailing name `s`, and admitting that
# would match any `@x.s` — a worse rule than the gap. The modern define/frozen/mutable API is covered.
_DATA_DECORATORS = {"dataclass", "define", "frozen", "mutable", "attrs"}
_DATA_BASES = {"BaseModel", "NamedTuple", "TypedDict"}


class ClassIndex:
    """Every class under the root packages, grouped by file and tagged with its role."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    @staticmethod
    def _is_error(cls: ast.ClassDef) -> bool:
        """An exception class — by its own name or by a base's (N818 enforces the `Error` suffix)."""
        names = {cls.name} | Names.bases(cls)
        return any(n.endswith(_ERROR_SUFFIXES) for n in names)

    @staticmethod
    def _is_data_container(cls: ast.ClassDef) -> bool:
        """A record DECLARED rather than implemented — fields plus generated behaviour, no subject of its own.

        Deliberately mechanism-plural. Testing `@dataclass` alone tested one MECHANISM rather than the
        concept, so a pydantic model scored as PRIMARY — and pydantic is both the config idiom in every
        consumer repo and a dependency this very template ships (bd az9).

        Excludes the *Cfg / *Config / *Settings NAMING vocabulary on purpose: a name heuristic is only as
        sound as the gate that enforces the name. The `Error` suffix is safe precisely because ruff's N818
        forces it; nothing forces *Cfg, so keying on it would be fitting the rule to the shape of the repos
        we happen to have rather than to anything true.
        """
        declared = any(Names.decorator(d) in _DATA_DECORATORS for d in cls.decorator_list)
        return declared or bool(Names.bases(cls) & _DATA_BASES)

    @staticmethod
    def _is_enum(cls: ast.ClassDef) -> bool:
        return bool(Names.bases(cls) & _ENUM_BASES)

    @staticmethod
    def role(cls: ast.ClassDef, siblings: set[str], contracts: list[set[str]] | None = None) -> str:
        """PRIMARY (the file's subject) or SATELLITE (its error / value object / local specialisation).

        `siblings` = names of the OTHER classes defined in the same file, so a local subclass reads as a
        specialisation of this module's subject rather than a second, competing subject. `contracts` = the
        method sets of the same-file Protocols, so a STRUCTURAL implementation reads the same way.
        """
        subordinate = (
            ClassIndex._is_error(cls)
            or ClassIndex._is_data_container(cls)
            or ClassIndex._is_enum(cls)
            or bool(Names.bases(cls) & siblings)
            or ClassIndex._implements(cls, contracts or [])
        )
        return SATELLITE if subordinate else PRIMARY

    @staticmethod
    def _method_names(cls: ast.ClassDef) -> set[str]:
        """This class's own PUBLIC method names — the surface a Protocol is matched against."""
        return {n.name for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}

    @staticmethod
    def _contracts(classes: list[ast.ClassDef]) -> list[set[str]]:
        """Method sets of the same-file Protocols — the contracts a sibling can satisfy without inheriting."""
        return [
            methods for cls in classes if "Protocol" in Names.bases(cls) and (methods := ClassIndex._method_names(cls))
        ]

    @staticmethod
    def _implements(cls: ast.ClassDef, contracts: list[set[str]]) -> bool:
        """Whether this class structurally implements a same-file Protocol.

        The rule already treats "subclass of a same-file class" as a satellite — a local specialisation is
        not a competing subject. But that tests INHERITANCE, which is a mechanism, when the concept is local
        specialisation; `Protocol` exists precisely so you do NOT inherit, so the rule under-detected exactly
        where a codebase uses the more modern idiom (bd dun.1).

        Precise but incomplete, matching the resolver's rule: a superset of the contract's PUBLIC methods
        counts, so an unrelated class is never mislabelled a satellite — and an empty Protocol matches
        nothing, since every class would satisfy it.
        """
        if "Protocol" in Names.bases(cls):
            return False  # a Protocol DECLARES a contract; it does not locally implement one (it would
            # otherwise satisfy its own methods and label itself a satellite of itself)
        surface = ClassIndex._method_names(cls)
        return any(contract <= surface for contract in contracts)

    @staticmethod
    def classify(module: ast.Module) -> list[tuple[str, str]]:
        """[(class-name, role)] for one parsed module — the containment record for a single file."""
        classes = [n for n in module.body if isinstance(n, ast.ClassDef)]
        names = {c.name for c in classes}
        contracts = ClassIndex._contracts(classes)
        return [(c.name, ClassIndex.role(c, names - {c.name}, contracts)) for c in classes]

    def by_file(self) -> dict[Path, list[tuple[str, str]]]:
        """{file: [(class-name, role)]} across the root packages — the containment tree's class tier."""
        return {path: self.classify(tree) for path, tree in Trees(self.packages).walk()}

    def multi_primary(self) -> list[str]:
        """Files defining more than one PRIMARY class — two subjects in one module, split them."""
        out: list[str] = []
        for path, records in sorted(self.by_file().items()):
            primaries = [name for name, role in records if role == PRIMARY]
            if len(primaries) > 1:
                out.append(
                    f"{path.as_posix()}: {len(primaries)} primary classes {primaries} — one subject per file, split"
                )
        return out

    def report(self) -> str:
        """Per-file class roles as one text block — the explorer view."""
        out: list[str] = []
        for path, records in sorted(self.by_file().items()):
            if not records:
                continue
            out.append(path.as_posix())
            out += [f"  {role:<9} {name}" for name, role in records]
        return "\n".join(out)

    def run_assert(self) -> int:
        """The gate: log any multi-primary file and return an exit code (1 when any file has two subjects)."""
        violations = self.multi_primary()
        if violations:
            log.error("class roles — BLOCKING (%d):\n  %s", len(violations), "\n  ".join(violations))
            return 1
        log.info("class roles: clean (no file defines two primary classes)")
        return 0


def main():
    Cli(
        ClassIndex,
        "Class containment + role classification (primary vs satellite).",
        gate="exit 1 when a file defines more than one PRIMARY class",
    ).run()


if __name__ == "__main__":
    main()
