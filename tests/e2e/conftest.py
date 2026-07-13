"""Shared helpers + fixtures for the scaffold E2E suite.

The suite treats the scaffold as a black box: it generates real projects with copier from the
current working-tree template, then runs every gate as a subprocess and asserts the outcome.
Runs on Linux/CI (matches the generated projects' `ubuntu-latest`); copier needs a git repo, so
each run builds a throwaway git repo from the on-disk template (testing what is on disk, not a tag).
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]  # tests/e2e/conftest.py -> scaffold root


def _copier_default(key):
    """Read a `when: false` constant's default straight from copier.yml — the single source of truth.

    Keeps the harness's pinned versions + ruff select in ONE place (copier.yml) so a bump can't drift
    between the template and the tests that exercise it. Regex-parsed to avoid a PyYAML dependency.
    """
    text = (REPO / "copier.yml").read_text(encoding="utf-8")
    match = re.search(rf'^{key}:\n(?:  .*\n)*?  default: "([^"]+)"', text, re.M)
    if match is None:
        msg = f"copier.yml: no default found for {key!r}"
        raise RuntimeError(msg)
    return match.group(1)


COPIER = "copier@9.16.0"
RUFF = f"ruff@{_copier_default('ruff_version')}"
VULTURE = f"vulture@{_copier_default('vulture_version')}"
NOX = f"nox@{_copier_default('nox_version')}"
PRECOMMIT = f"pre-commit@{_copier_default('precommit_version')}"
# Curated-narrow select — single-sourced from copier.yml's `ruff_select` (must match the template).
SELECT = _copier_default("ruff_select")

# Two representative points on the toggle lattice: the minimal mid-stage and the full cardioseg mirror.
COMBOS = {
    "base": {
        "project_name": "base",
        "packages": "base_pkg",
        "ship_example": "true",
        "enforce_arch_fitness": "true",
        "enable_astgrep": "false",
        "enable_jscpd": "false",
        "enable_class_shape_smells": "false",
        "enable_beads": "false",
        "enable_import_linter": "true",
        "coverage_floor": "80",
    },
    "full": {
        "project_name": "full",
        "packages": "full_pkg",
        "ship_example": "true",
        "enforce_arch_fitness": "true",
        "enable_astgrep": "true",
        "enable_jscpd": "true",
        "enable_class_shape_smells": "true",
        "enable_beads": "true",
        "enable_import_linter": "true",
        "coverage_floor": "80",
    },
}


def example_pkg(combo_name):
    """The demo package's folder name = the first entry in `packages` (copier's computed package_name)."""
    return COMBOS[combo_name]["packages"].split(",")[0].strip()


def run(cmd, cwd, *, check=True, env=None):
    """Run a subprocess, capturing output. On failure, surface stdout+stderr in the assertion."""
    result = subprocess.run(
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


def layers(combo_name):
    return [p.strip() for p in COMBOS[combo_name]["packages"].split(",")]


def make_scaffold(dst: Path):
    """Build a throwaway git repo from the on-disk template so copier can version it."""
    for item in ["copier.yml", "ruff.toml", ".pre-commit-hooks.yaml", "template"]:
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
    """A generated + git-inited + uv-synced project for each toggle combo. Session-scoped: built once."""
    name = request.param
    out = tmp_path_factory.mktemp(f"proj_{name}")
    generate(scaffold, out, COMBOS[name])
    git_init_commit(out)
    run(["uv", "sync", "--extra", "dev", "--extra", "devtools"], out)
    return name, out
