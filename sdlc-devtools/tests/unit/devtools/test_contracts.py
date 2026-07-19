"""Unit tests for devtools/contracts.py — forbidden-USE contracts over the typed arrows."""

from devtools.contracts import UseContracts

# app.service HOLDS + CALLS app.store.Store, and CONSTRUCTS app.store.Store
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


def _violations(monkeypatch, tmp_path, contracts: list[dict]) -> list[str]:
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    for name, src in _FILES.items():
        (pkg / name).write_text(src)
    monkeypatch.chdir(tmp_path)
    return UseContracts(["app"], contracts=contracts).violations()


def test_no_contracts_means_nothing_to_check(monkeypatch, tmp_path):
    """A fresh project starts green and ratchets — no configured rule, no findings."""
    assert _violations(monkeypatch, tmp_path, []) == []


def test_a_forbidden_use_is_caught_across_every_kind(monkeypatch, tmp_path):
    contract = {"name": "service must not use store", "source": "app.service", "forbidden": ["app.store"]}
    found = _violations(monkeypatch, tmp_path, [contract])
    assert found, "the arrows from service to store must trip the contract"
    assert all("service must not use store" in f for f in found), "each finding names its contract"


def test_a_contract_can_target_ONE_kind(monkeypatch, tmp_path):
    """The precision imports cannot express: forbid CONSTRUCTING a concrete while still permitting use."""
    contract = {
        "name": "only wiring may construct",
        "source": "app.service",
        "forbidden": ["app.store"],
        "kinds": ["construct"],
    }
    found = _violations(monkeypatch, tmp_path, [contract])
    assert len(found) == 1, f"exactly the construction, not the calls/holds: {found}"
    assert "--construct-->" in found[0]


def test_the_reverse_direction_is_not_forbidden(monkeypatch, tmp_path):
    """Contracts are DIRECTIONAL — store using service would be the violation, not service using store."""
    contract = {"name": "store must not use service", "source": "app.store", "forbidden": ["app.service"]}
    assert _violations(monkeypatch, tmp_path, [contract]) == []


def test_an_unrelated_contract_stays_silent(monkeypatch, tmp_path):
    contract = {"name": "unrelated", "source": "app.nothing", "forbidden": ["app.elsewhere"]}
    assert _violations(monkeypatch, tmp_path, [contract]) == []


def test_a_prefix_covers_the_whole_subtree(monkeypatch, tmp_path):
    """`app` as a source covers `app.service.Service` — layers are named by module prefix."""
    contract = {"name": "package-wide", "source": "app", "forbidden": ["app.store"], "kinds": ["construct"]}
    assert _violations(monkeypatch, tmp_path, [contract]), "a prefix matches classes beneath it"


def test_findings_are_deduped(monkeypatch, tmp_path):
    contract = {"name": "dupe check", "source": "app.service", "forbidden": ["app.store"], "kinds": ["calls"]}
    found = _violations(monkeypatch, tmp_path, [contract])
    assert len(found) == len(set(found))


# ---- a contract that CANNOT fire is a config error, not a pass ---------------------------------------


def test_an_unknown_kind_is_reported_not_silently_ignored():
    """`kinds = ["constrct"]` matches no arrow, so the gate would go green with the rule quietly off —
    the same failure mode as a gate wired into only some runners. It must be an error instead."""
    broken = UseContracts.malformed([{"name": "typo", "source": "a", "forbidden": ["b"], "kinds": ["constrct"]}])
    assert len(broken) == 1
    assert "unknown kind" in broken[0] and "constrct" in broken[0]


def test_a_missing_source_or_forbidden_is_reported():
    assert UseContracts.malformed([{"name": "no source", "forbidden": ["b"]}])
    assert UseContracts.malformed([{"name": "no targets", "source": "a"}])


def test_every_real_kind_is_accepted():
    """The vocabulary a contract may name — kept in sync with what the two engines actually emit."""
    kinds = ["inherits", "holds", "references", "calls", "construct"]
    assert UseContracts.malformed([{"name": "ok", "source": "a", "forbidden": ["b"], "kinds": kinds}]) == []


def test_a_well_formed_contract_is_not_flagged():
    assert UseContracts.malformed([{"name": "ok", "source": "a", "forbidden": ["b"]}]) == []
