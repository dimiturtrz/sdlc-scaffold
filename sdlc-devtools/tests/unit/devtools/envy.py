"""Unit tests for devtools/envy.py — a method more interested in another class than its own.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import logging

import pytest

from devtools.envy import FeatureEnvy, MethodSite

_ENGINE = "class Engine:\n    def a(self): ...\n    def b(self): ...\n    def c(self): ...\n    def d(self): ...\n\n\n"

# A field-typed receiver reaching past its own state four times — the smell in its plainest form.
_ENVIOUS = _ENGINE + (
    "class Manager:\n"
    "    def __init__(self, engine: Engine):\n        self._engine = engine\n\n"
    "    def drive(self):\n"
    "        self._engine.a()\n        self._engine.b()\n        self._engine.c()\n        self._engine.d()\n"
)
# The same four foreign accesses, but the method uses its OWN state more — that is a ratio, not a smell.
_OWN_STATE = _ENVIOUS + "        self.x\n        self.y\n        self.z\n        self.w\n        self.v\n"
# A PARAMETER's annotation resolves the receiver just as a field's declared type does.
_PARAM = _ENGINE + (
    "class Manager:\n"
    "    def drive(self, engine: Engine):\n"
    "        engine.a()\n        engine.b()\n        engine.c()\n        engine.d()\n"
)
_BELOW_FLOOR = _ENGINE + (
    "class Manager:\n"
    "    def __init__(self, engine: Engine):\n        self._engine = engine\n\n"
    "    def drive(self):\n        self._engine.a()\n        self._engine.b()\n"
)
_VALUE_OBJECT = (
    "@dataclass(frozen=True)\nclass Config:\n    a: int\n    b: int\n    c: int\n    d: int\n\n\n"
    "class Engine:\n"
    "    def __init__(self, config: Config):\n        self._config = config\n\n"
    "    def go(self):\n"
    "        return self._config.a + self._config.b + self._config.c + self._config.d\n"
)
_ORCHESTRATOR = (
    "class A:\n    def go(self): ...\n\n\nclass B:\n    def go(self): ...\n\n\n"
    "class C:\n    def go(self): ...\n\n\nclass D:\n    def go(self): ...\n\n\n"
    "class Orchestrator:\n"
    "    def __init__(self, a: A, b: B, c: C, d: D):\n"
    "        self._a, self._b, self._c, self._d = a, b, c, d\n\n"
    "    def run(self):\n"
    "        self._a.go()\n        self._b.go()\n        self._c.go()\n        self._d.go()\n"
)
_UNRESOLVABLE = (
    "class Manager:\n"
    "    def drive(self, thing):\n"
    "        thing.a()\n        thing.b()\n        thing.c()\n        thing.d()\n"
)


def _engine(monkeypatch, tmp_path, name: str, src: str, minimum: int = 4) -> FeatureEnvy:
    """A FeatureEnvy over a real one-module package — the resolver needs files, not a fake tree."""
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "mod.py").write_text(src)
    monkeypatch.chdir(tmp_path)
    return FeatureEnvy([name], minimum=minimum)


@pytest.mark.parametrize(
    ("name", "src", "hits"),
    [
        ("envy_hit", _ENVIOUS, 1),
        # A param's annotation resolves the receiver — envy does not require the collaborator to be a field.
        ("envy_param", _PARAM, 1),
        ("envy_own", _OWN_STATE, 0),
        # Two accesses versus one is not evidence — the floor exists so the ratio is not read as noise.
        ("envy_floor", _BELOW_FLOOR, 0),
        # A frozen dataclass is a SATELLITE. Reading its fields is what it is FOR, and the fix envy implies
        # (move the method onto it) is usually impossible because the method needs its own state too. This
        # is the real false positive the role classification exists to remove.
        ("envy_vo", _VALUE_OBJECT, 0),
        # Envy is judged against ONE class. Spreading calls across collaborators is orchestration — a
        # different shape, and often correct.
        ("envy_orch", _ORCHESTRATOR, 0),
        # The ratio is only ever computed over accesses we actually understand.
        ("envy_unres", _UNRESOLVABLE, 0),
    ],
)
def test_violations(monkeypatch, tmp_path, name, src, hits):
    found = _engine(monkeypatch, tmp_path, name, src).violations()
    assert len(found) == hits, f"{name}: expected {hits} finding(s), got {found}"
    if hits:
        assert "Manager.drive" in found[0], "the finding names the method"
        assert "may belong on Engine" in found[0], "and says where the method wants to live"


def test_violations_honours_the_floor(monkeypatch, tmp_path):
    """The SAME source flips verdict on the floor alone — which is what makes the knob a real tuning point
    rather than decoration. Legitimate delegators (mappers, serializers, facades) read another class heavily
    by design, so the repo raises the floor instead of the rule being weakened."""
    assert _engine(monkeypatch, tmp_path, "envy_low", _ENVIOUS, minimum=4).violations() != []
    assert _engine(monkeypatch, tmp_path, "envy_high", _ENVIOUS, minimum=9).violations() == []


@pytest.mark.parametrize(
    ("target", "count", "own", "expects"),
    [
        # The target arrives QUALIFIED and the suggestion must name the class alone — a message reading
        # "may belong on pkg.mod.Engine" would name something no reader can move a method onto.
        ("pkg.mod.Engine", 5, 1, ("pkg/mod.py:12", "Manager.drive", "5x", "1x", "may belong on Engine")),
        ("Engine", 4, 0, ("may belong on Engine",)),  # an unqualified target survives the rsplit unchanged
    ],
)
def test_describe(target, count, own, expects):
    """The finding's wording — every fact a reviewer needs to act, in one line.

    The four location fields travel together as one value precisely so this message cannot be assembled
    with a mismatched path and line; asserting on the rendered string is asserting that they stayed paired.
    """
    message = MethodSite("pkg/mod.py", "Manager", "drive", 12).describe(target, count, own)
    for fragment in expects:
        assert fragment in message, f"{fragment!r} missing from {message!r}"


def test_load_minimum(tmp_path, monkeypatch):
    """The floor comes from config, and its ABSENCE is a default rather than a crash — a repo that never
    heard of this gate must still be scannable."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[tool.structure]\nfeature_envy_min = 9\n")
    assert FeatureEnvy.load_minimum() == 9
    (tmp_path / "pyproject.toml").write_text("[tool.other]\nx = 1\n")
    assert FeatureEnvy.load_minimum() == 4, "the documented default stands in when the key is absent"


def test_report(monkeypatch, tmp_path):
    """The explorer view: the headline names the FLOOR as well as the count.

    Without the floor in the text, "feature envy: 0" is unreadable — a clean repo and a repo whose floor was
    raised past every finding print the same line, and only one of those is good news.
    """
    text = _engine(monkeypatch, tmp_path, "envy_report", _ENVIOUS).report()
    assert text.startswith("feature envy (floor 4): 1"), f"count and floor lead, got {text!r}"
    assert "Manager.drive" in text, "and the finding follows"
    clean = _engine(monkeypatch, tmp_path, "envy_report_clean", _OWN_STATE).report()
    assert clean == "feature envy (floor 4): 0", "a clean run is the headline alone"


def test_run_assert(monkeypatch, tmp_path, caplog):
    """The gate view: exit code AND the logged findings.

    The code is what CI reads and the log is what the human reads; a gate returning 1 while logging nothing
    would block a build with no way to learn why, so both halves are asserted together.
    """
    with caplog.at_level(logging.ERROR):
        assert _engine(monkeypatch, tmp_path, "envy_gate", _ENVIOUS).run_assert() == 1
    assert "Manager.drive" in caplog.text, "the block says which method"
    caplog.clear()
    with caplog.at_level(logging.ERROR):
        assert _engine(monkeypatch, tmp_path, "envy_gate_ok", _OWN_STATE).run_assert() == 0
    assert caplog.text == "", "a clean run logs nothing at ERROR"
