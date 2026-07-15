"""Shared devtools primitives: the package-tree AST walk and the pyproject `[tool.*]` reader, factored
out of the individual engines. Every scanning engine previously re-globbed `*.py` + re-parsed each file,
and every config-driven one re-opened pyproject — one home each for 'iterate the source' and 'read my
config section', so the walk/read logic lives in exactly one place (DRY across the eight engines)."""

from __future__ import annotations

import ast
import logging
import tomllib
from collections.abc import Iterator
from pathlib import Path


class Trees:
    """The source-tree AST walk shared by every engine that scans packages (one glob+parse home)."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def walk(self) -> Iterator[tuple[Path, ast.Module]]:
        """(path, parsed-AST) for every `*.py` under each root package, sorted within a package."""
        for pkg in self.packages:
            for path in sorted(Path(pkg).rglob("*.py")):
                yield path, ast.parse(path.read_text(encoding="utf-8"))

    def files(self) -> list[Path]:
        """Every `*.py` path under the root packages (no parse) — for line-count / path-only scans."""
        return [p for pkg in self.packages for p in sorted(Path(pkg).rglob("*.py"))]


class Pyproject:
    """Reader for a `[tool.<section>]` table from pyproject.toml — the shared config-load primitive."""

    @staticmethod
    def tool_section(section: str, pyproject: str = "pyproject.toml") -> dict:
        """The `[tool.<section>]` table (empty dict if the file or section is absent). One config home."""
        p = Path(pyproject)
        if not p.exists():
            return {}
        return tomllib.loads(p.read_text(encoding="utf-8")).get("tool", {}).get(section, {})


class Ratchet:
    """Freeze-the-floor gate over named integer counts — the reusable core behind every count-based gate.

    A count's current floor is frozen as a per-repo ceiling FACT (`[tool.<section>] max_<name>`); a NEW item
    that pushes the count OVER the ceiling fails the merge; the escape hatch is raising the ceiling in the
    same commit with a reason. No ceiling (key/section/file absent -> None) means that axis is ADVISORY —
    reported, never bites. `magic_literals` was the first user (strings/key_sets); the OSS survey found NO
    tool that ratchets, so wrapping best-of-breed counts (deptry unused/missing, radon complexity) in this
    primitive is the integration play (bd 85l). Adding a count-based gate is then ~3 lines, not a re-paste
    of ceiling plumbing."""

    def __init__(self, section: str, pyproject: str = "pyproject.toml") -> None:
        self.section = section
        self.pyproject = pyproject

    def ceilings(self, names: list[str]) -> dict[str, int | None]:
        """The `max_<name>` ceiling FACT per axis (None when the key/section/file is absent -> advisory)."""
        cfg = Pyproject.tool_section(self.section, self.pyproject)
        return {name: cfg.get(f"max_{name}") for name in names}

    @staticmethod
    def resolve(ceilings: dict[str, int | None], overrides: dict[str, int | None]) -> dict[str, int | None]:
        """Per-axis ceiling with a CLI override winning over the pyproject FACT (a None override keeps the FACT)."""
        return {n: (overrides.get(n) if overrides.get(n) is not None else c) for n, c in ceilings.items()}

    @staticmethod
    def breaches(counts: dict[str, int], ceilings: dict[str, int | None]) -> list[str]:
        """The `<axis> count > ceiling` messages, one per breached axis; empty when all under or advisory."""
        return [
            f"{name} {counts.get(name, 0)} > {ceiling}"
            for name, ceiling in ceilings.items()
            if ceiling is not None and counts.get(name, 0) > ceiling
        ]

    def enforce(self, counts: dict[str, int], overrides: dict[str, int | None], log: logging.Logger) -> None:
        """Full gate: resolve CLI>FACT ceilings and, on any breach, log the error + raise SystemExit(1).

        Advisory-safe: with no ceilings set (all None) there are no breaches, so it returns silently and the
        caller's report is the whole output. Call AFTER emitting the ranked report."""
        resolved = self.resolve(self.ceilings(list(counts)), overrides)
        if over := self.breaches(counts, resolved):
            log.error(
                "%s ratchet exceeded (%s) — reduce the count or raise the ceiling with a reason",
                self.section,
                "; ".join(over),
            )
            raise SystemExit(1)
