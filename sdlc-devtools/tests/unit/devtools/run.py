"""Unit tests for devtools/run.py — the one-process batch runner (bd f9y.3).

The runner exists for a measured reason: a gate spends ~0.32s starting a process and ~0.19s importing
devtools against ~0.15s of analysis, so a twelve-gate run burns ~6s on startup for ~1.3s of work. These
tests pin the two properties that saving is made of — engines share ONE parse of the tree, and one engine
failing does not abandon the rest — plus the boundary that keeps the runner mechanism rather than policy.
"""

import pytest

from devtools.run import Batch, Result


class Resolving:
    """An engine that resolves names: it declares `resolver`, so the runner should hand it the shared one."""

    def __init__(self, packages: list[str], resolver=None) -> None:
        self.packages, self.resolver = packages, resolver

    def report(self) -> str:
        return "resolving"


class Walking:
    """An engine that only walks the source: it declares `trees`, not a resolver."""

    def __init__(self, packages: list[str], trees=None) -> None:
        self.packages, self.trees = packages, trees

    def report(self) -> str:
        return "walking"


class Plain:
    """An engine that needs neither — it must not be handed something it never asked for."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def report(self) -> str:
        return "plain"

    def run_assert(self) -> int:
        return 0


class Failing:
    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def report(self) -> str:
        return "failing"

    def run_assert(self) -> int:
        return 1


class Exploding:
    def __init__(self, packages: list[str]) -> None:
        self.packages = packages

    def report(self) -> str:
        raise RuntimeError("unparseable file")

    def run_assert(self) -> int:
        raise RuntimeError("unparseable file")


_FAKES = {"resolving": Resolving, "walking": Walking, "plain": Plain, "failing": Failing, "exploding": Exploding}


@pytest.fixture
def batch(monkeypatch):
    """A Batch whose engine lookup returns the fakes above, so these tests exercise the RUNNER rather than
    whichever real engines happen to be installed."""
    monkeypatch.setattr(Batch, "engine_class", staticmethod(_FAKES.__getitem__))
    return Batch(["pkg"])


# ---- the shared parse, which is the entire point ------------------------------------------------------


def test_every_resolving_engine_gets_the_same_resolver(batch):
    """THE performance claim, stated as an identity: two engines, one parse of the tree. If this ever
    returns two objects the runner still works and silently costs what twelve subprocesses did."""
    first, second = batch.build("resolving"), batch.build("resolving")
    assert first.resolver is second.resolver


def test_an_engine_that_walks_gets_the_trees_from_that_same_resolver(batch):
    """Routed by SIGNATURE, like Cli routes flags: `trees` and `resolver` are different needs, and an
    engine declares which it has. Sharing therefore costs no branching here and no coordination there."""
    assert batch.build("walking").trees is batch.resolver.trees


def test_an_engine_that_needs_neither_is_handed_neither(batch):
    """Passing a resolver to an engine that never declared one is how a keyword-argument error ships."""
    assert batch.build("plain").packages == ["pkg"]


def test_the_resolver_is_not_built_until_something_needs_it(batch):
    """A run of purely line-level engines must not pay to parse the tree for resolution it never uses.

    `resolver` is a `cached_property`, so "not built yet" IS the absence of its instance-dict entry —
    reading `batch.resolver` to check would build the thing the test is asserting was not built.
    """
    batch.build("plain")
    assert "resolver" not in batch.__dict__, "constructing a non-resolving engine parsed the tree anyway"


def test_the_resolver_is_built_once_and_reused(batch):
    """The other half of the same claim: every engine in a batch shares ONE parse of the source tree."""
    assert batch.resolver is batch.resolver


# ---- every engine runs, whatever the others do --------------------------------------------------------


def test_a_failing_gate_does_not_abandon_the_rest(batch):
    """Twelve chained `session.run` calls stop at the first red, so a commit breaking three gates is
    discovered three times. Here the run completes and the report is whole."""
    results = batch.run(["failing", "plain"], [])
    assert [r.name for r in results] == ["failing", "plain"]
    assert [r.code for r in results] == [1, 0]


def test_an_engine_that_raises_becomes_a_failure_not_a_crash(batch):
    """One unparseable file must not hide the verdicts of eleven other gates."""
    results = batch.run(["exploding", "plain"], [])
    assert [(r.name, r.code) for r in results] == [("exploding", 1), ("plain", 0)]


def test_a_report_never_fails_the_run(batch):
    """Explorers are advisory by definition — an engine listed under --report cannot set the exit code,
    which is what keeps `classes` advisory here while `envy` blocks."""
    results = batch.run([], ["failing"])
    assert results == [Result("failing", "failing", 0)]


def test_reports_and_gates_both_run(batch):
    results = batch.run(["plain"], ["resolving"])
    assert {r.name for r in results} == {"plain", "resolving"}


# ---- mechanism, not policy ----------------------------------------------------------------------------


def test_nothing_runs_unless_it_was_named(batch):
    """The runner never infers intent from whether an engine owns a `run_assert`. Which engines gate is a
    per-repo decision — `classes` is advisory everywhere, `shape_contracts` is wired ML-only — and it stays
    in the runner config rather than being guessed here."""
    assert batch.run([], []) == []


def test_the_engine_lookup_finds_the_class_the_module_owns():
    """Not monkeypatched: the real lookup, against a real module. `graph` imports several engine classes
    from its siblings, so a lookup that took the first class it found would return the wrong one."""
    assert Batch.engine_class("graph").__name__ == "ImportGraph"
    assert Batch.engine_class("demeter").__name__ == "Demeter"
