"""Remote copier-update smoke (bd knl).

The rest of the E2E suite proves the update *mechanic* against a throwaway LOCAL git repo built from
the working tree (conftest.make_scaffold): gates bite, `copier update` heals drift. This test guards the
one axis that path can't — the **network hop**: fetch the scaffold from its real remote URL, resolve a
published tag, `copier update` to a newer published tag, and confirm `.copier-answers.yml` records the
new tag as `_commit`. That closes the "asserted, never shown" gap in the manual remote proof (bd 8r7).

Skipped unless `SCAFFOLD_REMOTE_SMOKE=1` (so normal/offline runs never touch the network). CI wires it via
`.github/workflows/remote-smoke.yml` (dispatch + weekly schedule), where it becomes a real regression gate.

Auth: a token in `GH_TOKEN`/`GITHUB_TOKEN` is injected as git's `http.extraheader` via `GIT_CONFIG_*`
env vars — it NEVER lands in a command line (argv is world-readable via `ps`) or a config file. The plain
URL is what git actually invokes. Without a token the plain URL relies on the caller's ambient git creds.
"""

import base64
import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.slow,  # network + full copier round-trip — lives in the slow layer (uo0.4)
    pytest.mark.skipif(
        os.environ.get("SCAFFOLD_REMOTE_SMOKE") != "1",
        reason="remote network smoke — set SCAFFOLD_REMOTE_SMOKE=1 to run (needs git access to the scaffold remote)",
    ),
]

COPIER = "copier@9.16.0"
_TAG = re.compile(r"refs/tags/(v\d+\.\d+\.\d+)$")


def _git_env():
    """Auth + no-hang env for every git/copier subprocess. Token (if any) becomes an `http.extraheader`
    through GIT_CONFIG_* — kept out of argv (ps-visible) and off disk. GIT_TERMINAL_PROMPT=0 turns a
    missing credential into an immediate error instead of a wedged interactive prompt."""
    env = {"GIT_TERMINAL_PROMPT": "0"}
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.https://github.com/.extraheader"
        env["GIT_CONFIG_VALUE_0"] = f"AUTHORIZATION: basic {basic}"
    return env


def _sh(cmd, cwd=None, *, check=True):
    result = subprocess.run(  # noqa: S603 (test infra: cmd is a controlled list, never shell/untrusted input)
        [str(c) for c in cmd],
        cwd=cwd and str(cwd),
        env={**os.environ, **_git_env()},
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


def _remote_url():
    """The scaffold's own origin (override with SCAFFOLD_REMOTE_URL). Any embedded credentials are stripped
    so nothing secret can reach argv — auth rides the GIT_CONFIG_* extraheader from `_git_env` instead."""
    url = os.environ.get("SCAFFOLD_REMOTE_URL")
    if not url:
        url = _sh(["git", "remote", "get-url", "origin"], cwd=Path(__file__).resolve().parents[2]).stdout.strip()
    return re.sub(r"https://[^@/]*@", "https://", url)


def _newest_tags(url, n=2):
    """The n newest vX.Y.Z tags on the remote, newest first (copier resolves these as vcs-refs)."""
    out = _sh(["git", "ls-remote", "--tags", "--sort=-v:refname", url, "v*"]).stdout
    seen, ordered = set(), []
    for line in out.splitlines():
        m = _TAG.search(line)
        if m and m.group(1) not in seen:  # skip peeled ^{} duplicates
            seen.add(m.group(1))
            ordered.append(m.group(1))
    return ordered[:n]


def _answers_commit(project: Path):
    """The `_commit:` copier stamped into .copier-answers.yml (the tag it last rendered from)."""
    for line in (project / ".copier-answers.yml").read_text(encoding="utf-8").splitlines():
        if line.startswith("_commit:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError("no _commit line in .copier-answers.yml")


def test_remote_copy_then_update_across_tags(tmp_path):
    url = _remote_url()
    newer, older = _newest_tags(url, 2)
    assert older != newer, f"need two distinct published tags to test the update hop (got {newer!r} twice)"

    proj = tmp_path / "remote_proj"
    data = ["--data", "project_name=remote-proj", "--data", "packages=core", "--data", "domain=none"]

    # Copy from the REMOTE at the older tag.
    _sh(["uvx", COPIER, "copy", "--defaults", "--trust", "--vcs-ref", older, *data, url, str(proj)])
    assert _answers_commit(proj) == older, "copy should stamp the older tag as _commit"

    # A generated project must be a git repo for `copier update` (it 3-way-merges against git state).
    _sh(["git", "init", "-q"], cwd=proj)
    _sh(["git", "config", "user.email", "smoke@test"], cwd=proj)
    _sh(["git", "config", "user.name", "smoke"], cwd=proj)
    _sh(["git", "add", "-A"], cwd=proj)
    _sh(["git", "commit", "-qm", "gen"], cwd=proj)

    # Update to the newer tag over the network — the hop this test exists to guard.
    _sh(["uvx", COPIER, "update", "--defaults", "--trust", "--vcs-ref", newer], cwd=proj)
    assert _answers_commit(proj) == newer, f"update should advance _commit {older} -> {newer}"
