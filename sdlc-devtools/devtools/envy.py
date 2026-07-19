"""Feature envy — a method more interested in another class than its own (bd 4bl.7).

Fowler's smell, at the granularity it actually lives: the METHOD. `arrows.py` and `calls.py` aggregate per
CLASS, which is the right cut for "does this class depend on that one" but blind here — a class can be
perfectly coupled overall while one of its methods really belongs somewhere else.

MEASURE, per method: how many members it touches on ITS OWN object (`self.x`, `self.foo()`) versus on ONE
other class (`self._store.get(...)`, `param.field`). Envy is judged against a SINGLE foreign class, not the
sum of all of them — a method that talks to three collaborators is coordinating, which is a different thing
(and often correct); a method that talks past its own state into one specific other class is the smell.

Only the OUTERMOST link of an attribute chain is counted, so `self._store.get(k)` is one access to `Store`
rather than also an access to `self`. Receivers resolve exactly as in `calls.py` — a field's declared type,
a parameter's annotation, a local's constructor — and anything unresolvable is not counted at all, so the
ratio is only ever computed over accesses we actually understand.

TUNING: `[tool.structure] feature_envy_min` (default 4) is the floor of foreign accesses before a method is
judged at all. Below it the ratio is noise — two accesses versus one is not evidence of anything. Legitimate
delegators (mappers, serializers, visitors, facades) read another class heavily BY DESIGN, so the floor is
raisable per repo rather than the rule being weakened.

Run: `python -m devtools.envy [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import ast
import logging
from collections import Counter
from dataclasses import dataclass

from devtools.classes import SATELLITE, ClassIndex
from devtools.cli import Cli
from devtools.pyproject import Pyproject
from devtools.resolve import FileScope, Resolver
from devtools.trees import Trees

log = logging.getLogger("devtools.envy")


@dataclass(frozen=True)
class MethodSite:
    """WHERE a method is — file, class, name, line. These four always travel together when reporting a
    finding, so they are one value rather than four parameters (which is what the argument-count gate was
    telling us)."""

    path: str
    cls: str
    name: str
    line: int

    def describe(self, target: str, count: int, own: int) -> str:
        return (
            f"{self.path}:{self.line}: {self.cls}.{self.name} touches {target} {count}x but its own "
            f"state {own}x — the method may belong on {target.rsplit('.', 1)[-1]}"
        )


class FeatureEnvy:
    """Methods that touch one other class more than their own object."""

    def __init__(self, packages: list[str], minimum: int | None = None) -> None:
        self.packages = packages
        self.minimum = minimum if minimum is not None else self.load_minimum()
        self.resolver = Resolver(packages)
        self._satellite_ids = self._satellites()

    @staticmethod
    def load_minimum(pyproject: str = "pyproject.toml") -> int:
        """Foreign-access floor from `[tool.structure] feature_envy_min`, defaulted when absent."""
        return int(Pyproject.structure_cfg(pyproject)["feature_envy_min"])

    def _satellites(self) -> set[str]:
        """Qualified ids of the SATELLITE classes — a value object / config / enum / error family.

        Reading one field-by-field is not envy: that is what a value object is FOR, and the fix envy
        implies (move the method onto it) is usually impossible, because the method also needs its own
        object's state. Reusing the role classification from bd 4bl.1 keeps this a principled exclusion
        rather than a suppression list.
        """
        return {
            f"{Resolver.module_of(path)}.{name}"
            for path, records in ClassIndex(self.packages).by_file().items()
            for name, role in records
            if role == SATELLITE
        }

    def _is_satellite(self, target: str) -> bool:
        return target in self._satellite_ids

    @staticmethod
    def _outermost(fn: ast.FunctionDef) -> list[ast.Attribute]:
        """Attribute links that END a chain — `self._store.get` counts once (as an access to the store),
        not twice (also as an access to self)."""
        inner = {node.value for node in ast.walk(fn) if isinstance(node, ast.Attribute)}
        return [n for n in ast.walk(fn) if isinstance(n, ast.Attribute) and n not in inner]

    def _tally(
        self, fn: ast.FunctionDef, fields: dict[str, set[str]], scope: dict[str, set[str]]
    ) -> tuple[int, Counter[str]]:
        """(accesses on own object, {foreign class: accesses}) for one method."""
        own, foreign = 0, Counter[str]()
        for link in self._outermost(fn):
            receiver = link.value
            if Resolver.is_self_attr(receiver):  # self.field.<member> -> a use of the FIELD's type
                for name in fields.get(receiver.attr, set()):
                    foreign[name] += 1
            elif isinstance(receiver, ast.Name) and receiver.id == "self":  # self.<member> -> own state
                own += 1
            elif isinstance(receiver, ast.Name):
                for name in scope.get(receiver.id, set()):
                    foreign[name] += 1
        return own, foreign

    def violations(self) -> list[str]:
        """Every method more interested in one other class than in its own object."""
        out: list[str] = []
        for path, tree in Trees(self.packages).walk():
            scope_of_file = Resolver.scope_of(path, tree)
            for cls in Resolver.classes_in(tree):
                fields = Resolver.field_types(cls)
                for fn in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
                    params = {a.arg: Resolver.annotation_names(a.annotation) for a in fn.args.args}
                    own, foreign = self._tally(fn, fields, params)
                    site = MethodSite(path.as_posix(), cls.name, fn.name, fn.lineno)
                    out += self._verdict(site, own, foreign, scope_of_file)
        return sorted(out)

    def _verdict(self, site: MethodSite, own: int, foreign: Counter[str], scope: FileScope) -> list[str]:
        """The finding for one method, if any — judged against the single most-used foreign class."""
        return [
            site.describe(target, count, own)
            for name, count in foreign.items()
            if (target := self.resolver.resolve(name, scope)) is not None
            and count >= self.minimum
            and count > own
            and not self._is_satellite(target)
        ]

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        found = self.violations()
        return "\n".join([f"feature envy (floor {self.minimum}): {len(found)}", *found])

    def run_assert(self) -> int:
        """The gate: log envious methods and return an exit code."""
        found = self.violations()
        if found:
            log.error("feature envy — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("feature envy: clean (no method prefers another class, floor %d)", self.minimum)
        return 0


def main():
    Cli(
        FeatureEnvy,
        "Feature envy — a method more interested in another class than its own.",
        gate="exit 1 on an envious method",
    ).run()


if __name__ == "__main__":
    main()
