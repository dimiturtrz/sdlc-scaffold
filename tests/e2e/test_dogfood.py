"""Dogfood — the scaffold's own devtools engines meet the bar they enforce (bd dud).

Scaffold-side ONLY: the engines are template-owned, so this is the one place they're editable + fixable
(a generated project can't act on a finding in template-owned code, and bd 0lh keeps devtools tests out of
consumers). Applicable subset for a bag of single-file CLI tools: ruff + graph (god-module / cycle /
god-file) + magic-literals. DELIBERATELY NOT run: ast-grep class-shape (the engines are module-level
`main()` + functions BY DESIGN — the same house-gate-vs-mandated-pattern conflict as bd 8ex), test-mirror
(devtools are tested as one bundle in test_devtools.py, not per-engine — hence `graph --no-test-mirror`),
and jscpd (its config is shaped for a generated project root; DRY across independent CLIs is low-value).
"""

import subprocess

import pytest

from conftest import REPO, RUFF, SELECT, run

pytestmark = pytest.mark.slow

TEMPLATE = REPO / "template"
# ceiling for magic-literals: standalone engines legitimately repeat a few literals that can't be DRY'd
# without a shared module (which would break the single-file-per-tool design) — 'utf-8' (read_text encoding),
# 'packages' (the shared CLI arg name), 'tool' (pyproject section). Freeze that floor; a 4th distinct
# recurring literal bites.
MAGIC_MAX_STRINGS = "3"
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
    # god-module / import-cycle / god-file — but NOT test-mirror (bundle-tested, 0lh): --no-test-mirror.
    _engine("devtools.graph", "devtools", "--assert", "--no-test-mirror")


def test_devtools_magic_under_ceiling():
    _engine(
        "devtools.magic_literals",
        "devtools",
        "--max-strings",
        MAGIC_MAX_STRINGS,
        "--max-key-sets",
        MAGIC_MAX_KEY_SETS,
    )
