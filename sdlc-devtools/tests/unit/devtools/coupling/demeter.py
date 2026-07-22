"""Unit tests for devtools/demeter.py — calling a method on a stranger (Law of Demeter).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import ast

import pytest

from devtools.coupling.demeter import Demeter

# A chain that trips the default ceiling of 2, used wherever a test needs a package that HAS a finding.
_WRECK = "class A:\n    def go(self):\n        return self.store.config.reload()\n"


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
    """ "Ask `self`" is not advice. The friend is the field that was walked through."""
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


@pytest.mark.parametrize(
    ("pyproject_text", "expected"),
    [
        # No pyproject at all -> the LEGISLATED default. 2 is "use your own field", 3 is already reaching
        # past it, and a repo that never states a ceiling still gets gated at the doctrine's number.
        (None, 2),
        ("[tool.structure]\ndemeter_max_depth = 4\n", 4),
        # A [tool.structure] that exists but is silent on this key must still default rather than blow up —
        # every other structure gate shares this section, so its presence says nothing about ours.
        ('[tool.structure]\ntest_layout = "off"\n', 2),
    ],
)
def test_load_max_depth(tmp_path, monkeypatch, pyproject_text, expected):
    """The ceiling is config, and where it comes from is the whole contract of this method."""
    monkeypatch.chdir(tmp_path)
    if pyproject_text is not None:
        (tmp_path / "pyproject.toml").write_text(pyproject_text)
    assert Demeter.load_max_depth() == expected


# ---- the whole-package surface: violations / report / run_assert -------------------------------------


def _pkg(tmp_path, write_pkg, name: str, src: str) -> Demeter:
    """A Demeter over a real one-module package. `max_depth` is passed explicitly so these tests exercise
    the WALK, not the config load — `test_load_max_depth` owns that half."""
    return Demeter([write_pkg(tmp_path, name, src)], max_depth=2)


def test_violations(tmp_path, write_pkg):
    """The package-wide walk: `_violations_in` finds a wreck in one tree, this finds them across the tree
    set and stamps each with the file it came from. The clean arm is load-bearing — a gate that cannot
    return an empty list cannot ever pass."""
    found = _pkg(tmp_path, write_pkg, "dem_bad", _WRECK).violations()
    assert len(found) == 1
    assert "mod.py:3" in found[0], "the finding carries the real path, not the in-memory label"
    assert "calls 3 deep (> 2)" in found[0] and "ask `self.store`" in found[0]

    clean = "class A:\n    def go(self):\n        return self.store.get(1)\n"
    assert _pkg(tmp_path, write_pkg, "dem_ok", clean).violations() == []


def test_report(tmp_path, write_pkg):
    """The explorer view. The header states the CEILING as well as the count, because "3 findings" means
    nothing without the number they were measured against — a raised ceiling changes what the list is."""
    text = _pkg(tmp_path, write_pkg, "dem_rep", _WRECK).report()
    assert text.splitlines()[0] == "law of demeter (max depth 2): 1"
    assert "calls 3 deep" in text, "the header is followed by the findings themselves, not just a count"

    clean = _pkg(tmp_path, write_pkg, "dem_rep_ok", "class A:\n    def go(self): ...\n").report()
    assert clean == "law of demeter (max depth 2): 0", "a clean run is the header alone, with no trailing blank"


def test_run_assert(tmp_path, write_pkg, caplog):
    """The gate view: an exit CODE, and the findings logged where CI will show them.

    Asserting the code and the log together is the point — a gate that returned 1 silently would fail the
    build with no way to see why, and one that logged without returning 1 would never block at all.
    """
    with caplog.at_level("ERROR"):
        assert _pkg(tmp_path, write_pkg, "dem_gate", _WRECK).run_assert() == 1
    assert "BLOCKING" in caplog.text and "calls 3 deep" in caplog.text

    caplog.clear()
    assert _pkg(tmp_path, write_pkg, "dem_gate_ok", "class A:\n    def go(self): ...\n").run_assert() == 0
    assert "BLOCKING" not in caplog.text
