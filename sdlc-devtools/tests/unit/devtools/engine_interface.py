"""The interface every analyzer answers to — the invariant that makes a shared CLI possible (bd 0y9).

Each engine had grown its own answer to "how do I report" and "how do I gate", so `main()` became the place
the missing interface got improvised, seventeen times. Extracting a CLI without settling this would only
relocate the improvisation, so this pins the contract instead:

  report()      -> str   every engine, computing its own findings
  run_assert()  -> int   every engine that ships a --assert flag

The second line is the sharp one. `shape_contracts` shipped `--assert` while gating INLINE in main(), so
the one thing every other gate exposes as a method was, there, reachable only by running the CLI.
"""

import importlib
import inspect
import pkgutil

import pytest

import devtools
from devtools.run import PLUMBING, Batch


# What is exempt from the report()/run_assert() CONTRACT — DERIVED, not listed (bd yfv.1). Enginehood is a
# property of the class: a module is bespoke exactly when the class the runner would drive answers no
# `report()`. `config` prints a packaged path, `archmap` writes files, `run` is the RUNNER (its `Batch` has
# `run_report`, not `report`) — none owns the verb, so the code says so and no hand-list can omit a new one.
#
# This is deliberately NOT run.py's other question, "can I construct it as Engine(packages)". `analytics` is
# the case that separates them: its `__init__(repo, areas)` is unconstructable by a batch run, yet it HONOURS
# the contract with a real `report()` — so it is NOT bespoke and is held to the contract HERE. The
# constructability axis was a dead, self-inconsistent literal in run.py (it listed archmap/run, which DO take
# packages) and was removed; the only axis with a consumer is this one.
def _bespoke(name: str) -> bool:
    return not callable(getattr(Batch.engine_class(name), "report", None))


def _main_modules():
    """Every module owning a `main()`, at ANY depth — the candidate engines. Discovery recurses because the
    engines no longer all live at the top level: `primitives/` (bd yfv.2) holds three that ARE engines, so a
    top-level-only walk would silently drop them from the contract check. `plumbing/` holds none (machinery,
    no CLI), so the `main()` test excludes it for free — no name has to. The yielded name is dotted under
    `devtools` (`primitives.arrows`), exactly what `Batch.engine_class` re-imports and the invocation prints.
    """
    for info in pkgutil.walk_packages(devtools.__path__, prefix="devtools."):
        if info.ispkg:
            continue
        module = importlib.import_module(info.name)
        if hasattr(module, "main"):
            yield info.name.removeprefix("devtools."), module


def _engine_modules():
    return ((name, module) for name, module in _main_modules() if not _bespoke(name))


def _engine_class(module):
    """The module's engine class, resolved by the RUNNER's own rule (`Batch.engine_class`).

    This used to be a second copy of that logic, and the copies disagreed the moment `mirror` grew a
    `Coverage` dataclass: both picked "the alphabetically first class defined here", so both picked the
    value object, and this file then reported that `mirror` had no `report()`. The runner would have driven
    the wrong class in production for the same reason.

    Shared for the same reason `PLUMBING` is: "which class is the engine" is ONE question, and a test that
    answers it differently from the runner is testing something the runner does not do.
    """
    return Batch.engine_class(module.__name__.removeprefix("devtools."))


ENGINES = sorted(_engine_modules())


def test_the_engine_set_is_not_empty():
    """Guards the discovery itself: a broken filter would make every test below vacuously pass."""
    assert len(ENGINES) >= 10, f"expected the full analyzer set, found {[n for n, _ in ENGINES]}"


def test_plumbing_holds_no_engines():
    """The counterpart to the primitives move (bd 2wt / yfv.2): the `plumbing/` subpackage is machinery, so
    a module misfiled there would be skipped by discovery and by every gate the runner drives, silently. None
    of it may own a `main()`. PLUMBING is the derived membership set (run.py walks the folder), consumed here
    so the folder's promise — "no engines live here" — is a checked invariant, not a naming convention."""
    for name in PLUMBING:
        module = importlib.import_module(f"devtools.plumbing.{name}")
        assert not hasattr(module, "main"), f"plumbing/{name} owns a main() — it is an engine, misfiled"


def test_the_bespoke_set_is_exactly_the_known_three():
    """The DERIVED exemption must not silently grow (bd yfv.1). Deriving bespoke from "answers no report()"
    means an engine that LOSES its report() would drop out of the tested set as bespoke rather than fail —
    so this pins the only three modules allowed to be contract-exempt. A fourth is a loud failure here, not a
    silent skip: the literal survives as this guard, which is the whole value the hand-list used to carry."""
    bespoke = sorted(name for name, _ in _main_modules() if _bespoke(name))
    assert bespoke == ["graph.archmap", "run", "tools.config"], (
        f"the contract-exempt set changed to {bespoke}; a new module answering no report() is either a real "
        f"bespoke tool (add it here) or an engine that lost its contract (a bug this test exists to catch)"
    )


@pytest.mark.parametrize(("name", "module"), ENGINES, ids=[n for n, _ in ENGINES])
def test_every_engine_reports(name, module):
    """`report() -> str`, computing its own findings.

    Four engines used to expose a STATIC `report(rows)` taking rows the caller had already computed, and
    seven an instance `report(self)`. Two shapes for one question is exactly what stopped a shared runner
    from existing; `_render(rows)` survives as the private formatter.
    """
    engine = _engine_class(module)
    report = getattr(engine, "report", None)
    assert callable(report), f"{name}: no report()"
    params = list(inspect.signature(report).parameters)
    assert params and params[0] == "self", f"{name}: report() must be an instance method, got {params}"


@pytest.mark.parametrize(("name", "module"), ENGINES, ids=[n for n, _ in ENGINES])
def test_every_gate_engine_exposes_its_gate(name, module):
    """An engine shipping `--assert` must expose `run_assert() -> int`.

    Derived from the module's own source rather than a hand-kept list, so a new gate cannot be added with
    its verdict trapped inside main() the way shape_contracts' was.
    """
    source = inspect.getsource(module)
    # Two spellings because the migration to the shared Cli is what MOVED the flag: a converted engine
    # declares `gate="..."` and the literal "--assert" now lives in cli.py. Detecting only the literal made
    # a converted gate look like an explorer and skip its own contract — silently, which is the failure
    # mode this whole file exists to prevent.
    if '"--assert"' not in source and "gate=" not in source:
        pytest.skip(f"{name} ships no --assert flag")
    engine = _engine_class(module)
    assert callable(getattr(engine, "run_assert", None)), f"{name}: ships --assert but has no run_assert()"
