"""The vocabulary every analyzer in this package speaks.

An ENGINE answers at most two questions, and `test_engine_interface.py` enforces that across the package:

    report()     -> str   every engine, computing its own findings
    run_assert() -> int   every engine that ships a gate

Declared at the package ROOT rather than inside any one module because no single producer owns it —
seventeen engines speak it, `cli.py` invokes it one engine at a time, and `run.py` drives it across many.
That is the house definition of shared vocabulary, as opposed to a leftovers module named for the KIND of
thing it holds.

A GATE EXTENDS AN ENGINE rather than sitting beside it. Every engine reports; a gate is one that also
carries a verdict. Written first as two independent Protocols, which the class-roles gate correctly read as
two competing subjects in one file — and it was right about the modelling, not merely about the count: the
halves are not peers, one is a specialisation of the other, and inheritance says so. A single Protocol
carrying both would be the opposite error, promising a `run_assert` that explorers do not own.

`cli.py` still declines to restate this in its own dispatch, and that is still right there — it never
touches the returned object, so a Protocol would be documentation wearing a type's clothes. `run.py` DOES
touch it: it builds an engine from a NAME, so without a declared contract a checker sees `object` and
cannot verify the two calls the runner exists to make.
"""

from typing import Protocol


class Engine(Protocol):
    """Computes its own findings and renders them. Every analyzer in the package is one."""

    def report(self) -> str: ...


class Gate(Engine, Protocol):
    """An engine that also returns a verdict — 0 clean, non-zero blocking."""

    def run_assert(self) -> int: ...
