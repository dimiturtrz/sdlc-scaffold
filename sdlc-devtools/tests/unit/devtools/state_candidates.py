"""Unit tests for devtools/state_candidates.py — namespace latent-state promotion candidates.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import sys

import pytest

from devtools import state_candidates
from devtools.state_candidates import StateCandidates

_BAG = """
class Bag:
    @staticmethod
    def load(cfg, path):
        return cfg
    @staticmethod
    def save(cfg, data):
        return cfg
"""

_STATEFUL = (
    "class Stateful:\n"
    "    def __init__(self, cfg):\n"
    "        self.cfg = cfg\n"
    "    @staticmethod\n"
    "    def load(cfg, path): ...\n"
    "    @staticmethod\n"
    "    def save(cfg, data): ...\n"
)
_PYDANTIC = (
    "class Cfg(BaseModel):\n    @staticmethod\n    def a(cfg, x): ...\n    @staticmethod\n    def b(cfg, y): ...\n"
)
_COMMAND = "class Cmd:\n    @staticmethod\n    def add_args(cfg, p): ...\n    @staticmethod\n    def run(cfg, a): ...\n"
_AUTOGRAD = (
    "class GradReverse(Function):\n"
    "    @staticmethod\n    def forward(ctx, x):\n        return x\n"
    "    @staticmethod\n    def backward(ctx, g):\n        return g\n"
)
_ONE_METHOD = "class Lonely:\n    @staticmethod\n    def only(cfg, x): ...\n"


@pytest.mark.parametrize(
    ("case", "src", "expected"),
    [
        ("a param threaded by every staticmethod IS the latent instance state", _BAG, {"cfg": 2}),
        # Every row below is an EXEMPTION, and each exists because the detector fired wrongly on it once.
        ("__init__ present — already stateful, nothing to promote", _STATEFUL, {}),
        ("pydantic config — its shared params are declared FIELDS, not latent state", _PYDANTIC, {}),
        ("CLI dispatcher (add_args + run) — legitimately stateless", _COMMAND, {}),
        # forward/backward thread ctx by the torch.autograd.Function contract, not latent state (76i).
        ("autograd.Function — ctx is a framework contract", _AUTOGRAD, {}),
        # One method cannot SHARE anything; the >=2 floor is what stops a single signature reading as state.
        ("a single staticmethod — below the floor", _ONE_METHOD, {}),
    ],
)
def test_shared_state(case, src, expected, make_cls):
    assert StateCandidates.shared_state(make_cls(src)) == expected, case


def test_scan(tmp_path, monkeypatch):
    """Ranking across a tree, and the coverage-omit skip proved in BOTH directions.

    The same package is scanned twice with only `omit` changed, because an empty result is ambiguous on its
    own — a broken scan and a working skip look identical, and the un-omitted run is what tells them apart.
    """
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "shell.py").write_text(_BAG)  # a namespace bag that WOULD flag (load/save thread cfg)
    # coverage-omitted -> the shell is skipped (its shared params are data, not object identity)
    (tmp_path / "pyproject.toml").write_text('[tool.coverage.run]\nomit = ["pkg/shell.py"]\n')
    assert StateCandidates(["pkg"]).scan() == [], "a coverage-omitted shell is not a state-promotion candidate"

    (tmp_path / "pyproject.toml").write_text("[tool.coverage.run]\nomit = []\n")
    rows = StateCandidates(["pkg"]).scan()
    assert rows, "un-omitted, the namespace bag is flagged"
    score, name, path, methods, shared = rows[0]
    assert (name, methods, shared) == ("Bag", 2, {"cfg": 2}), "the row carries class, method count and the params"
    assert score == 2, "the score sums the shared counts, so 'many methods thread many params' ranks highest"
    assert path.endswith("shell.py"), "the file is relative to the scan root — an absolute path is not portable"


def test_report(tmp_path, monkeypatch):
    """The explorer view: a headline count, a header row, then one ranked line per candidate.

    Ranking is the product here — the whole point of scoring is that the worst offender is read FIRST — so
    the order of the rendered lines is asserted, not just their presence.
    """
    monkeypatch.chdir(tmp_path)
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "small.py").write_text(_BAG)
    (pkg / "big.py").write_text(
        "class Heavy:\n"
        "    @staticmethod\n    def a(cfg, root, x): ...\n"
        "    @staticmethod\n    def b(cfg, root, y): ...\n"
        "    @staticmethod\n    def c(cfg, root, z): ...\n"
    )
    (tmp_path / "pyproject.toml").write_text("[tool.coverage.run]\nomit = []\n")

    text = StateCandidates(["pkg"]).report()
    lines = text.splitlines()
    assert lines[0] == "2 promotion candidates", "the headline counts the rows, not the files scanned"
    assert "score" in lines[1] and "class" in lines[1], "a header row labels the columns"
    assert lines[2].split()[1] == "Heavy", "the higher score sorts first — the ranking IS the product"
    assert lines[3].split()[1] == "Bag"
    assert "cfg×3" in lines[2] and "root×3" in lines[2], "every shared param is shown with its method count"

    (pkg / "small.py").unlink()
    (pkg / "big.py").unlink()
    assert StateCandidates(["pkg"]).report().startswith("0 promotion candidates"), "a clean tree still reports"


def test_state_candidates_main_requires_packages(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["devtools.state_candidates"])
    with pytest.raises(SystemExit) as exc:
        state_candidates.main()
    assert exc.value.code == 2, "no-arg invocation must be an argparse usage error"
