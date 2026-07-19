"""Unit tests for devtools/composition.py — cycles in the `holds` (has-a) object graph."""

from devtools.composition import CompositionCycles


def _cycles(monkeypatch, tmp_path, name: str, files: dict[str, str]) -> list[str]:
    pkg = tmp_path / name
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for filename, src in files.items():
        (pkg / filename).write_text(src)
    monkeypatch.chdir(tmp_path)
    return CompositionCycles([name]).cycles()


def test_a_one_way_composition_is_fine(monkeypatch, tmp_path):
    files = {
        "b.py": "class B: ...\n",
        "a.py": "from comp_ok.b import B\n\n\nclass A:\n    def __init__(self, b: B):\n        self._b = b\n",
    }
    assert _cycles(monkeypatch, tmp_path, "comp_ok", files) == []


def test_mutual_composition_is_a_cycle(monkeypatch, tmp_path):
    """A owns a B that owns an A — neither can be constructed or tested alone."""
    files = {
        "b.py": "from comp_bad.a import A\n\n\nclass B:\n    def __init__(self, a: A):\n        self._a = a\n",
        "a.py": "from comp_bad.b import B\n\n\nclass A:\n    def __init__(self, b: B):\n        self._b = b\n",
    }
    found = _cycles(monkeypatch, tmp_path, "comp_bad", files)
    assert len(found) == 1
    assert "composition cycle" in found[0]
    assert "comp_bad.a.A" in found[0] and "comp_bad.b.B" in found[0]


def test_an_intra_file_composition_cycle_is_caught(monkeypatch, tmp_path):
    """The case the IMPORT cycle check structurally cannot see: two classes composing each other inside
    ONE module, whose roll-up is a file self-loop and therefore no import cycle at all."""
    src = (
        "class A:\n    def __init__(self, b: 'B'):\n        self._b = b\n\n\n"
        "class B:\n    def __init__(self, a: A):\n        self._a = a\n"
    )
    found = _cycles(monkeypatch, tmp_path, "comp_intra", {"both.py": src})
    assert len(found) == 1, f"expected one intra-file cycle, got {found}"


def test_a_holds_cycle_through_three_classes_is_one_finding(monkeypatch, tmp_path):
    files = {
        "c.py": "from comp_three.a import A\n\n\nclass C:\n    def __init__(self, a: A):\n        self._a = a\n",
        "b.py": "from comp_three.c import C\n\n\nclass B:\n    def __init__(self, c: C):\n        self._c = c\n",
        "a.py": "from comp_three.b import B\n\n\nclass A:\n    def __init__(self, b: B):\n        self._b = b\n",
    }
    assert len(_cycles(monkeypatch, tmp_path, "comp_three", files)) == 1, "one group, not one per member"
