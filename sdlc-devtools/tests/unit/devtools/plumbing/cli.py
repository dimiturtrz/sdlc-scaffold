"""Unit tests for devtools/cli.py — the shared argparse/dispatch plumbing (bd 0y9).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour. `Flag.add_to` and
`Switch.add_to` share a name across two classes, so both carry the qualified `test_<class>_<method>` form.
"""

import argparse
import logging

import pytest

from devtools.plumbing.cli import Cli, Flag, Switch
from devtools.primitives.arrows import ClassArrows  # a REAL in-package engine, for the subpackage-path proof


class Fake:
    """A stand-in engine: the Cli's whole contract is construction-from-packages plus report/run_assert."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def report(self, top: int = 7) -> str:
        return f"report {self.packages} top={top}"

    def run_assert(self, test_mirror: bool = True) -> int:
        return 0 if test_mirror else 3


class Explorer:
    """An engine with no gate — the majority case."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def report(self) -> str:
        return f"explored {self.packages}"


def test_flag_add_to():
    """A VALUE option reaches argparse with its own correctly-typed call.

    The two flag shapes exist because `add_argument` is overloaded — `type=` is REJECTED alongside a
    store_false action — so this asserts the half that carries `type` and `default`, and
    `test_switch_add_to` asserts the half that cannot. Coercion is the load-bearing bit: a `--top` arriving
    as the string "5" would reach an engine expecting an int and fail somewhere far from here.
    """
    parser = argparse.ArgumentParser()
    Flag("--top", "rows", type=int, default=3).add_to(parser)
    assert parser.parse_args(["--top", "5"]).top == 5, "the value is coerced by `type`, not left a string"
    assert parser.parse_args([]).top == 3, "the declared default stands when the flag is absent"
    assert "rows" in parser.format_help(), "the help text reaches --help"


def test_switch_add_to():
    """A boolean OFF-switch, whose `dest` is the PARAMETER it feeds.

    `--no-test-mirror` with `dest="test_mirror"` keeps the documented spelling while matching
    `run_assert(test_mirror=...)`. The default-True assertion is the point: a store_false flag that
    defaulted False would silently disable the thing it exists to let you disable.
    """
    parser = argparse.ArgumentParser()
    Switch("--no-mirror", "skip the mirror check", dest="test_mirror").add_to(parser)
    assert parser.parse_args([]).test_mirror is True, "not passing the OFF-switch leaves the feature ON"
    assert parser.parse_args(["--no-mirror"]).test_mirror is False, "and passing it turns the feature off"


def test_parser():
    """The parser's SHAPE: packages required, the gate flag declared only when a gate exists, flags wired.

    The `--assert` check is matched on the USAGE line, not anywhere in the help: the packages help text
    itself mentions `--assert` (explaining why a no-arg run would pass vacuously), so a bare substring
    search finds it in every parser and would assert nothing.
    """
    explorer = Cli(Explorer, "d").parser()
    assert "[--assert]" not in explorer.format_usage(), "an explorer must not advertise a gate it cannot honour"
    assert "[--assert]" in Cli(Fake, "d", gate="g").parser().format_usage()
    assert explorer.parse_args(["pkg", "other"]).packages == ["pkg", "other"], "packages is variadic"
    with pytest.raises(SystemExit):
        explorer.parse_args([])  # >=1 required — a no-arg run would scan nothing
    with_flags = Cli(Fake, "d", gate="g", flags=(Flag("--top", "rows", type=int),)).parser()
    parsed = with_flags.parse_args(["pkg", "--top", "2", "--assert"])
    assert (parsed.top, parsed.assert_) == (2, True), "declared flags and the gate flag coexist"


def _fn(top: int = 1, test_mirror: bool = True) -> None: ...


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"top": 5}, {"top": 5}),
        # `None` means the flag was NOT passed. Forwarding it would override the engine's own default with
        # nothing, which is how --min-clump once reached range() as None and crashed.
        ({"top": None}, {}),
        # A value the method does not declare belongs to the OTHER method — routing by signature is what
        # keeps the dispatch if-free, so an unknown name must be dropped rather than passed through.
        ({"nope": 5}, {}),
        ({"top": 5, "test_mirror": False, "nope": 1, "other": None}, {"top": 5, "test_mirror": False}),
        # `False` and `0` are PASSED values, not absent ones — filtering on falsiness instead of `is None`
        # would make every OFF-switch unreachable.
        ({"test_mirror": False, "top": 0}, {"test_mirror": False, "top": 0}),
        ({}, {}),
    ],
)
def test_accepted(values, expected):
    assert Cli.accepted(_fn, values) == expected


def test_run(caplog):
    """Parse, dispatch, exit — over both engine shapes and both branches.

    Routing is by SIGNATURE, which is what keeps the dispatch free of per-engine branching: `--top` is a
    report() parameter and `--no-mirror` a run_assert() one, and neither leaks into the other.
    """
    # A no-arg run would scan nothing and pass `--assert` VACUOUSLY — the worst outcome a gate has: green
    # because it looked at nothing.
    with pytest.raises(SystemExit):
        Cli(Explorer, "d").run([])

    with caplog.at_level(logging.INFO):
        Cli(Explorer, "d").run(["pkg"])
    assert "explored ['pkg']" in caplog.text, "the report is logged under the tool name"

    # `--assert` propagates run_assert's int, so the runner's exit code is the engine's verdict.
    with pytest.raises(SystemExit) as exit_info:
        Cli(Fake, "d", gate="g").run(["pkg", "--assert"])
    assert exit_info.value.code == 0

    flags = (Flag("--top", "rows", type=int), Switch("--no-mirror", "skip the mirror check", dest="test_mirror"))
    with pytest.raises(SystemExit) as exit_info:
        Cli(Fake, "d", gate="g", flags=flags).run(["pkg", "--assert", "--no-mirror"])
    assert exit_info.value.code == 3, "run_assert must receive test_mirror=False, and --top must not reach it"

    caplog.clear()
    with caplog.at_level(logging.INFO):
        Cli(Fake, "d", flags=(Flag("--top", "rows", type=int),)).run(["pkg"])
    assert "top=7" in caplog.text, "the engine's own default must survive an unpassed flag"

    caplog.clear()
    with caplog.at_level(logging.INFO):
        Cli(Fake, "d", flags=(Flag("--top", "rows", type=int),)).run(["pkg", "--top", "2"])
    assert "top=2" in caplog.text, "and a passed flag wins"


def test_tool():
    """The short name every log line is emitted under, resolved from the engine's FILE.

    `tool` and `prog` are PROPERTIES, read as attributes rather than called. They were once covered by a
    single `test_prog_names_the_documented_invocation`, on the grounds that the method-mirror gate exempted
    properties by kind; it no longer does — a property is public API, matched by attribute ACCESS — so the
    pair is split into one test per member.

    The expected value is `cli` because `Fake` is defined in THIS file, and under the mirror layout
    (bd 1a8) this file is `cli.py`.
    """
    assert Cli(Fake, "d").tool == "cli"
    assert Cli(Explorer, "d").tool == "cli", "the tool is the engine's file, not the engine's name"


def test_prog():
    """The invocation the `--help` header advertises, resolved from the engine's FILE and not `__module__`.

    Under `python -m devtools.x` the module is re-loaded as `__main__`, so deriving this from `__module__`
    would advertise an invocation that does not exist and label every log line `__main__`. It used to read
    `devtools.test_cli` — a module that has never existed, asserted as correct only because the prefix made
    the mirror's name differ from its subject's.
    """
    assert Cli(Fake, "d").prog.endswith(Cli(Fake, "d").tool), "prog is the tool, spelled as a runnable command"
    # A stand-in defined in this test file sits OUTSIDE the package, so it exercises the stem FALLBACK.
    assert Cli(Fake, "d").prog == "python -m devtools.cli"
    # A REAL in-package engine exercises the path resolution: an engine in a SUBPACKAGE keeps its segment,
    # so the header advertises the invocation that actually runs (bd yfv.2) rather than dropping to the bare
    # module name — which would print `python -m devtools.arrows` for a tool that now answers only at
    # `devtools.primitives.arrows`.
    assert Cli(ClassArrows, "d").tool == "primitives.arrows"
    assert Cli(ClassArrows, "d").prog == "python -m devtools.primitives.arrows"
