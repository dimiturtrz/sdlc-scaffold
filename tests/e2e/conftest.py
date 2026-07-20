"""Shared helpers + fixtures for the scaffold E2E suite.

The suite treats the scaffold as a black box: it generates real projects with copier from the
current working-tree template, then runs every gate as a subprocess and asserts the outcome.
Runs on Linux/CI (matches the generated projects' `ubuntu-latest`); copier needs a git repo, so
each run builds a throwaway git repo from the on-disk template (testing what is on disk, not a tag).
"""

import functools
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
COPIER_VERSION = COPIER.split("@")[1]
# Where the pinned copier is INSTALLED, isolated from the developer's own `uv tool` set so a test run never
# mutates it. Kept in the repo (gitignored) rather than a temp dir on purpose: it survives between runs, so
# the install cost is paid once ever instead of once per run.
_TOOLS = REPO / ".e2e-tools"
RUFF = f"ruff@{copier_default('ruff_version')}"
VULTURE = f"vulture@{copier_default('vulture_version')}"
NOX = f"nox@{copier_default('nox_version')}"
PRECOMMIT = f"pre-commit@{copier_default('precommit_version')}"
# deptry runs env-aware via `uv run --with` (PEP508 pin, not the uvx `@` form) so it reads installed metadata.
DEPTRY = f"deptry=={copier_default('deptry_version')}"
PIP_AUDIT = f"pip-audit=={copier_default('pip_audit_version')}"
PYREFLY = f"pyrefly=={copier_default('pyrefly_version')}"
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
# there is something for the gates to lint/test/graph. The fixture lives as REAL FILES under `seed/` (named
# `.py.tmpl` so the scaffold's own ruff/pyrefly skip them — they carry a package-name token, not valid
# imports) and is architecturally RICH on purpose: it must exercise every arrow the class-graph gates read
# (bd 4bl) — `inherits` both INTRA-file (KeyMissingError -> StoreError) and CROSS-file (CapacityError ->
# StoreError); `holds` (Repository -> the Store contract, MemoryStore -> StoreConfig); `calls` resolving to
# the INTERFACE (Repository -> Store, satisfied structurally so no subclassing is needed); and `constructs`
# reaching the CONCRETE (Service wires a MemoryStore). It also ships green through every EXISTING gate —
# pyrefly strict (targeting the 3.11 floor, so no 3.12-only `typing.override`), ruff, vulture, ast-grep
# in-a-class, test-mirror, 100% covered — so the fixture doubles as proof the gates coexist.
_SEED_ROOT = Path(__file__).parent / "seed"
_PKG_TOKEN = "__PKG__"  # a token, not str.format: the fixture is real code, full of f-string braces


def seed_example(path, pkg):
    """Drop the demo package + its strict-mirror tests into a generated (code-less) project."""
    for src in sorted(_SEED_ROOT.rglob("*.py.tmpl")):
        name = src.name.removesuffix(".tmpl")
        target = (path / pkg / name) if src.parent.name == "pkg" else (path / "tests" / "unit" / pkg / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src.read_text(encoding="utf-8").replace(_PKG_TOKEN, pkg), encoding="utf-8")


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


def _npx():
    """The npx spelling `subprocess` can actually launch on this platform.

    On Windows, node ships BOTH an extensionless POSIX `npx` script and `npx.cmd`. `shutil.which("npx")`
    finds the former, which subprocess cannot exec -- so a which()-based guard reported "available" and the
    jscpd tests then died on FileNotFoundError. Resolving the real spelling makes them RUN rather than
    merely fail honestly; skipping would have been the smaller half of the fix.
    """
    for candidate in (["npx.cmd", "npx"] if sys.platform == "win32" else ["npx"]):
        try:
            subprocess.run([candidate, "--version"], capture_output=True, check=True, text=True)  # noqa: S603
        except (OSError, subprocess.CalledProcessError):
            continue
        return candidate
    return None


NPX = _npx()


def has_node():
    """Whether the jscpd gates can run here at all — i.e. whether some npx spelling is launchable."""
    return NPX is not None


def bash_sees_uv():
    """Whether the `bash` pre-commit shells out to can find `uv` on its PATH.

    The archmap hook is the one hook wrapped in `bash -c`, because it needs `&&`/`||` between the regen
    and the staleness check. On Windows the bash pre-commit picks does not always inherit `uv` from the
    Windows PATH, and the hook then dies with `uv: command not found`.

    This is an ENVIRONMENT predicate, not a way to make a red test green: what it guards is a hook that
    cannot execute here at all, and the hook itself now FAILS LOUDLY in that case rather than reporting
    Passed while writing nothing (it used to join the two commands with `;`, discarding the regen's exit
    code — a hook that went green precisely when its job did not happen).
    """
    try:
        probe = subprocess.run(["bash", "-c", "command -v uv"], capture_output=True, check=False)  # noqa: S607
    except OSError:
        return False
    return probe.returncode == 0


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


@functools.cache
def copier_cmd() -> list[str]:
    """The pinned copier as an INSTALLED executable, resolved once per session (bd f9y.1).

    `uvx copier@9.16.0` re-resolves the tool environment on every call — 0.72s before any work happens, of
    a 2.80s generation, paid ~17 times across the suite. Installing it once and invoking the binary spends
    that once (and zero times on later runs, since the install persists).

    THE PIN STAYS LOAD-BEARING. `uvx tool@version` had the virtue of making the version unmissable at the
    call site, and dropping to a bare `copier` would quietly test whatever happened to be installed — which
    is not what consumers run. So the installed binary is version-checked against COPIER on every session,
    and reinstalled the moment it disagrees. Drift fails loudly instead of silently changing the subject.
    """
    binaries = _TOOLS / "bin"
    env = {"UV_TOOL_DIR": str(_TOOLS / "tools"), "UV_TOOL_BIN_DIR": str(binaries)}
    exe = binaries / ("copier.exe" if sys.platform == "win32" else "copier")
    if _installed_version(exe) != COPIER_VERSION:
        subprocess.run(  # noqa: S603 (test infra: a fixed, pinned command)
            ["uv", "tool", "install", "--force", f"copier=={COPIER_VERSION}"],  # noqa: S607 (uv on PATH)
            env={**os.environ, **env},
            capture_output=True,
            text=True,
            check=True,
        )
    found = _installed_version(exe)
    assert found == COPIER_VERSION, f"copier {found!r} installed but the suite pins {COPIER_VERSION!r}"
    return [str(exe)]


def _installed_version(exe: Path) -> str | None:
    """The version of an already-installed copier, or None when there is nothing runnable there yet."""
    if not exe.exists():
        return None
    result = subprocess.run([str(exe), "--version"], capture_output=True, text=True, check=False)  # noqa: S603
    return result.stdout.strip().split()[-1] if result.returncode == 0 else None


def generate(scaffold: Path, out: Path, answers: dict):
    cmd = [*copier_cmd(), "copy", "--defaults", "--trust"]
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
