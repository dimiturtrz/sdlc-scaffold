"""One process for the whole gate set, instead of one process per gate (bd f9y.3).

MEASURED on cardiac-seg (102 files): each gate costs ~0.32s to start a process, ~0.19s to import devtools
and ~0.15s to actually analyse. A lint run fires about twelve of them, so ~6s goes on startup against ~1.3s
of work — analysis is roughly a quarter of what a gate costs. That ratio is why the Rust question (bd
f9y.4) is filed at P4: rewriting the analysers attacks the 1.3s and leaves the 6s untouched.

This runs the same engines in ONE interpreter: one process, one `import devtools`, and one parse of the
source tree shared between every engine that resolves names (bd 5cg). It is only possible because 0y9 gave
every engine the same two verbs — `report() -> str` and `run_assert() -> int` — so a runner can drive them
without knowing which is which.

MECHANISM, NOT POLICY. Which engines gate and which merely report is a per-repo decision that already
lives in the runner config: `classes` is advisory everywhere, `envy` blocks, `shape_contracts` is wired
ML-only. So this takes explicit `--gate` and `--report` lists rather than inferring intent from whether an
engine happens to own a `run_assert`. Nothing here decides what a project enforces.

EVERY ENGINE RUNS, even after one fails. Twelve chained `session.run` calls stop at the first red, so a
commit that breaks three gates is discovered three times; here the exit code is the OR of all of them and
the report is complete.


`python -m devtools.<tool> [--assert]` is unchanged and remains the documented contract — this is an
ADDITION for runners to call, not a replacement (it is pinned in consumers and wired into every template).
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from functools import cached_property
from typing import cast

from devtools import Engine, Gate, plumbing
from devtools.plumbing.cli import ENGINE_LOG_FORMAT
from devtools.plumbing.resolve import Resolver

log = logging.getLogger("devtools.run")

# Shared machinery with no findings of its own — not an engine under ANY reading. WALKED from the plumbing
# subpackage rather than hand-listed (bd 2wt): the folder is the authority, so the set is a fact about the
# tree and cannot drift from it. The literal it replaced was hand-edited for `layout` during PR #30, and
# forgetting it would have made the interface test demand an engine's verbs of a config strategy — the exact
# silent disagreement between a list and the tree the folder move removes. `test_engine_interface` imports
# this (one home) rather than keeping a copy.
PLUMBING = frozenset(info.name for info in pkgutil.iter_modules(plumbing.__path__))


@dataclass(frozen=True)
class Result:
    """What one engine did: its findings as text, and the exit code a gate returned (0 for a report).

    Kept as a value rather than printed on the spot so the runner can finish every engine before deciding
    the overall verdict — the whole point of not short-circuiting.
    """

    name: str
    text: str
    code: int


class Batch:
    """Runs many engines in one process, over one shared parse of the source tree."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    @staticmethod
    def engine_class(module_name: str) -> type:
        """The engine class a devtools module owns — the one DEFINED there that answers the ENGINE CONTRACT.

        Two filters, and the second was missing. `graph` imports several sibling engine classes, so the
        class must be defined HERE. But a module also legitimately defines SATELLITES — `calls` has
        `CallEdge` and `CallSite` beside `CallArrows` — and `getmembers` returns them sorted by NAME, so
        "the first one defined here" was really "the alphabetically first one". `calls` resolved correctly
        only because `CallArrows` happens to sort before `CallEdge`; adding a `Coverage` dataclass to
        `mirror` made the runner pick it over `MethodMirror` and the whole gate silently stopped being an
        engine. Selecting on the CONTRACT — it answers `report` — is what the runner actually means, and it
        does not depend on what anyone names a value object next year.
        """
        module = importlib.import_module(f"devtools.{module_name}")
        defined = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__ and not obj.__name__.startswith("_")
        ]
        return next((obj for obj in defined if callable(getattr(obj, "report", None))), defined[0])

    @staticmethod
    def names(value: str | None) -> list[str]:
        """A comma-separated engine list, empty when the flag was not passed."""
        return [n for n in (value or "").split(",") if n]

    @cached_property
    def resolver(self) -> Resolver:
        """Built once, and only if something asks for it — a run of purely line-level engines never pays
        to parse the tree for name resolution it will not use.

        `cached_property` rather than a hand-rolled `if self._resolver is None` memo: the lazy read was
        the first thing `devtools.coupling.purity` flagged when it was written, and it was right. The descriptor
        does the caching, so the property itself stays a pure read.
        """
        return Resolver(self.packages)

    def build(self, name: str) -> object:
        """Construct one engine, handing it the shared parse if its signature says it can use one.

        Routed by SIGNATURE, the same trick `Cli` uses to dispatch flags: an engine that resolves names
        declares `resolver`, one that only walks the source declares `trees`, and one that needs neither
        declares neither. So sharing costs no per-engine branching here and no coordination there.
        """
        cls = self.engine_class(name)
        parameters = inspect.signature(cls.__init__).parameters
        if "resolver" in parameters:
            return cls(self.packages, resolver=self.resolver)
        if "trees" in parameters:
            return cls(self.packages, trees=self.resolver.trees)
        return cls(self.packages)

    # Named `run_gate` / `run_report` rather than `gate` / `report`, because a method called `report` HERE
    # collides with the engine verb: it made the runner read as an engine to two different checks — the
    # interface test passed it by coincidence, and class-roles filed Batch as a satellite of its own
    # Protocol. The runner runs engines; it is not one.
    def run_gate(self, name: str) -> Result:
        """Run one engine as a GATE — its `run_assert` verdict becomes the exit code.

        The cast is the seam between a name and a type: what `--gate x` guarantees is enforced at RUNTIME by
        test_engine_interface, which asserts every engine shipping a gate owns `run_assert`. Naming an
        engine that has none fails loudly here rather than being silently skipped.
        """
        return Result(name, "", cast(Gate, self.build(name)).run_assert())

    def run_report(self, name: str) -> Result:
        """Run one engine as an EXPLORER — findings only, never a verdict."""
        return Result(name, cast(Engine, self.build(name)).report(), 0)

    def run(self, gates: list[str], reports: list[str]) -> list[Result]:
        """Every engine, in order, regardless of failures. A gate that raises is a FAILURE, not a crash of
        the whole run: one engine hitting an unparseable file must not hide the verdicts of the other
        eleven, which is exactly what a chain of separate processes did."""
        return [self._guarded(n, self.run_report) for n in reports] + [self._guarded(n, self.run_gate) for n in gates]

    @staticmethod
    def _guarded(name: str, run: Callable[[str], Result]) -> Result:
        try:
            return run(name)
        except Exception as error:  # noqa: BLE001 — one engine's crash must not mask eleven other verdicts
            log.error("%s: FAILED to run — %s", name, error)
            return Result(name, "", 1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m devtools.run",
        description="run many devtools engines in ONE process, sharing a single parse of the tree",
    )
    parser.add_argument("packages", nargs="+", help="root packages to scan (>=1 required)")
    parser.add_argument("--gate", help="comma-separated engines to run as GATES (their verdict sets the exit code)")
    parser.add_argument("--report", help="comma-separated engines to run as EXPLORERS (findings only, never fail)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format=ENGINE_LOG_FORMAT)

    batch = Batch(args.packages)
    results = batch.run(Batch.names(args.gate), Batch.names(args.report))
    for result in (r for r in results if r.text):
        log.info("--- %s ---\n%s", result.name, result.text)
    if failed := [r.name for r in results if r.code]:
        log.error("BLOCKING (%d): %s", len(failed), ", ".join(failed))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
