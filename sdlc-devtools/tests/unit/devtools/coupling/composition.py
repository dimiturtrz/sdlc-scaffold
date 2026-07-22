"""Unit tests for devtools/composition.py — cycles in the `holds` (has-a) object graph.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import pytest

from devtools.coupling.composition import CompositionCycles

# A owns a B that owns an A, across two modules — the canonical mutual-ownership defect, reused wherever a
# test needs a package that HAS a finding.
_MUTUAL = {
    "b.py": "from {pkg}.a import A\n\n\nclass B:\n    def __init__(self, a: A):\n        self._a = a\n",
    "a.py": "from {pkg}.b import B\n\n\nclass A:\n    def __init__(self, b: B):\n        self._b = b\n",
}
_ONE_WAY = {
    "b.py": "class B: ...\n",
    "a.py": "from {pkg}.b import B\n\n\nclass A:\n    def __init__(self, b: B):\n        self._b = b\n",
}


def _engine(monkeypatch, tmp_path, name: str, files: dict[str, str]) -> CompositionCycles:
    package = tmp_path / name
    package.mkdir()
    (package / "__init__.py").write_text("")
    for filename, src in files.items():
        (package / filename).write_text(src.format(pkg=name))
    monkeypatch.chdir(tmp_path)
    return CompositionCycles([name])


def test_graph(monkeypatch, tmp_path):
    """The object graph itself — an edge means "owns an instance of", and ONLY `holds` may put one there.

    Asserted separately from `cycles` because the subgraph choice is the reason this gate can block: `holds`
    is SOUND (a field's declared type is stated in the source, not inferred), so a `calls` or `imports` edge
    leaking in here would turn a blocking gate into a guessing one.
    """
    graph = _engine(monkeypatch, tmp_path, "comp_graph", _ONE_WAY).graph()
    assert set(graph.nodes) == {"comp_graph.a.A", "comp_graph.b.B"}
    assert set(graph.edges) == {("comp_graph.a.A", "comp_graph.b.B")}, "the owner points at the owned"

    # A class that holds nothing contributes no NODE either — the graph is built from edges, so an isolated
    # class simply cannot be in a cycle and never needs to be represented.
    bare = _engine(monkeypatch, tmp_path, "comp_graph_bare", {"a.py": "class A: ...\n"}).graph()
    assert set(bare.nodes) == set() and set(bare.edges) == set()


@pytest.mark.parametrize(
    ("name", "files", "expected", "members"),
    [
        # One-way composition is the ordinary case and must stay silent, or the gate blocks every design.
        ("comp_ok", _ONE_WAY, 0, ()),
        # A owns a B that owns an A — neither can be constructed or tested alone.
        ("comp_bad", _MUTUAL, 1, ("comp_bad.a.A", "comp_bad.b.B")),
        # The case the IMPORT cycle check structurally CANNOT see: two classes composing each other inside
        # ONE module, whose roll-up is a file self-loop and therefore no import cycle at all.
        (
            "comp_intra",
            {
                "both.py": "class A:\n    def __init__(self, b: 'B'):\n        self._b = b\n\n\n"
                "class B:\n    def __init__(self, a: A):\n        self._a = a\n"
            },
            1,
            ("comp_intra.both.A", "comp_intra.both.B"),
        ),
        # A three-class loop is ONE group, not one finding per member — the SCC is the unit of the defect.
        (
            "comp_three",
            {
                "c.py": "from {pkg}.a import A\n\n\nclass C:\n    def __init__(self, a: A):\n        self._a = a\n",
                "b.py": "from {pkg}.c import C\n\n\nclass B:\n    def __init__(self, c: C):\n        self._c = c\n",
                "a.py": "from {pkg}.b import B\n\n\nclass A:\n    def __init__(self, b: B):\n        self._b = b\n",
            },
            1,
            ("comp_three.a.A", "comp_three.b.B", "comp_three.c.C"),
        ),
        # A SELF-LOOP is a stated boundary, not an oversight (bd a0a). `holds` emits self-arrows, so a class
        # owning its own type reaches this graph — but a tree node, a linked list and a Composite are all
        # that shape and all ordinary. What cannot be built is MUTUAL ownership, so `len(component) > 1` is
        # the rule itself: a recursive type can be constructed and tested alone, a mutual pair cannot.
        ("comp_self", {"a.py": "class A:\n    def __init__(self, a: 'A'):\n        self._a = a\n"}, 0, ()),
    ],
)
def test_cycles(monkeypatch, tmp_path, name, files, expected, members):
    found = _engine(monkeypatch, tmp_path, name, files).cycles()
    assert len(found) == expected, f"{name}: expected {expected} finding(s), got {found}"
    if expected:
        assert "composition cycle" in found[0], "the finding names the rule it broke"
        # Members are sorted into the message, and the first is repeated at the end to close the loop —
        # so the reader sees the cycle as a cycle rather than as a set they must re-derive.
        for member in members:
            assert member in found[0]
        assert found[0].count(members[0]) == 2, "the loop is closed by repeating the first member"
        assert "break the loop with an interface or an owner" in found[0], "a finding carries its remedy"


def test_report(monkeypatch, tmp_path):
    """The explorer view: a count line, then the findings themselves.

    The clean arm is the load-bearing one — a report that could not render "0" would mean the only way to
    read this engine is to already have a defect.
    """
    text = _engine(monkeypatch, tmp_path, "comp_rep", _MUTUAL).report()
    assert text.splitlines()[0] == "composition cycles: 1"
    assert "comp_rep.a.A" in text, "the header is followed by the findings, not just their count"
    assert _engine(monkeypatch, tmp_path, "comp_rep_ok", _ONE_WAY).report() == "composition cycles: 0"


def test_run_assert(monkeypatch, tmp_path, caplog):
    """The gate view: an exit CODE, and the cycle logged where CI will show it.

    Code and log are asserted together deliberately — a gate returning 1 silently fails a build with no way
    to see why, and one that logs without returning 1 never blocks at all. Both halves are the contract.
    """
    with caplog.at_level("ERROR"):
        assert _engine(monkeypatch, tmp_path, "comp_gate", _MUTUAL).run_assert() == 1
    assert "BLOCKING" in caplog.text and "composition cycle" in caplog.text

    caplog.clear()
    assert _engine(monkeypatch, tmp_path, "comp_gate_ok", _ONE_WAY).run_assert() == 0
    assert "BLOCKING" not in caplog.text
