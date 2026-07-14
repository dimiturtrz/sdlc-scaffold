"""Fixtures for the devtools unit tests.

These test the LOGIC of the shipped fitness functions (LCOM4, data-clumps, namespace-state, the
arch-fitness gate) — the guardrails' own guardrails. To test the artifact AS SHIPPED, a session
fixture generates a full instance with copier and imports `devtools.*` from it (the tools ship
verbatim, so the generated copy is byte-identical to template/devtools/). The low-level scaffold
helpers are reused from the E2E conftest — no duplication.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# Reuse the E2E suite's scaffold+generate helpers. Loaded explicitly under a distinct module name so it
# does not collide with this file (both are basename `conftest`).
_E2E_CONFTEST = Path(__file__).resolve().parents[1] / "e2e" / "conftest.py"
_spec = importlib.util.spec_from_file_location("e2e_conftest", _E2E_CONFTEST)
_e2e = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_e2e)
COMBOS, generate, make_scaffold = _e2e.COMBOS, _e2e.generate, _e2e.make_scaffold


@pytest.fixture(scope="session")
def devtools(tmp_path_factory):
    """Import the four devtools modules from a freshly generated FULL instance."""
    scaffold = tmp_path_factory.mktemp("dt_scaffold")
    make_scaffold(scaffold)
    instance = tmp_path_factory.mktemp("dt_instance") / "proj"
    generate(scaffold, instance, COMBOS["full"])
    sys.path.insert(0, str(instance))
    import devtools.analytics as analytics
    import devtools.data_clumps as data_clumps
    import devtools.graph as graph
    import devtools.lcom as lcom
    import devtools.magic_literals as magic_literals
    import devtools.omit as omit
    import devtools.shape_contracts as shape_contracts
    import devtools.state_candidates as state_candidates

    return {
        "lcom": lcom,
        "data_clumps": data_clumps,
        "state_candidates": state_candidates,
        "graph": graph,
        "omit": omit,
        "magic_literals": magic_literals,
        "analytics": analytics,
        "shape_contracts": shape_contracts,
    }
