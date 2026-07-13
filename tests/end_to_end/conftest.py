"""Shared helpers + fixtures for the scaffold E2E suite.

The suite treats the scaffold as a black box: it generates real projects with copier from the
current working-tree template, then runs every gate as a subprocess and asserts the outcome.
Runs on Linux/CI (matches the generated projects' `ubuntu-latest`); copier needs a git repo, so
each run builds a throwaway git repo from the on-disk template (testing what is on disk, not a tag).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]  # tests/end_to_end/conftest.py -> scaffold root
COPIER = "copier@9.16.0"
RUFF = "ruff@0.15.13"
VULTURE = "vulture@2.16"
NOX = "nox@2026.7.11"
PRECOMMIT = "pre-commit@4.6.0"
SELECT = "F,E,W,B,C4,UP,I,T20,FBT,BLE001,S,C90,PLR,PLC,SIM,RUF"

# Two representative points on the toggle lattice: the minimal mid-stage and the full cardioseg mirror.
COMBOS = {
    "base": {
        "project_name": "base",
        "package_name": "base_pkg",
        "has_viewer": "false",
        "viewer_imports_trainer": "false",
        "enforce_arch_fitness": "true",
        "enable_astgrep": "false",
        "enable_jscpd": "false",
        "coverage_floor": "80",
    },
    "full": {
        "project_name": "full",
        "package_name": "full_pkg",
        "has_viewer": "true",
        "viewer_name": "full_viz",
        "viewer_imports_trainer": "false",
        "enforce_arch_fitness": "true",
        "enable_astgrep": "true",
        "enable_jscpd": "true",
        "coverage_floor": "80",
    },
}


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
    answers = COMBOS[combo_name]
    result = ["core", answers["package_name"]]
    if answers["has_viewer"] == "true":
        result.append(answers["viewer_name"])
    return result


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
