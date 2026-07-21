"""Unit tests for devtools/astgrep.py — the packaged ast-grep rule set as an engine.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.

The external CLI is never invoked. `subprocess.run` is the seam: a FAKE run records its command and hands
back a real `CompletedProcess`, so the tests assert on the command this engine builds and on how it reads a
result — the two things this module actually owns. Actually shelling out would test `uvx`, need the network,
and make the suite depend on a rule set that lives in another file.
"""

import subprocess

import pytest

from devtools.astgrep import AstGrep


def _done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    """A real CompletedProcess — the type the engine actually receives, so no stub semantics can drift."""
    return subprocess.CompletedProcess(args=["ast-grep"], returncode=code, stdout=out, stderr=err)


def test_scan(monkeypatch):
    """The command carries the INSTALLED config path, which is the whole reason this engine exists.

    Locating the config used to be a `$(python -m devtools.config sgconfig)` shell substitution, and that
    substitution is the only reason the hook needed bash — which is why the gate did not run on Windows, the
    scaffold's own primary dev platform. Asserting the resolved path is asserting that the shell is gone.
    """
    captured = {}

    def fake_run(command, **_):
        captured["command"] = command
        return _done()

    monkeypatch.setattr("devtools.astgrep.subprocess.run", fake_run)
    done = AstGrep(["pkg_a", "pkg_b"]).scan()
    command = captured["command"]
    assert command[-2:] == ["pkg_a", "pkg_b"], "the root packages are the scan scope, and they come last"
    assert command[-3].endswith("sgconfig.yml"), "the config resolved to the INSTALLED file, not a repo path"
    assert "ast-grep" in command, "it invokes the vendored CLI"
    assert command[:2] == ["uvx", "--from"], "resolved per-run by uvx — no repo-level install"
    assert done.returncode == 0, "the CompletedProcess is returned, not swallowed"


@pytest.mark.parametrize(
    ("code", "out", "err", "expected"),
    [
        # A broken rule FILE reports on stderr while stdout stays empty. Dropping stderr would render that
        # as 'clean' — the exact failure this gate exists to prevent, so both streams are load-bearing.
        (1, "error[x]: found", "cannot parse rule", "error[x]: found\ncannot parse rule"),
        (1, "error[x]: found", "", "error[x]: found"),
        (1, "", "cannot parse rule", "cannot parse rule"),
        # Whitespace-only output is nothing to say, not a finding made of blank lines.
        (0, "", "", "ast-grep: clean"),
        (0, "  \n ", "\n", "ast-grep: clean"),
    ],
)
def test_findings(code, out, err, expected):
    assert AstGrep.findings(_done(code, out=out, err=err)) == expected


def test_report(monkeypatch):
    """The explorer view renders whatever the scan said, INCLUDING advisory output a gate would let pass."""
    engine = AstGrep(["pkg"])
    monkeypatch.setattr(engine, "scan", lambda: _done(1, out="warning[py-dynamic-attr]: ..."))
    assert "py-dynamic-attr" in engine.report()
    monkeypatch.setattr(engine, "scan", lambda: _done(0))
    assert engine.report() == "ast-grep: clean", "a clean tree reports clean rather than an empty string"


def test_run_assert(monkeypatch):
    """The verdict is the CLI's OWN exit code, and the gate scans exactly once.

    `error`-severity rules set a non-zero exit; `warning` ones do not, which is how the advisory
    py-dynamic-attr rule rides the same scan as the blocking rules without failing it — so the exit code is
    read directly rather than re-derived from the text.

    The call count is the second fact: rendering the failure must not re-scan the tree. A gate that calls
    `report()` to print its own findings pays for the whole analysis twice, on the slowest path it has.
    """
    engine = AstGrep(["pkg"])
    for code, out in ((0, ""), (1, "error[py-top-level-function]: ...")):
        calls = []
        monkeypatch.setattr(engine, "scan", lambda code=code, out=out: (calls.append(1), _done(code, out=out))[1])
        assert engine.run_assert() == code, f"exit {code} is passed through as the verdict"
        assert len(calls) == 1, "one scan per gate run, pass or fail"
