"""Unit tests for devtools/cli.py — the shared argparse/dispatch plumbing (bd 0y9)."""

import logging

import pytest

from devtools.cli import Cli, Flag, Switch


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


def test_packages_are_required():
    """A no-arg run would scan nothing and pass `--assert` VACUOUSLY, which is the worst outcome a gate has:
    green because it looked at nothing."""
    with pytest.raises(SystemExit):
        Cli(Explorer, "d").run([])


def test_report_is_logged_under_the_tool_name(caplog):
    with caplog.at_level(logging.INFO):
        Cli(Explorer, "d").run(["pkg"])
    assert "explored ['pkg']" in caplog.text


def test_the_gate_exits_with_the_engines_code():
    """`--assert` propagates run_assert's int, so the runner's exit code is the engine's verdict."""
    with pytest.raises(SystemExit) as exit_info:
        Cli(Fake, "d", gate="g").run(["pkg", "--assert"])
    assert exit_info.value.code == 0


def test_a_flag_reaches_the_method_that_declares_it():
    """Routing is by SIGNATURE, which is what keeps the dispatch free of per-engine branching: `--top` is a
    report() parameter and `--no-mirror` a run_assert() one, and neither leaks into the other.

    Also covers the Flag/Switch split: a VALUE option and a boolean OFF-switch reach argparse through
    their own correctly-typed calls, because add_argument rejects `type=` alongside store_false."""
    flags = (
        Flag("--top", "rows", type=int),
        Switch("--no-mirror", "skip the mirror check", dest="test_mirror"),
    )
    with pytest.raises(SystemExit) as exit_info:
        Cli(Fake, "d", gate="g", flags=flags).run(["pkg", "--assert", "--no-mirror"])
    assert exit_info.value.code == 3, "run_assert must receive test_mirror=False"


def test_an_unpassed_flag_does_not_override_the_engine_default(caplog):
    """`None` means "not passed". Forwarding it would replace the engine's own default with nothing — which
    is exactly how `--min-clump` once reached range() as None and crashed."""
    with caplog.at_level(logging.INFO):
        Cli(Fake, "d", flags=(Flag("--top", "rows", type=int),)).run(["pkg"])
    assert "top=7" in caplog.text, "the engine's own default must survive an unpassed flag"


def test_a_passed_flag_wins(caplog):
    with caplog.at_level(logging.INFO):
        Cli(Fake, "d", flags=(Flag("--top", "rows", type=int),)).run(["pkg", "--top", "2"])
    assert "top=2" in caplog.text


def test_the_gate_flag_only_exists_when_a_gate_is_declared():
    """An explorer must not advertise a gate it cannot honour.

    Matched on the USAGE line, not anywhere in the help: the packages help text itself mentions `--assert`
    (explaining why a no-arg run would pass vacuously), so a bare substring search finds it in every parser.
    """
    assert "[--assert]" not in Cli(Explorer, "d").parser().format_usage()
    assert "[--assert]" in Cli(Fake, "d", gate="g").parser().format_usage()


def test_prog_names_the_documented_invocation():
    """Resolved from the engine's FILE: under `python -m devtools.x` the module is re-loaded as `__main__`,
    so deriving this from `__module__` would advertise an invocation that does not exist."""
    assert Cli(Fake, "d").prog == "python -m devtools.test_cli"
