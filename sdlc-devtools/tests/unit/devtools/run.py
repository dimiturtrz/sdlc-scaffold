"""Unit tests for devtools/run.py — the one-process batch runner (bd f9y.3).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.

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


def test_engine_class():
    """Not monkeypatched: the real lookup, against real modules. `graph` imports several engine classes from
    its siblings, so a lookup that took the first class it found would return the wrong one — and the runner
    would silently drive somebody else's engine under this engine's name."""
    assert Batch.engine_class("graph").__name__ == "ImportGraph", "the class graph.py DEFINES, not one it imports"
    assert Batch.engine_class("demeter").__name__ == "Demeter"
    assert Batch.engine_class("data_clumps").__name__ == "DataClumps", "underscored module names resolve too"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("graph,demeter", ["graph", "demeter"]),
        ("graph", ["graph"]),
        # The flag not being passed is argparse's None, and a bare `--gate ""` is the same intent — both must
        # mean "no engines" rather than one engine named "", which `build` would then fail to import.
        (None, []),
        ("", []),
        # Trailing/duplicated separators come from shell-assembled lists in CI configs; empties are dropped
        # rather than carried through as a name that cannot resolve.
        ("graph,", ["graph"]),
        (",,graph,,demeter,", ["graph", "demeter"]),
        # Order is the RUN order — a config listing cheap gates first must not be reshuffled.
        ("demeter,graph", ["demeter", "graph"]),
    ],
)
def test_names(value, expected):
    assert Batch.names(value) == expected


def test_build(batch):
    """Construction routed by SIGNATURE — the mechanism the whole ~6s saving rests on.

    The order here is load-bearing. `resolver` is a `cached_property`, so "not built yet" IS the absence of
    its instance-dict entry; reading `batch.resolver` to check would build the very thing being asserted
    absent, so the non-resolving case has to run before anything touches it.
    """
    plain = batch.build("plain")
    assert plain.packages == ["pkg"], "an engine declaring neither is handed neither — a kwarg error otherwise"
    assert "resolver" not in batch.__dict__, "constructing a non-resolving engine parsed the tree anyway"

    # THE performance claim, stated as an identity: two engines, one parse. Two objects here and the runner
    # still works while silently costing what twelve subprocesses did.
    assert batch.build("resolving").resolver is batch.build("resolving").resolver
    assert batch.build("resolving").resolver is batch.resolver, "and it is the batch's own, not a fresh one"
    assert batch.build("walking").trees is batch.resolver.trees, "`trees` and `resolver` are different needs"
    assert not hasattr(batch.build("walking"), "resolver"), "a walker is not handed a resolver it never declared"
    assert batch.resolver is batch.resolver, "built once and reused — the descriptor does the caching"


def test_run_gate(batch):
    """A gate's VERDICT becomes the exit code and its text stays empty — the runner prints findings only for
    explorers, so a gate that also returned text would double-report what it already logged itself."""
    assert batch.run_gate("plain") == Result("plain", "", 0)
    assert batch.run_gate("failing") == Result("failing", "", 1)
    # Naming an engine with no `run_assert` fails LOUDLY rather than being skipped as a silent pass — the
    # cast is only a type-level promise, and the runtime guarantee is this raise.
    with pytest.raises(AttributeError):
        batch.run_gate("resolving")


def test_run_report(batch):
    """An explorer's findings are carried as text and its code is ALWAYS 0 — `failing` here owns a
    `run_assert` returning 1 and still reports clean, which is what keeps `classes` advisory while `envy`
    blocks. That decision lives in the runner config, never in whether an engine happens to own a verb."""
    assert batch.run_report("plain") == Result("plain", "plain", 0)
    assert batch.run_report("failing") == Result("failing", "failing", 0)
    assert batch.run_report("resolving") == Result("resolving", "resolving", 0), "a report needs no run_assert"


@pytest.mark.parametrize(
    ("gates", "reports", "expected"),
    [
        # Twelve chained `session.run` calls stop at the first red, so a commit breaking three gates is
        # discovered three times. Here the run completes and the report is whole.
        (["failing", "plain"], [], [Result("failing", "", 1), Result("plain", "", 0)]),
        # One unparseable file must not hide the verdicts of eleven other gates: a raise is a FAILURE.
        (["exploding", "plain"], [], [Result("exploding", "", 1), Result("plain", "", 0)]),
        # An explorer that raises fails the same way rather than aborting the run mid-list — the ONE case
        # where a --report engine can carry a non-zero code, because it never produced a verdict at all.
        ([], ["exploding", "plain"], [Result("exploding", "", 1), Result("plain", "plain", 0)]),
        # Reports run BEFORE gates, so the findings a reviewer reads are printed above the verdict.
        (["plain"], ["resolving"], [Result("resolving", "resolving", 0), Result("plain", "", 0)]),
        # Mechanism, not policy: nothing runs unless it was named, whatever verbs it owns.
        ([], [], []),
    ],
)
def test_run(batch, gates, reports, expected):
    assert batch.run(gates, reports) == expected


def test_run_completes_every_engine_in_one_call(batch):
    """The exit code a caller derives is the OR over the WHOLE list, not the first red it meets."""
    results = batch.run(["failing", "exploding", "plain"], ["resolving"])
    assert [r.name for r in results] == ["resolving", "failing", "exploding", "plain"]
    assert [r.name for r in results if r.code] == ["failing", "exploding"], "both reds survive to the verdict"
