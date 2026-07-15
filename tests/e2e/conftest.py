"""Shared helpers + fixtures for the scaffold E2E suite.

The suite treats the scaffold as a black box: it generates real projects with copier from the
current working-tree template, then runs every gate as a subprocess and asserts the outcome.
Runs on Linux/CI (matches the generated projects' `ubuntu-latest`); copier needs a git repo, so
each run builds a throwaway git repo from the on-disk template (testing what is on disk, not a tag).
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]  # tests/e2e/conftest.py -> scaffold root
sys.path.insert(0, str(REPO / "tests"))
from _meta import copier_default  # noqa: E402  (shared copier.yml reader, one home)

COPIER = "copier@9.16.0"
RUFF = f"ruff@{copier_default('ruff_version')}"
VULTURE = f"vulture@{copier_default('vulture_version')}"
NOX = f"nox@{copier_default('nox_version')}"
PRECOMMIT = f"pre-commit@{copier_default('precommit_version')}"
# deptry runs env-aware via `uv run --with` (PEP508 pin, not the uvx `@` form) so it reads installed metadata.
DEPTRY = f"deptry=={copier_default('deptry_version')}"
PIP_AUDIT = f"pip-audit=={copier_default('pip_audit_version')}"
# Curated-narrow select — single-sourced from copier.yml's `ruff_select` (must match the template).
SELECT = copier_default("ruff_select")

# Two representative points on the toggle lattice: the minimal mid-stage and the full cardioseg mirror.
COMBOS = {
    # The gates are always-on now (no toggles) — combos differ by domain (enable_ml) + naming. Both
    # exercise the full gate set; base = domain-neutral, full = ML.
    "base": {
        "project_name": "base",
        "packages": "base_pkg",
        "domain": "none",
        "coverage_floor": "80",
    },
    "full": {
        "project_name": "full",
        "packages": "full_pkg",
        "domain": "ml",
        "coverage_floor": "80",
    },
}


def example_pkg(combo_name):
    """First entry in `packages` — the package the e2e seeds its demo code into."""
    return COMBOS[combo_name]["packages"].split(",")[0].strip()


# The template ships ZERO code (bd r2w) — the e2e OWNS this demo and seeds it into a generated project so
# there is something for the gates to lint/test/graph. An astgrep-compliant leaf class + an intra-package
# edge + strict-mirror tests (so coverage floor + test-mirror pass).
_SEED = {
    "{pkg}/__init__.py": "",
    "{pkg}/math_ops.py": (
        "class MathOps:\n"
        "    @staticmethod\n"
        "    def mean(values: list[float]) -> float:\n"
        '        if not values:\n            msg = "mean() requires at least one value"\n            raise ValueError(msg)\n'
        "        return sum(values) / len(values)\n"
    ),
    "{pkg}/pipeline.py": (
        "from {pkg}.math_ops import MathOps\n\n\n"
        "class Pipeline:\n"
        "    @staticmethod\n"
        "    def doubled_mean(values: list[float]) -> float:\n"
        "        return MathOps.mean(values) * 2\n"
    ),
    "tests/unit/{pkg}/test_math_ops.py": (
        "import pytest\n\nfrom {pkg}.math_ops import MathOps\n\n\n"
        "def test_mean():\n    assert MathOps.mean([1.0, 3.0]) == 2.0\n\n\n"
        'def test_mean_empty():\n    with pytest.raises(ValueError, match="at least one value"):\n        MathOps.mean([])\n'
    ),
    "tests/unit/{pkg}/test_pipeline.py": (
        "from {pkg}.pipeline import Pipeline\n\n\ndef test_doubled_mean():\n    assert Pipeline.doubled_mean([1.0, 3.0]) == 4.0\n"
    ),
}


def seed_example(path, pkg):
    """Drop the demo package + its strict-mirror tests into a generated (code-less) project."""
    for rel, body in _SEED.items():
        target = path / rel.format(pkg=pkg)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.format(pkg=pkg), encoding="utf-8")


def run(cmd, cwd, *, check=True, env=None):
    """Run a subprocess, capturing output. On failure, surface stdout+stderr in the assertion."""
    result = subprocess.run(  # noqa: S603 (test infra: cmd is a controlled list, never shell/untrusted input)
        [str(c) for c in cmd],
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"command failed ({result.returncode}): {' '.join(map(str, cmd))}\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    return result


def has_node():
    return shutil.which("node") is not None and shutil.which("npx") is not None


def assert_bites(project, cmd, mutate):
    """Prove a gate BITES: `mutate(project)` injects a violation and returns a restore callable; run
    `cmd`; restore BEFORE asserting (so a failure can't leave a shared fixture dirty); assert non-zero."""
    restore = mutate(project)
    result = run(cmd, project, check=False)
    restore()
    assert result.returncode != 0, f"gate must FAIL after injection: {' '.join(map(str, cmd))}"
    return result


def layers(combo_name):
    return [p.strip() for p in COMBOS[combo_name]["packages"].split(",")]


def make_scaffold(dst: Path):
    """Build a throwaway git repo from the on-disk template so copier can version it."""
    for item in ["copier.yml", "ruff.toml", ".pre-commit-hooks.yaml", "_partials", "template"]:
        src = REPO / item
        if src.is_dir():
            shutil.copytree(src, dst / item)
        else:
            shutil.copy2(src, dst / item)
    run(["git", "init", "-q"], dst)
    run(["git", "config", "user.email", "e2e@test"], dst)
    run(["git", "config", "user.name", "e2e"], dst)
    run(["git", "add", "-A"], dst)
    run(["git", "commit", "-qm", "e2e-v0.1.0"], dst)
    run(["git", "tag", "v0.1.0"], dst)


def generate(scaffold: Path, out: Path, answers: dict):
    cmd = ["uvx", COPIER, "copy", "--defaults", "--trust"]
    for key, value in answers.items():
        cmd += ["--data", f"{key}={value}"]
    cmd += [str(scaffold), str(out)]
    run(cmd, cwd=out.parent)
    return out


def use_local_devtools(out: Path):
    """Point the generated project's `sdlc-devtools` git-dep at the WORKING-TREE package via a
    `[tool.uv.sources]` override, so `uv sync --extra devtools` builds the local package instead of
    fetching the (unpublished, at test time) scaffold tag from GitHub. What ships to a real consumer is
    the pure git pin; this override is test-only."""
    pkg = (REPO / "sdlc-devtools").as_posix()
    pyproject = out / "pyproject.toml"
    # editable=true: install from the live source tree (no built-wheel cache), so a working-tree edit to the
    # engines / config / sg-rules is always what the gates see — a non-editable path source can serve a
    # STALE cached wheel keyed on the unchanged version.
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + f'\n[tool.uv.sources]\nsdlc-devtools = {{ path = "{pkg}", editable = true }}\n',
        encoding="utf-8",
    )


def config_path(project: Path, name: str) -> str:
    """Resolve a packaged ast-grep/jscpd config path from the installed devtools package, as the gates do
    (`python -m devtools.config <name>`) — for the e2e's direct ast-grep/jscpd invocations."""
    return run(
        ["uv", "run", "-q", "--extra", "devtools", "python", "-m", "devtools.config", name], project
    ).stdout.strip()


def git_init_commit(path: Path):
    run(["git", "init", "-q"], path)
    run(["git", "config", "user.email", "e2e@test"], path)
    run(["git", "config", "user.name", "e2e"], path)
    run(["git", "add", "-A"], path)
    run(["git", "commit", "-qm", "gen"], path)


@pytest.fixture(scope="session")
def scaffold(tmp_path_factory):
    """One throwaway scaffold repo, reused by every read-only generation test."""
    dst = tmp_path_factory.mktemp("scaffold")
    make_scaffold(dst)
    return dst


@pytest.fixture(scope="session", params=list(COMBOS))
def project(request, scaffold, tmp_path_factory):
    """A generated (code-less) project SEEDED with the e2e's own demo, git-inited + uv-synced, per combo."""
    name = request.param
    out = tmp_path_factory.mktemp(f"proj_{name}")
    generate(scaffold, out, COMBOS[name])
    seed_example(out, example_pkg(name))  # the template ships zero code; the e2e owns the demo
    use_local_devtools(out)  # resolve the devtools git-dep to the working-tree package (test-only override)
    git_init_commit(out)
    run(["uv", "sync", "--extra", "dev", "--extra", "devtools"], out)
    return name, out
