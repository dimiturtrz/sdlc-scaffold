"""Unit tests for devtools/astgrep.py — the packaged ast-grep rule set as an engine."""

import subprocess

from devtools.astgrep import AstGrep


def _done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["ast-grep"], returncode=code, stdout=out, stderr=err)


# ---- the command carries the PACKAGED config, which is the whole reason this engine exists -----------


def test_the_scan_points_at_the_installed_config_not_a_repo_path(monkeypatch):
    """Locating the config used to be a `$(python -m devtools.config sgconfig)` shell substitution, and
    that substitution is the only reason the hook needed bash — which is why it did not run on Windows."""
    captured = {}

    def fake_run(command, **_):
        captured["command"] = command
        return _done()

    monkeypatch.setattr("devtools.astgrep.subprocess.run", fake_run)
    AstGrep(["pkg_a", "pkg_b"]).scan()
    assert captured["command"][-2:] == ["pkg_a", "pkg_b"], "the root packages are the scan scope"
    assert captured["command"][-3].endswith("sgconfig.yml"), "config resolved to the INSTALLED file"
    assert "ast-grep" in captured["command"], "it invokes the vendored CLI"


# ---- the gate verdict is the CLI's own exit code ------------------------------------------------------


def test_a_clean_scan_passes(monkeypatch):
    engine = AstGrep(["pkg"])
    monkeypatch.setattr(engine, "scan", lambda: _done(0))
    assert engine.run_assert() == 0


def test_a_violation_blocks(monkeypatch):
    """`error`-severity rules set a non-zero exit; `warning` ones do not, which is how the advisory
    py-dynamic-attr rule rides the same scan as the blocking rules without failing it."""
    engine = AstGrep(["pkg"])
    monkeypatch.setattr(engine, "scan", lambda: _done(1, out="error[py-top-level-function]: ..."))
    assert engine.run_assert() == 1


def test_gating_scans_exactly_once(monkeypatch):
    """Rendering the failure must not re-scan the tree — a gate that calls report() to print its own
    findings pays for the whole analysis twice."""
    calls = []
    engine = AstGrep(["pkg"])
    monkeypatch.setattr(engine, "scan", lambda: (calls.append(1), _done(1, out="boom"))[1])
    engine.run_assert()
    assert len(calls) == 1


# ---- what the reader is shown ------------------------------------------------------------------------


def test_findings_carry_both_streams():
    """A broken rule file reports on stderr while stdout stays empty; dropping stderr would render that
    as 'clean' — the failure mode this gate exists to prevent."""
    text = AstGrep.findings(_done(1, out="error[x]: found", err="cannot parse rule"))
    assert "error[x]: found" in text
    assert "cannot parse rule" in text


def test_findings_say_clean_when_there_is_nothing_to_say():
    assert AstGrep.findings(_done(0)) == "ast-grep: clean"


def test_report_renders_a_scan(monkeypatch):
    engine = AstGrep(["pkg"])
    monkeypatch.setattr(engine, "scan", lambda: _done(1, out="warning[py-dynamic-attr]: ..."))
    assert "py-dynamic-attr" in engine.report()
