"""One home for the argparse/dispatch plumbing every engine repeated (bd 0y9).

Seventeen engines each carried ~15 lines of ArgumentParser setup, a `packages` positional, `parse_args`,
`logging.basicConfig`, engine construction and a gate/report branch. That is ~200 lines saying the same
thing, and — worse than the duplication — each copy was free to say it slightly differently, which is how
`shape_contracts` ended up gating inline and four engines ended up with a static `report(rows)`.

The interface came first (see `test_engine_interface.py`); this is what it buys. An engine now declares
WHAT it offers and the Cli owns HOW it is invoked:

    Cli(Demeter, "Law of Demeter — reach-through chain depth.", gate="exit 1 on a reach-through").run()

The dispatch carries per-engine variation without an if-ladder (house rule: low ifs). Extra options are
declared as `Flag` DATA rather than branched on, and each parsed value is routed to whichever method
actually accepts it — so `--top` reaches `report(top=...)` and `--no-test-mirror` reaches
`run_assert(test_mirror=...)` with no engine-specific code here.

The engine contract itself (`report() -> str`, plus `run_assert() -> int` when a gate ships) is not
restated here as a Protocol: `test_engine_interface.py` ENFORCES it across the package, and a second
declaration nothing checks against would be documentation wearing a type's clothes.

The invocation contract is unchanged and load-bearing: `python -m devtools.<tool> [pkgs...] [--assert]` is
documented, wired into every template runner, and pinned in consumers. Each engine keeps its own module
entry point; only the plumbing is centralised.
"""

from __future__ import annotations

import argparse
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import devtools

ENGINE_LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"
PLAIN_LOG_FORMAT = "%(message)s"
_PACKAGES_HELP = "root packages to scan (>=1 required — a no-arg run would scan nothing and pass --assert vacuously)"


@dataclass(frozen=True)
class Flag:
    """A VALUE option — `--top 5`.

    Two flag shapes exist rather than one with optional everything, because argparse's `add_argument` is
    overloaded: `type=` is meaningless (and rejected) alongside a store_false action. Building one kwargs
    dict for both shapes meant a heterogeneous `dict[str, object]` that argparse's signature refuses and
    `Any` would have papered over — and Any is banned here. Two small types call add_argument with their
    OWN correctly-typed arguments, so the parser stays if-free AND checkable.
    """

    name: str
    help: str
    type: type = int
    default: object = None

    def add_to(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(self.name, help=self.help, type=self.type, default=self.default)


@dataclass(frozen=True)
class Switch:
    """A boolean option that turns something OFF — `--no-test-mirror`.

    `dest` names the PARAMETER it feeds, so the flag can read backwards from it: `--no-test-mirror` with
    `dest="test_mirror"` keeps the documented spelling while matching `run_assert(test_mirror=...)`.
    """

    name: str
    help: str
    dest: str

    def add_to(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(self.name, help=self.help, dest=self.dest, action="store_false")


class Cli:
    """The shared entry point: parse, build the engine, then either gate or report."""

    def __init__(
        self,
        engine: type,
        description: str,
        *,
        gate: str | None = None,
        flags: tuple[Flag | Switch, ...] = (),
        log_format: str = ENGINE_LOG_FORMAT,
    ) -> None:
        self.engine = engine
        self.description = description
        self.gate = gate
        self.flags: tuple[Flag | Switch, ...] = flags
        self.log_format = log_format

    @property
    def tool(self) -> str:
        """The engine's dotted module path UNDER `devtools`, resolved from its FILE rather than `__module__`.

        Running `python -m devtools.demeter` loads that module a SECOND time under the name `__main__`, so
        `__module__` reads `__main__` there — which would advertise an invocation that does not exist in
        `--help` and label every log line `__main__` instead of the tool that emitted it. The FILE is stable
        across that reload.

        Taken RELATIVE to the package root so a subpackage is not dropped: `primitives/arrows.py` resolves to
        `primitives.arrows`, which is what makes `python -m devtools.primitives.arrows` the invocation the
        help header prints and the logger name it stamps (bd yfv.2). An engine defined OUTSIDE the package —
        only a test fake — has no such path and falls back to the bare file stem.
        """
        file = Path(inspect.getfile(self.engine)).resolve()
        root = Path(devtools.__file__).resolve().parent
        try:
            return ".".join(file.relative_to(root).with_suffix("").parts)
        except ValueError:
            return file.stem

    @property
    def prog(self) -> str:
        """The documented invocation, so `--help` shows how the tool is really run."""
        return f"python -m devtools.{self.tool}"

    def parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.prog, description=self.description)
        parser.add_argument("packages", nargs="+", help=_PACKAGES_HELP)
        for flag in self.flags:
            flag.add_to(parser)
        if self.gate:
            parser.add_argument("--assert", action="store_true", dest="assert_", help=self.gate)
        return parser

    @staticmethod
    def accepted(method: Callable[..., object], values: dict[str, object]) -> dict[str, object]:
        """The subset of parsed values `method` actually takes.

        This is what keeps the dispatch if-free: an engine's flags are routed by the SIGNATURE that wants
        them, so `--top` lands on report() and `--no-test-mirror` on run_assert() with no per-engine code.
        """
        parameters = inspect.signature(method).parameters
        # `None` means the flag was not passed. Forwarding it would OVERRIDE the engine's own default
        # with nothing, which is how --min-clump reached range() as None.
        return {n: v for n, v in values.items() if n in parameters and v is not None}

    def run(self, argv: list[str] | None = None) -> None:
        """Parse, dispatch, exit. `--assert` returns the engine's exit code; otherwise the report is logged."""
        values = vars(self.parser().parse_args(argv))
        logging.basicConfig(level=logging.INFO, format=self.log_format)
        engine = self.engine(values.pop("packages"))
        if values.pop("assert_", False):
            raise SystemExit(engine.run_assert(**self.accepted(engine.run_assert, values)))
        report = engine.report(**self.accepted(engine.report, values))
        logging.getLogger(f"devtools.{self.tool}").info("%s", report)
