"""Unit tests for devtools/config.py — the packaged-config locator (ast-grep / jscpd paths).

Method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a dense
container of parameter combinations rather than one case per behaviour.
"""

import sys

import pytest

from devtools import config
from devtools.config import Config


def test_names():
    """The advertised short-names ARE the argparse `choices` and the resolvable set — all three or none.

    Tied together deliberately: a name listed here but not resolvable would be a usage message offering an
    argument that then dies as a "broken install"; a name resolvable but not listed would be undiscoverable
    and unreachable through the CLI, since argparse rejects anything outside `choices`.
    """
    names = Config.names()
    assert names == ["jscpd", "sgconfig"], "the known configs, sorted — sorted so the usage line is stable"
    for name in names:
        assert Config.path(name).exists(), f"{name} is advertised, so it must resolve to a shipped file"


def test_path(tmp_path):
    """Resolution of each packaged config, plus both ways it must fail LOUDLY.

    Both failures raise `SystemExit` rather than returning None because this is read through
    `$(python -m devtools.config sgconfig)` in a shell: a None printed as "None" would be handed to
    ast-grep as a config path, and the external CLI's own error is where the real cause disappears.

    The missing-file case is the one worth building a tree for — it separates "you asked for a config that
    does not exist" from "the config exists but was not packaged", which are a user error and a build bug
    with entirely different fixes.
    """
    for name, filename in (("sgconfig", "sgconfig.yml"), ("jscpd", "jscpd.json")):
        resolved = Config.path(name)
        assert resolved.name == filename and resolved.exists(), f"{name} resolves to the packaged file"
        assert resolved.is_absolute(), "an external CLI is run from an arbitrary cwd — the path must be absolute"

    # sgconfig's `ruleDirs: [sg-rules]` is relative to the config FILE, so the rules must ship beside it.
    assert (Config.path("sgconfig").parent / "sg-rules").is_dir(), "the ast-grep rule dir ships beside sgconfig"

    with pytest.raises(SystemExit, match="unknown config"):
        Config.path("nope")

    # A short-name that IS known but whose file was not packaged — the broken-install branch, driven by
    # pointing the module at an empty directory rather than by deleting anything real.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(config, "__file__", str(tmp_path / "config.py"))
    with pytest.raises(SystemExit, match="broken install"):
        Config.path("sgconfig")
    monkey.undo()
    assert Config.path("sgconfig").exists(), "the real resolution is restored — no leaked patch"


def test_main_rejects_an_unknown_name(monkeypatch):
    """`main` is mirror-exempt argparse plumbing, but the `choices` wiring to `names()` is not free — a
    bogus name must die as an argparse USAGE error (exit 2), not reach `Config.path`'s exit 1."""
    monkeypatch.setattr(sys, "argv", ["devtools.config", "bogus"])
    with pytest.raises(SystemExit) as exc:
        config.main()
    assert exc.value.code == 2, "an invalid choice is an argparse usage error"
