"""Unit tests for devtools/small.py — a unit test touches nothing it did not create.

Written in the method-mirror convention (docs/UNIT_TESTS.md), and held to its own rule: every fixture here
is built under `tmp_path` during the test that reads it.
"""

import ast

import pytest

from devtools.small import SmallTests


def _expr(src: str) -> ast.expr:
    return ast.parse(src, mode="eval").body


def _engine(tmp_path, monkeypatch, **files: str) -> SmallTests:
    """A repo whose unit tree contains the given `name: source` modules."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.structure]\ntest_layout = "mirror"\n')
    unit = tmp_path / "tests" / "unit"
    unit.mkdir(parents=True, exist_ok=True)
    for name, source in files.items():
        (unit / f"{name}.py").write_text(source)
    return SmallTests([], test_root=str(unit))


def test_files(tmp_path, monkeypatch):
    """The unit tree, and an empty one is not an error — a fresh generation has no tests yet and a gate
    that opened red on a brand-new project would be teaching people to ignore it."""
    engine = _engine(tmp_path, monkeypatch, a="", b="")
    (tmp_path / "tests" / "unit" / "__pycache__").mkdir()
    (tmp_path / "tests" / "unit" / "__pycache__" / "stale.py").write_text("import time\ntime.sleep(1)\n")
    assert [p.name for p in engine.files()] == ["a.py", "b.py"], "compiled leftovers are not source"
    assert SmallTests([], test_root=str(tmp_path / "absent")).files() == []


@pytest.mark.parametrize(
    ("expr", "chain", "trailing"),
    [
        ("time.sleep(0)", "time.sleep", "sleep"),
        ("sleep(0)", "sleep", "sleep"),
        ("urllib.request.urlopen(u)", "urllib.request.urlopen", "urlopen"),
        # A subscripted or computed callee has no name to read; both answer empty rather than guessing.
        ("handlers[0](x)", "", ""),
    ],
)
def test_chain(expr, chain, trailing):
    """The dotted spelling — `time.sleep` and a bare imported `sleep` are the same defect, so the engine
    reads both a full chain (for `requests.get`, where the prefix is the evidence) and a trailing name."""
    assert SmallTests.chain(_expr(expr).func) == chain


@pytest.mark.parametrize(
    ("expr", "trailing"),
    [("time.sleep(0)", "sleep"), ("sleep(0)", "sleep"), ("a.b.c.deep()", "deep"), ("handlers[0](x)", "")],
)
def test_trailing(expr, trailing):
    assert SmallTests.trailing(_expr(expr).func) == trailing


def test_calls(tmp_path, monkeypatch):
    """Every call as (node, trailing, chain) — parsed once because four checks read the same list."""
    engine = _engine(tmp_path, monkeypatch)
    found = engine.calls(ast.parse("import time\ntime.sleep(1)\nfoo()\n"))
    assert {(name, chain) for _node, name, chain in found} == {("sleep", "time.sleep"), ("foo", "foo")}
    assert all(isinstance(node, ast.Call) for node, _n, _c in found)


@pytest.mark.parametrize(
    ("value", "absolute"),
    [
        ("/data/raw/x.wav", True),
        ("C:/data/x.wav", True),
        ("C:\\data\\x.wav", True),
        ("relative/path.py", False),
        ("", False),
        (42, False),
    ],
)
def test_is_absolute(value, absolute):
    assert SmallTests.is_absolute(value) is absolute


def test_absolute_paths(tmp_path, monkeypatch):
    """An absolute literal is only a defect when something OPENS it.

    Measured on this repo, the literal-only version scored 2 findings and 2 false positives: a `/*...*/`
    comment marker in generated HTML, and a `"/mod.py"` substring asserted against a message. Neither
    touches a filesystem, so the entry point is the evidence and the literal is only its argument.
    """
    engine = _engine(tmp_path, monkeypatch)
    src = (
        "Path('/data/raw/big.wav').read_text()\n"
        "open('/etc/hosts')\n"
        "assert '/mod.py' in message\n"
        "html = f'/*{marker}*/'\n"
        "Path('fixtures/small.wav')\n"
    )
    found = engine.absolute_paths(engine.calls(ast.parse(src)))
    assert {node.value for node in found} == {"/data/raw/big.wav", "/etc/hosts"}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import time\n\ndef test_a():\n    time.sleep(1)\n    assert 1\n", ["sleep"]),
        ("def test_a():\n    requests.get('http://x')\n    assert 1\n", ["network"]),
        ("def test_a():\n    urllib.request.urlopen(u)\n    assert 1\n", ["network"]),
        ("def test_a():\n    Path.home()\n    assert 1\n", ["outside its own fixtures"]),
        ("def test_a():\n    Path('/data/x').read_text()\n    assert 1\n", ["absolute path"]),
        ("def test_a():\n    assert random.randint(0, 9) >= 0\n", ["nothing in this file seeds"]),
        # The seed rule is PER FILE: a seed in a fixture covers the module's tests, so demanding one at each
        # sampling site would fight the fixture pattern the convention encourages.
        ("random.seed(0)\n\ndef test_a():\n    assert random.randint(0, 9) >= 0\n", []),
        ("def test_a():\n    rng = np.random.default_rng(0)\n    assert rng.random() >= 0\n", []),
        # The clean shape: fixtures it created, no clock, no network, no unseeded draw.
        ("def test_a(tmp_path):\n    (tmp_path / 'f').write_text('x')\n    assert 1\n", []),
    ],
)
def test_violations(tmp_path, monkeypatch, source, expected):
    found = _engine(tmp_path, monkeypatch, probe=source).violations()
    assert len(found) == len(expected), found
    for finding, fragment in zip(found, expected, strict=True):
        assert fragment in finding
        assert "probe.py:" in finding, "the finding names the file and line, so it is actionable"


def test_report(tmp_path, monkeypatch):
    """The explorer view: a count plus every finding, so a reader sees scale before detail."""
    text = _engine(tmp_path, monkeypatch, probe="import time\n\ndef test_a():\n    time.sleep(1)\n").report()
    assert text.splitlines()[0] == "unit tests that are not small: 1"
    assert "probe.py" in text
    assert _engine(tmp_path / "clean", monkeypatch).report() == "unit tests that are not small: 0"


def test_run_assert(tmp_path, monkeypatch):
    """The gate view — and a repo with no unit tests yet passes, because a fresh generation must open green."""
    assert _engine(tmp_path, monkeypatch, probe="def test_a(tmp_path):\n    assert 1\n").run_assert() == 0
    assert _engine(tmp_path / "empty", monkeypatch).run_assert() == 0
    assert _engine(tmp_path, monkeypatch, probe="import time\n\ndef test_a():\n    time.sleep(1)\n").run_assert() == 1
