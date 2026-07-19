"""Unit tests for devtools/envy.py — a method more interested in another class than its own."""

from devtools.envy import FeatureEnvy

_ENGINE = "class Engine:\n    def a(self): ...\n    def b(self): ...\n    def c(self): ...\n    def d(self): ...\n\n\n"


def _violations(monkeypatch, tmp_path, name: str, src: str, minimum: int = 4) -> list[str]:
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "mod.py").write_text(src)
    monkeypatch.chdir(tmp_path)
    return FeatureEnvy([name], minimum=minimum).violations()


# ---- the smell ---------------------------------------------------------------------------------------


def test_a_method_that_lives_on_another_class_is_flagged(monkeypatch, tmp_path):
    src = _ENGINE + (
        "class Manager:\n"
        "    def __init__(self, engine: Engine):\n        self._engine = engine\n\n"
        "    def drive(self):\n"
        "        self._engine.a()\n        self._engine.b()\n        self._engine.c()\n        self._engine.d()\n"
    )
    found = _violations(monkeypatch, tmp_path, "envy_hit", src)
    assert len(found) == 1
    assert "Manager.drive" in found[0] and "Engine" in found[0]
    assert "may belong on Engine" in found[0], "the finding says where the method wants to live"


def test_a_parameter_receiver_counts_too(monkeypatch, tmp_path):
    src = _ENGINE + (
        "class Manager:\n"
        "    def drive(self, engine: Engine):\n"
        "        engine.a()\n        engine.b()\n        engine.c()\n        engine.d()\n"
    )
    assert _violations(monkeypatch, tmp_path, "envy_param", src), "a param's annotation resolves the receiver"


# ---- not the smell -----------------------------------------------------------------------------------


def test_using_your_own_state_more_is_clean(monkeypatch, tmp_path):
    src = _ENGINE + (
        "class Manager:\n"
        "    def __init__(self, engine: Engine):\n        self._engine = engine\n\n"
        "    def drive(self):\n"
        "        self._engine.a()\n        self._engine.b()\n        self._engine.c()\n        self._engine.d()\n"
        "        self.x\n        self.y\n        self.z\n        self.w\n        self.v\n"
    )
    assert _violations(monkeypatch, tmp_path, "envy_own", src) == []


def test_below_the_floor_is_not_judged(monkeypatch, tmp_path):
    """Two accesses versus one is not evidence — the floor exists so the ratio is not read as noise."""
    src = _ENGINE + (
        "class Manager:\n"
        "    def __init__(self, engine: Engine):\n        self._engine = engine\n\n"
        "    def drive(self):\n        self._engine.a()\n        self._engine.b()\n"
    )
    assert _violations(monkeypatch, tmp_path, "envy_floor", src) == []


def test_reading_a_value_object_is_not_envy(monkeypatch, tmp_path):
    """A frozen dataclass is a SATELLITE — reading its fields is what it is FOR, and the fix envy implies
    (move the method onto it) is usually impossible because the method needs its own state too. This is the
    real false positive the role classification exists to remove."""
    src = (
        "@dataclass(frozen=True)\nclass Config:\n    a: int\n    b: int\n    c: int\n    d: int\n\n\n"
        "class Engine:\n"
        "    def __init__(self, config: Config):\n        self._config = config\n\n"
        "    def go(self):\n"
        "        return self._config.a + self._config.b + self._config.c + self._config.d\n"
    )
    assert _violations(monkeypatch, tmp_path, "envy_vo", src) == [], "a value object is never the envy target"


def test_talking_to_several_collaborators_is_coordination(monkeypatch, tmp_path):
    """Envy is judged against ONE class. Spreading calls across collaborators is orchestration, which is a
    different shape and often correct."""
    src = (
        "class A:\n    def go(self): ...\n\n\nclass B:\n    def go(self): ...\n\n\n"
        "class C:\n    def go(self): ...\n\n\nclass D:\n    def go(self): ...\n\n\n"
        "class Orchestrator:\n"
        "    def __init__(self, a: A, b: B, c: C, d: D):\n"
        "        self._a, self._b, self._c, self._d = a, b, c, d\n\n"
        "    def run(self):\n"
        "        self._a.go()\n        self._b.go()\n        self._c.go()\n        self._d.go()\n"
    )
    assert _violations(monkeypatch, tmp_path, "envy_orch", src) == []


def test_an_unresolvable_receiver_is_not_counted(monkeypatch, tmp_path):
    """The ratio is only ever computed over accesses we actually understand."""
    src = (
        "class Manager:\n"
        "    def drive(self, thing):\n"
        "        thing.a()\n        thing.b()\n        thing.c()\n        thing.d()\n"
    )
    assert _violations(monkeypatch, tmp_path, "envy_unres", src) == []


def test_the_floor_is_configurable(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[tool.structure]\nfeature_envy_min = 9\n")
    monkeypatch.chdir(tmp_path)
    assert FeatureEnvy.load_minimum() == 9
