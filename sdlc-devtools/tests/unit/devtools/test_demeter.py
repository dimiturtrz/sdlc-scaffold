"""Unit tests for devtools/demeter.py — calling a method on a stranger (Law of Demeter)."""

import ast

from devtools.demeter import Demeter


def _hits(src: str, max_depth: int = 2) -> list[str]:
    return Demeter([], max_depth=max_depth)._violations_in(ast.parse(src), "mod.py")


# ---- allowed: your own field, your parameters --------------------------------------------------------


def test_talking_to_your_own_field_is_fine():
    """`self.store.get(k)` is 2 hops — reach your field, then talk to it. The whole point of composition."""
    assert _hits("class A:\n    def go(self):\n        return self.store.get(1)\n") == []


def test_talking_to_a_parameter_is_fine():
    assert _hits("class A:\n    def go(self, store):\n        return store.get(1)\n") == []


def test_a_bare_attribute_is_fine():
    assert _hits("class A:\n    def go(self):\n        return self.name\n") == []


# ---- the train wreck: a CALL on a stranger -----------------------------------------------------------


def test_calling_through_a_field_is_a_violation():
    hits = _hits("class A:\n    def go(self):\n        return self.store.config.reload()\n")
    assert len(hits) == 1
    assert "calls 3 deep" in hits[0]
    assert "mod.py:3" in hits[0], "the violation names its line"


def test_the_finding_names_the_friend_to_ask_not_the_root():
    """"Ask `self`" is not advice. The friend is the field that was walked through."""
    hits = _hits("class A:\n    def go(self):\n        return self._client.session.close()\n")
    assert "ask `self._client`" in hits[0]


def test_the_friend_of_a_parameter_chain_is_the_parameter():
    hits = _hits("class A:\n    def go(self, store):\n        return store.config.logger.flush()\n")
    assert "ask `store`" in hits[0]


def test_a_deeper_wreck_reports_its_full_depth():
    assert "calls 4 deep" in _hits("class A:\n    def go(self):\n        return self.a.b.c.d()\n")[0]


def test_each_chain_is_reported_once_not_per_prefix():
    """An over-deep chain contains over-deep prefixes; the reviewer wants ONE finding, not three."""
    assert len(_hits("class A:\n    def go(self):\n        return self.a.b.c.d.e()\n")) == 1


# ---- READING is not calling (bd v3c.5) ---------------------------------------------------------------


def test_reading_a_deep_config_tree_is_not_a_violation():
    """The correction itself. `cfg.generator.synth.bg.mode` is data navigation — no stranger, no method,
    no coupling to an undeclared type. This shape was 20 of one consumer's 22 findings."""
    assert _hits("class A:\n    def go(self, cfg):\n        return cfg.generator.synth.bg.mode\n") == []


def test_reading_deep_through_self_is_not_a_violation():
    assert _hits("class A:\n    def go(self):\n        return self.cfg.generator.data.size\n") == []


def test_a_deep_read_passed_as_an_argument_is_not_a_violation():
    """There IS a call on the line — `f(...)` — but the deep chain is its argument, not its target."""
    assert _hits("class A:\n    def go(self):\n        return f(self.a.b.c.d)\n") == []


def test_assigning_a_deep_read_is_not_a_violation():
    assert _hits("class A:\n    def go(self):\n        x = self.a.b.c.d\n        return x\n") == []


def test_a_deep_call_on_the_same_line_as_a_deep_read_is_still_caught():
    """The read must not mask the call — they are different nodes and only one is a finding."""
    hits = _hits("class A:\n    def go(self):\n        return self.a.b.c.run(self.x.y.z.w)\n")
    assert len(hits) == 1
    assert "self.a.b.c.run()" in hits[0]


# ---- not object reach-through ------------------------------------------------------------------------


def test_an_imported_module_path_is_not_a_wreck():
    """`np.linalg.norm(x)` is a dotted MODULE path, not a walk across objects."""
    assert _hits("import numpy as np\n\n\nclass A:\n    def go(self):\n        return np.linalg.norm(1)\n") == []


def test_a_dotted_stdlib_module_path_is_not_a_wreck():
    src = "import logging.handlers\n\n\nclass A:\n    def go(self):\n        return logging.handlers.x.y()\n"
    assert _hits(src) == []


def test_an_imported_class_namespace_is_not_a_wreck():
    """`Path.a.b.c()` roots at an imported CLASS — a namespace, not a friend's internals."""
    assert _hits("from pathlib import Path\n\n\nclass A:\n    def go(self):\n        return Path.a.b.c()\n") == []


def test_a_chain_rooted_in_a_call_is_skipped():
    """`f().a.b.c()` has no NAME root to attribute the reach-through to — not something this gate can name."""
    assert _hits("class A:\n    def go(self):\n        return f().a.b.c()\n") == []


# ---- the ceiling is configurable ---------------------------------------------------------------------


def test_the_ceiling_is_configurable():
    src = "class A:\n    def go(self):\n        return self.a.b.c()\n"
    assert _hits(src, max_depth=2), "3 hops trips a ceiling of 2"
    assert _hits(src, max_depth=3) == [], "the same chain passes a raised ceiling (data-heavy repos)"


def test_default_ceiling_is_two(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert Demeter.load_max_depth() == 2, "no [tool.structure] -> the legislated default"


def test_ceiling_reads_the_structure_section(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("[tool.structure]\ndemeter_max_depth = 4\n")
    monkeypatch.chdir(tmp_path)
    assert Demeter.load_max_depth() == 4
