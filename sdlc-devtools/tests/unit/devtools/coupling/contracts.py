"""Unit tests for devtools/contracts.py — forbidden-USE contracts over the typed arrows.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import pytest

from devtools.coupling.contracts import UseContracts

# app.service HOLDS + CALLS app.store.Store, and CONSTRUCTS app.store.Store — three arrow kinds between one
# pair of classes, which is exactly the fixture a per-kind contract needs to be shown to discriminate.
_FILES = {
    "store.py": "class Store:\n    def put(self, k: str) -> None: ...\n",
    "service.py": (
        "from app.store import Store\n\n\n"
        "class Service:\n"
        "    def __init__(self):\n"
        "        self._store = Store()\n\n"
        "    def go(self) -> None:\n"
        "        self._store.put('k')\n"
    ),
}
_ARROWS = {"calls", "construct", "holds"}


def _app(monkeypatch, tmp_path) -> None:
    """Write the two-module `app` package and cd into its parent — INPUT only, never an expected value."""
    package = tmp_path / "app"
    package.mkdir(exist_ok=True)
    (package / "__init__.py").write_text("")
    for name, src in _FILES.items():
        (package / name).write_text(src)
    monkeypatch.chdir(tmp_path)


def _engine(monkeypatch, tmp_path, contracts: list[dict]) -> UseContracts:
    _app(monkeypatch, tmp_path)
    return UseContracts(["app"], contracts=contracts)


def test_load_contracts(tmp_path):
    """`[[tool.arch.forbidden]]` off disk, and the absences that must read as "nothing configured".

    Load-bearing because "no contracts" is the SHIPPED state of every fresh consumer repo: if a missing file
    or a missing table raised, the scaffold would fail on the first run of a project that never opted in.
    The non-table row is dropped rather than fatal — `rows` narrows, and `malformed` is what judges shape.
    """
    pp = tmp_path / "pyproject.toml"
    assert UseContracts.load_contracts(str(tmp_path / "none.toml")) == [], "a missing file configures nothing"

    pp.write_text("[tool.other]\nx = 1\n")
    assert UseContracts.load_contracts(str(pp)) == [], "a pyproject with no [tool.arch] configures nothing"

    pp.write_text(
        "[[tool.arch.forbidden]]\n"
        'name = "domain must not use infra"\n'
        'source = "app.domain"\n'
        'forbidden = ["app.infra"]\n'
        'kinds = ["calls"]\n\n'
        "[[tool.arch.forbidden]]\n"
        'name = "second"\n'
        'source = "app.a"\n'
        'forbidden = ["app.b"]\n'
    )
    loaded = UseContracts.load_contracts(str(pp))
    assert len(loaded) == 2, "an array-of-tables loads every row, in order"
    assert loaded[0]["name"] == "domain must not use infra"
    assert loaded[0]["forbidden"] == ["app.infra"] and loaded[0]["kinds"] == ["calls"]
    assert "kinds" not in loaded[1], "an omitted `kinds` stays absent — that is how 'every kind' is spelled"


@pytest.mark.parametrize(
    ("contracts", "expected"),
    [
        ([], 0),
        ([{"name": "ok", "source": "a", "forbidden": ["b"]}], 0),
        # The whole vocabulary, kept in sync with what the two arrow engines actually emit. If a kind were
        # renamed in arrows.py/calls.py this row goes red — which is the point of listing them literally.
        ([{"name": "ok", "source": "a", "forbidden": ["b"], "kinds": sorted(_ARROWS | {"inherits", "references"})}], 0),
        ([{"name": "ok", "source": "a", "forbidden": ["b"], "kinds": []}], 0),  # empty = every kind, not a typo
        # A misspelled kind matches NO arrow, so the gate goes green with the rule quietly off — the same
        # failure mode as a gate wired into only some runners. It must be an error, not a silent no-op.
        ([{"name": "typo", "source": "a", "forbidden": ["b"], "kinds": ["constrct"]}], 1),
        ([{"name": "no source", "forbidden": ["b"]}], 1),
        ([{"name": "no targets", "source": "a"}], 1),
        ([{"name": "empty source", "source": "", "forbidden": ["b"]}], 1),  # present-but-falsy cannot fire either
        ([{"name": "nothing"}], 2),  # both required keys missing = both reported, not just the first
        ([{"name": "a", "forbidden": ["b"]}, {"name": "b", "source": "a"}], 2),  # findings accumulate over rows
    ],
)
def test_malformed(contracts, expected):
    broken = UseContracts.malformed(contracts)
    assert len(broken) == expected, broken
    for finding in broken:
        assert str(contracts[0].get("name", "unnamed")) in finding or len(contracts) > 1, "a finding names its rule"


def test_malformed_names_the_offending_kind():
    """Split out because the MESSAGE is the remedy here — a reader must be told which word they typo'd."""
    broken = UseContracts.malformed([{"name": "typo", "source": "a", "forbidden": ["b"], "kinds": ["constrct"]}])
    assert "unknown kind" in broken[0] and "constrct" in broken[0]
    assert "construct" in broken[0], "the message lists the real vocabulary so the fix is visible"


def test_edges(monkeypatch, tmp_path):
    """Structural AND behavioural arrows in one list — the union is what makes a contract precise.

    Load-bearing because this is where the module's thesis lives: import-linter sees ONE arrow between
    Service and Store, and this sees three. A regression that dropped either engine would still leave
    `violations` firing on the broad contract, so only a direct assertion on the union catches it.
    """
    edges = _engine(monkeypatch, tmp_path, []).edges()
    assert {kind for _s, _d, kind in edges} == _ARROWS, f"both engines contribute: {edges}"
    assert all(src == "app.service.Service" and dst == "app.store.Store" for src, dst, _k in edges), edges
    assert len(edges) == len(set(edges)), "no arrow is reported twice by the two engines"


@pytest.mark.parametrize(
    ("contract", "expected"),
    [
        # No configured rule, no findings — a fresh project starts green and ratchets.
        (None, set()),
        # Omitting `kinds` forbids EVERY kind, which is the coarse import-linter-equivalent rule.
        ({"name": "n", "source": "app.service", "forbidden": ["app.store"]}, _ARROWS),
        # The precision imports cannot express: forbid CONSTRUCTING a concrete while still permitting use.
        ({"name": "n", "source": "app.service", "forbidden": ["app.store"], "kinds": ["construct"]}, {"construct"}),
        ({"name": "n", "source": "app.service", "forbidden": ["app.store"], "kinds": ["calls"]}, {"calls"}),
        # A kind nothing emits between this pair filters everything out without erroring — `malformed` owns
        # judging whether the kind is spelled right; `violations` only matches.
        ({"name": "n", "source": "app.service", "forbidden": ["app.store"], "kinds": ["inherits"]}, set()),
        # Contracts are DIRECTIONAL — store using service would be the violation, not service using store.
        ({"name": "n", "source": "app.store", "forbidden": ["app.service"]}, set()),
        ({"name": "n", "source": "app.nothing", "forbidden": ["app.elsewhere"]}, set()),
        # A prefix covers the whole subtree: `app` as a source matches `app.service.Service` beneath it.
        ({"name": "n", "source": "app", "forbidden": ["app.store"], "kinds": ["construct"]}, {"construct"}),
        ({"name": "n", "source": "app.service", "forbidden": ["app"], "kinds": ["construct"]}, {"construct"}),
        # A prefix must match on a DOT boundary, not a bare string prefix — `app.serv` is not a package.
        ({"name": "n", "source": "app.serv", "forbidden": ["app.store"]}, set()),
    ],
)
def test_violations(monkeypatch, tmp_path, contract, expected):
    found = _engine(monkeypatch, tmp_path, [] if contract is None else [contract]).violations()
    assert {f.rsplit("--", 2)[1] if "--" in f else "" for f in found} == expected, found
    assert all(f.startswith("n: ") for f in found), "each finding names its contract"
    assert found == sorted(set(found)), "findings are deduped and stably ordered"


def test_report(monkeypatch, tmp_path):
    """The explorer view: a header carrying BOTH counts, then the findings verbatim.

    The contract count is on the header on purpose — "0 findings" reads as clean and "0 findings from 0
    contracts" reads as unconfigured, and those are different states a reader must be able to tell apart.
    """
    contract = {"name": "no construct", "source": "app.service", "forbidden": ["app.store"], "kinds": ["construct"]}
    lines = _engine(monkeypatch, tmp_path, [contract]).report().splitlines()
    assert lines[0] == "forbidden-use (1 contracts): 1"
    assert lines[1:] == ["no construct: app.service.Service --construct--> app.store.Store"]

    clean = _engine(monkeypatch, tmp_path, []).report()
    assert clean == "forbidden-use (0 contracts): 0", "an unconfigured repo reports its emptiness, not nothing"


def test_run_assert(monkeypatch, tmp_path):
    """The gate's exit code across all three outcomes, and the ORDER of the first two.

    A malformed contract must beat a clean scan: an unusable rule that never fires looks identical to a
    repo with nothing to find, so if `violations` were consulted first the config error would exit 0 and
    the rule would stay silently off forever. That precedence is the load-bearing assertion here.
    """
    assert _engine(monkeypatch, tmp_path, []).run_assert() == 0, "unconfigured is clean, not an error"

    allowed = {"name": "store must not use service", "source": "app.store", "forbidden": ["app.service"]}
    assert _engine(monkeypatch, tmp_path, [allowed]).run_assert() == 0, "a rule nothing trips passes"

    forbidden = {"name": "no construct", "source": "app.service", "forbidden": ["app.store"]}
    assert _engine(monkeypatch, tmp_path, [forbidden]).run_assert() == 1, "a real forbidden use blocks"

    # Malformed AND unviolated: nothing to find, so only the config check can produce the failure.
    broken = {"name": "typo", "source": "app.store", "forbidden": ["app.service"], "kinds": ["constrct"]}
    assert _engine(monkeypatch, tmp_path, [broken]).run_assert() == 1, "a contract that cannot fire is an error"
