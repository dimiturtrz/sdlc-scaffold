"""Unit tests for devtools/shape_contracts.py — jaxtyping boundary gate (ML domain).

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import ast
import sys

import pytest

from devtools.shape_contracts import ShapeContracts


def _fn(make_cls, src):
    """The first function defined in the first class of a snippet."""
    return next(m for m in make_cls(src).body if isinstance(m, ast.FunctionDef))


def test_shape_contracts_flags_bare_array_boundary(make_cls):
    names = {"ndarray", "Tensor"}
    # a public method with a bare np.ndarray param + Tensor return, no jaxtyping shape -> both flagged
    src = "class Seg:\n    def run(self, x: np.ndarray) -> Tensor:\n        return x\n"
    assert ShapeContracts._bare_array_slots(_fn(make_cls, src), names) == ["x", "->return"]


def test_shape_contracts_jaxtyping_satisfies(make_cls):
    names = {"ndarray", "Tensor"}
    # a jaxtyping subscript IS the contract -> silent; `Float[Tensor, "..."] | None` still counts
    src = (
        "class Seg:\n    def run(self, x: Float[Tensor, 'b c h w']) -> Int[np.ndarray, 'n'] | None:\n        return x\n"
    )
    assert ShapeContracts._bare_array_slots(_fn(make_cls, src), names) == [], "jaxtyping boundaries satisfy"


def test_shape_contracts_private_scanned_scalar_exempt(make_cls):
    names = {"ndarray", "Tensor"}
    # bd drn: shapes are visibility-independent — a bare tensor on a PRIVATE helper is flagged like a public one
    private = _fn(make_cls, "class C:\n    def _h(self, x: np.ndarray): ...\n")
    assert ShapeContracts._bare_array_slots(private, names) == ["x"], "private array slots are unchecked too"
    scalar = _fn(make_cls, "class C:\n    def go(self, n: int) -> float: ...\n")
    assert ShapeContracts._bare_array_slots(scalar, names) == [], "a non-array signature is not a boundary"


def test_shape_contracts_analyze_covers_private_and_module_level(make_cls):
    names = {"ndarray", "Tensor"}
    # a private method, a module-level function, and an exempt CLI handler in one tree
    tree = ast.parse(
        "class C:\n"
        "    def _h(self, x: np.ndarray): ...\n"
        "    def run(self, a: Tensor): ...\n"  # _EXEMPT dispatcher handler -> skipped
        "def top(y: Tensor) -> np.ndarray: ...\n"  # module-level -> scanned
    )
    found = {name for _, name, _ in ShapeContracts._analyze(tree, names)}
    assert found == {"C._h", "top"}, "private method + module-level func flagged; the exempt run() handler is not"


def test_array_names(make_cls, tmp_path):
    """What counts as an array is HALF the gate's meaning, and a repo extends it without forking the tool.

    The absent-file arm is load-bearing: a repo with no `[tool.shape_contracts]` must still get the builtin
    array types. Falling back to an EMPTY set instead would flag nothing and read as a clean tree — the
    silent-pass failure mode, where a gate that cannot fire looks exactly like a gate with nothing to say.
    """
    pp = tmp_path / "pyproject.toml"
    pp.write_text('[tool.shape_contracts]\narray_aliases = ["Volume", "Mask"]\n')
    names = ShapeContracts.array_names(str(pp))
    assert names == {"ndarray", "Tensor", "Volume", "Mask"}, "builtin arrays plus the repo's alias slot"
    fn = _fn(make_cls, "class C:\n    def seg(self, v: Volume) -> Mask: ...\n")
    assert ShapeContracts._bare_array_slots(fn, names) == ["v", "->return"], "alias boundaries flag like ndarray"
    assert ShapeContracts.array_names(str(tmp_path / "none.toml")) == {"ndarray", "Tensor"}, "absent -> builtins"


def test_scan(write_pkg, tmp_path, monkeypatch):
    """The package-wide walk, and the row shape every consumer (report, run_assert) reads.

    The default-`names` arm matters as much as the explicit one: `scan()` with no argument resolves the
    array names from the repo's own pyproject, which is how the CLI actually calls it — passing them in
    every test would leave that resolution path unexercised.
    """
    names = {"ndarray", "Tensor"}
    pkg = write_pkg(tmp_path, "shp", "class S:\n    def go(self, x: np.ndarray): ...\n")
    rows = ShapeContracts([pkg]).scan(names)
    assert len(rows) == 1, rows
    path, lineno, qual, slots = rows[0]
    assert (qual, lineno, slots) == ("S.go", 2, ["x"]), "the row carries where, what, and which slots"
    assert path.endswith("mod.py"), "...and the file it came from, so a finding is navigable"

    clean = write_pkg(tmp_path, "shp_ok", "class S:\n    def go(self, x: Float[Tensor, 'n']): ...\n")
    assert ShapeContracts([clean]).scan(names) == [], "a satisfied contract is not a finding"

    # No `names` argument -> resolved from the cwd's pyproject, which is the CLI's actual call.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.shape_contracts]\narray_aliases = ["Volume"]\n')
    alias_pkg = write_pkg(tmp_path, "shp_alias", "class S:\n    def go(self, v: Volume): ...\n")
    assert [r[2] for r in ShapeContracts([alias_pkg]).scan()] == ["S.go"], "the alias slot reaches the scan"


def test_report(write_pkg, tmp_path, monkeypatch):
    """The explorer view: the count line, then one navigable line per boundary.

    A boundary's line must name the file, the line number, the qualname AND the slots — a shape rollout is
    worked through this list, and a finding you cannot navigate to is a finding nobody fixes.
    """
    monkeypatch.chdir(tmp_path)
    pkg = write_pkg(tmp_path, "shp_rep", "class S:\n    def go(self, x: np.ndarray) -> Tensor: ...\n")
    text = ShapeContracts([pkg]).report()
    assert text.splitlines()[0].startswith("1 bare-array boundaries")
    assert "S.go" in text and "[x, ->return]" in text, "both bare slots are named, not just the count"
    assert "mod.py:2" in text

    clean = write_pkg(tmp_path, "shp_rep_ok", "class S:\n    def go(self, n: int): ...\n")
    assert ShapeContracts([clean]).report().startswith("0 bare-array boundaries"), "a clean tree is the header"


def test_run_assert(write_pkg, tmp_path, monkeypatch, caplog):
    """The gate view (bd 0y9) — this engine had `--assert` but gated INLINE in main(), so the one thing
    every other gate engine exposes as a method was here reachable only by running the CLI.

    Note the exit code is asserted on a tree that HAS a boundary and one that does not: the engine ships
    ADVISORY, and a repo only opts into blocking once clean, so a clean tree returning anything but 0 would
    make the ratchet impossible to ever switch on.
    """
    monkeypatch.chdir(tmp_path)
    dirty = write_pkg(tmp_path, "shp_gate", "class S:\n    def go(self, x: np.ndarray): ...\n")
    with caplog.at_level("INFO"):
        assert ShapeContracts([dirty]).run_assert() == 1
    assert "S.go" in caplog.text, "the boundaries are logged, not merely counted into an exit code"

    caplog.clear()
    clean = write_pkg(tmp_path, "shp_gate_ok", "class S:\n    def go(self, x: Float[Tensor, 'n']): ...\n")
    with caplog.at_level("INFO"):
        assert ShapeContracts([clean]).run_assert() == 0
    assert "0 bare-array boundaries" in caplog.text


def test_shape_contracts_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.shape_contracts"])
    with pytest.raises(SystemExit) as exc:
        from devtools import shape_contracts

        shape_contracts.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"
