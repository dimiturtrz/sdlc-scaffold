"""Dogfood — the scaffold's own devtools engines meet the FULL bar they enforce (bd dud + vip 16y).

Scaffold-side ONLY: the engines are template-owned, so this is the one place they're editable + fixable
(a generated project can't act on a finding in template-owned code). As of v1.1.0 the engines are classes
with a thin `main()` (ast-grep clean) and carry per-engine mirror tests under template/tests/unit/devtools/
(test-mirror clean), so the dogfood runs the COMPLETE applicable gate set — ruff + graph (god-module /
cycle / god-file / TEST-MIRROR) + ast-grep class-shape + magic-literals — with NO carve-outs.

Still not run: jscpd (its config + threshold are shaped for a generated project root; DRY across the
handful of independent single-file CLIs is low-value, and the shared logic already lives in _common.py).
The class-shape smell explorers (lcom / data_clumps / state_candidates) are advisory everywhere by design,
so they are not a gate here either.
"""

import pytest

from conftest import REPO, RUFF, SELECT, run

pytestmark = pytest.mark.slow

TEMPLATE = REPO / "template"
# Magic-literal ceiling: after the _common.py extraction the engines legitimately repeat exactly two
# value-position tokens — 'utf-8' (read_text encoding, in _common + the two line/AST readers) and
# 'packages' (the shared CLI positional every engine's main() declares). Freeze that floor; a 3rd distinct
# recurring literal bites. ('tool' fell below threshold once the pyproject read moved into _common.)
MAGIC_MAX_STRINGS = "2"
MAGIC_MAX_KEY_SETS = "0"


def _engine(*args):
    """Invoke a devtools engine ON the template's own devtools/ — cwd=template so `devtools` imports, and
    --project points uv at the scaffold venv (grimp/networkx for graph)."""
    return run(
        ["uv", "run", "--project", str(REPO), "--group", "dev", "python", "-m", *args],
        TEMPLATE,
    )


def test_devtools_ruff_clean():
    # the engines meet the same enforced ruff union they impose (F722/F821 waived as jaxtyping would be,
    # though the engines carry no jaxtyping annotations — harmless, keeps the invocation identical to CI).
    run(["uvx", RUFF, "check", "devtools", "--select", SELECT, "--ignore", "F722,F821"], TEMPLATE)


def test_devtools_arch_fitness_clean():
    # god-module / import-cycle / god-file AND test-mirror — the FULL --assert (the engines now carry their
    # per-engine mirror tests, so the check that consumers get is the check the engines themselves pass).
    _engine("devtools.graph", "devtools", "--assert")


def test_devtools_class_shape_clean():
    # ast-grep house rule: every helper is a method on its engine class, only main() is a top-level function
    # (the engines obey the same in-a-class rule they impose). The config is valid YAML pre-render, so it
    # reads straight from the on-disk .jinja (no vars to interpolate).
    run(
        ["uvx", "--from", "ast-grep-cli", "ast-grep", "scan", "-c", "devtools/sgconfig.yml.jinja", "devtools"],
        TEMPLATE,
    )


def test_devtools_magic_under_ceiling():
    _engine(
        "devtools.magic_literals",
        "devtools",
        "--max-strings",
        MAGIC_MAX_STRINGS,
        "--max-key-sets",
        MAGIC_MAX_KEY_SETS,
    )
