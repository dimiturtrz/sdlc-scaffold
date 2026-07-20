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

# Engines are the modules that expose a CLI. `config` prints a packaged path and `archmap` writes files —
# both are genuinely bespoke verbs rather than report/gate engines, so they are named here as decisions.
# `run` is the batch RUNNER, not an engine — it drives the others. It would pass the contract below by
# coincidence (`Batch.report(name)` is callable and takes self, while the contract means `report() -> str`),
# and a check that passes for the wrong reason is the thing this file exists to prevent.
BESPOKE = {"config", "archmap", "run"}
_INTERNAL = {"_common", "names", "trees", "pyproject", "resolve", "omit", "cli"}


def _engine_modules():
    for info in pkgutil.iter_modules(devtools.__path__):
        if info.name in _INTERNAL or info.name in BESPOKE:
            continue
        module = importlib.import_module(f"devtools.{info.name}")
        if hasattr(module, "main"):
            yield info.name, module


def _engine_class(module):
    """The module's engine class — the one defined HERE, not imported into it."""
    return next(
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if obj.__module__ == module.__name__ and not obj.__name__.startswith("_")
    )


ENGINES = sorted(_engine_modules())


def test_the_engine_set_is_not_empty():
    """Guards the discovery itself: a broken filter would make every test below vacuously pass."""
    assert len(ENGINES) >= 10, f"expected the full analyzer set, found {[n for n, _ in ENGINES]}"


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
