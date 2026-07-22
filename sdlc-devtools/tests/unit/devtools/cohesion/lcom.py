"""Unit tests for devtools/lcom.py — LCOM4 cohesion (positive split + the strategy-pattern exemptions).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import sys

import pytest

from devtools.cohesion import lcom
from devtools.cohesion.lcom import Lcom

# two disjoint self-field groups: {a,b} touch self.x, {c,d} touch self.y -> LCOM4 == 2
_SPLIT = """
class Split:
    def a(self):
        return self.x
    def b(self):
        self.x += 1
    def c(self):
        return self.y
    def d(self):
        self.y += 1
"""

# every method touches self.x -> one component -> cohesive
_COHESIVE = """
class Cohesive:
    def a(self):
        return self.x
    def b(self):
        self.x += 1
    def c(self):
        return self.x * 2
"""

# One method CALLS the other and they share no field — the call is itself an edge, so LCOM4 is 1. Without
# this, any delegating pair would read as fused and the metric would fire on ordinary decomposition.
_CALL_LINKED = """
class Chain:
    def a(self):
        return self.helper()
    def helper(self):
        return self.y
"""


def test_lcom4(make_cls):
    """The raw metric: component count + membership, over connected-by-field and connected-by-call."""
    score, comps = Lcom.lcom4(make_cls(_SPLIT))
    assert score == 2, f"two disjoint groups must give LCOM4==2, got {score}: {comps}"
    assert {frozenset(c) for c in comps} == {frozenset({"a", "b"}), frozenset({"c", "d"})}

    score, comps = Lcom.lcom4(make_cls(_COHESIVE))
    assert score == 1, "a class whose methods share a field is cohesive (LCOM4==1)"
    assert {frozenset(c) for c in comps} == {frozenset({"a", "b", "c"})}

    assert Lcom.lcom4(make_cls(_CALL_LINKED))[0] == 1, "one method calling the other is an edge, not a split"
    assert Lcom.lcom4(make_cls("class Empty:\n    pass\n")) == (0, []), "no methods -> no components"


@pytest.mark.parametrize(
    ("source", "splits"),
    [
        (_SPLIT, True),
        (_COHESIVE, False),
        # A DOMAIN base means a polymorphic impl: its method split mirrors the interface contract, not real
        # fusion. This is the exemption that keeps raw LCOM4 usable on a strategy-pattern codebase.
        (
            "class Backend(BaseStore):\n    def read(self):\n        return self.a\n"
            "    def draw(self):\n        return self.b\n",
            False,
        ),
        # An ABC declares independent facets by design; a trivial-bodied stub holds no state to fuse at all.
        ("class I(ABC):\n    def a(self):\n        return self.x\n    def b(self):\n        return self.y\n", False),
        ("class Stub:\n    def a(self): ...\n    def b(self): ...\n", False),
        ("class One:\n    def a(self):\n        return self.x\n", False),  # LCOM is undefined below 2 methods
        # fit writes learned state, transform reads different state -> raw LCOM4 == 2, but that split IS the
        # sklearn duck-typed contract (bd 76i). Name-based, since the contract has no base class to key on.
        (
            "class Scaler:\n    def fit(self, X):\n        self.mean = X\n"
            "    def transform(self, X):\n        return self.scale\n",
            False,
        ),
        (
            "class Est:\n    def fit(self, X):\n        self.a = X\n"
            "    def __call__(self, X):\n        return self.b\n",
            False,
        ),
    ],
)
def test_is_split_candidate(make_cls, source, splits):
    assert (Lcom._is_split_candidate(make_cls(source)) is not None) == splits


def test_the_sklearn_contract_is_exempt_despite_a_real_split(make_cls):
    """The exemption is a POLICY layered over the metric, not a hole in it — the raw score still says 2."""
    src = (
        "class Scaler:\n    def fit(self, X):\n        self.mean = X\n"
        "    def transform(self, X):\n        return self.scale\n"
    )
    assert Lcom.lcom4(make_cls(src))[0] == 2, "fit/transform touch disjoint state -> raw LCOM4 is 2"
    assert Lcom._is_split_candidate(make_cls(src)) is None, "but fit+transform is exempt as the sklearn contract"


def test_scan(write_pkg, tmp_path):
    """The package-level sweep: only genuine split candidates survive, ranked worst-first, located.

    Driven through a real package rather than a list of ClassDefs because `scan` IS the walk — what it adds
    over `_is_split_candidate` is the filtering and the ranking, and neither is visible on a single class.
    """
    src = _SPLIT + _COHESIVE + "\nclass Stub:\n    def a(self): ...\n    def b(self): ...\n"
    rows = Lcom([write_pkg(tmp_path, "lcom_scan", src)]).scan()
    assert [name for _, name, _, _ in rows] == ["Split"], f"only the genuine split is reported, got {rows}"
    score, name, path, comps = rows[0]
    assert score == 2 and name == "Split"
    assert path.endswith("mod.py"), f"the row locates the class, got {path}"
    assert {frozenset(c) for c in comps} == {frozenset({"a", "b"}), frozenset({"c", "d"})}

    two = (
        _SPLIT
        + "\nclass Wider:\n    def a(self):\n        return self.x\n"
        "    def b(self):\n        return self.y\n    def c(self):\n        return self.z\n"
    )
    scores = [row[0] for row in Lcom([write_pkg(tmp_path, "lcom_rank", two)]).scan()]
    assert scores == sorted(scores, reverse=True), f"worst cohesion first, got {scores}"

    assert Lcom([write_pkg(tmp_path, "lcom_clean", _COHESIVE)]).scan() == [], "a cohesive tree is no findings"


def test_report(write_pkg, tmp_path):
    """The explorer view: `report` computes its own rows, so a caller needs only the engine.

    The count line is the part a reviewer reads first, and it must agree with the table beneath it — a header
    saying 0 over a non-empty table (or the reverse) is the one way this view can actively mislead.
    """
    text = Lcom([write_pkg(tmp_path, "lcom_report", _SPLIT)]).report()
    assert text.startswith("1 low-cohesion classes (LCOM4>=2)"), text.splitlines()[0]
    assert "Split" in text and "lcom4" in text, "the ranked table names the class under a header"
    assert "{a, b}" in text and "{c, d}" in text, "each disjoint group is shown — that is the extract-me hint"

    clean = Lcom([write_pkg(tmp_path, "lcom_report_clean", _COHESIVE)]).report()
    assert clean.startswith("0 low-cohesion classes"), "a clean tree still renders a header, not an empty string"
    assert "Cohesive" not in clean


def test_lcom_main_requires_packages(monkeypatch):
    # nargs="+" -> no positional makes argparse exit(2), never a vacuous scan of a phantom 'src' (skr GAP2)
    monkeypatch.setattr(sys, "argv", ["devtools.lcom"])
    with pytest.raises(SystemExit) as exc:
        lcom.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"
