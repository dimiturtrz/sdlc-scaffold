"""Unit tests for devtools/classes.py — class role classification + the one-subject-per-file gate."""

import ast

import pytest

from devtools.classes import PRIMARY, SATELLITE, ClassIndex


def _roles(src: str) -> dict[str, str]:
    return dict(ClassIndex.classify(ast.parse(src)))


# ---- SATELLITE equivalence classes: error / value-object / local specialisation ----------------------


def test_error_by_its_own_name_is_a_satellite():
    assert _roles("class ThingError(Exception): ...") == {"ThingError": SATELLITE}


def test_error_by_a_base_name_is_a_satellite():
    """A domain error whose own name is convention-clean still reads as an error via its base."""
    assert _roles("class Missing(StoreError): ...") == {"Missing": SATELLITE}


def test_dataclass_is_a_satellite():
    assert _roles("@dataclass\nclass Config: ...") == {"Config": SATELLITE}


def test_dotted_dataclass_decorator_is_a_satellite():
    assert _roles("@dataclasses.dataclass\nclass Config: ...") == {"Config": SATELLITE}


def test_dataclass_called_with_arguments_is_a_satellite():
    """`@dataclass(frozen=True)` is an ast.Call, not a Name — the factory form must not read as a peer."""
    assert _roles("@dataclass(frozen=True)\nclass Config: ...") == {"Config": SATELLITE}


@pytest.mark.parametrize(
    "src",
    [
        "class Cfg(BaseModel): ...",
        "class Cfg(pydantic.BaseModel): ...",
        "class Cfg(NamedTuple): ...",
        "class Cfg(TypedDict): ...",
        "@define\nclass Cfg: ...",
        "@frozen\nclass Cfg: ...",
    ],
)
def test_every_declared_data_container_is_a_satellite(src):
    """A data container is identified by being DECLARED, not by which library declares it. Keying on
    @dataclass alone tested one mechanism and scored pydantic models — the config idiom in all three
    consumer repos, and a dependency this template ships — as PRIMARY (bd az9)."""
    assert _roles(src) == {"Cfg": SATELLITE}


def test_legacy_attr_s_is_a_known_gap_not_a_silent_one():
    """`@attr.s` (attrs' pre-2020 API) reduces to the trailing name `s`, and admitting a bare `s` to the
    decorator set would match ANY `@x.s` — a worse rule than the gap it closes. The modern
    `@define`/`@frozen`/`@mutable` API is covered; this records the boundary so it is a decision rather
    than an oversight. A repo on the legacy API declares its own escape."""
    assert _roles("@attr.s\nclass Cfg: ...") == {"Cfg": PRIMARY}


def test_a_config_NAME_alone_does_not_make_a_satellite():
    """The counterpart guarantee: role follows the DECLARATION, never the name. A naming vocabulary is only
    as sound as the gate enforcing it — `Error` is safe because N818 forces it, `*Cfg` has no such backing,
    and keying on it would fit the rule to our own repos rather than to anything true."""
    assert _roles("class Config: ...") == {"Config": PRIMARY}
    assert _roles("class Settings: ...") == {"Settings": PRIMARY}


def test_enum_is_a_satellite():
    assert _roles("class Mode(StrEnum): ...") == {"Mode": SATELLITE}


def test_subclass_of_a_same_file_class_is_a_satellite():
    """A local specialisation is not a second subject — it belongs to the file's primary."""
    assert _roles("class Store: ...\nclass Fast(Store): ...") == {"Store": PRIMARY, "Fast": SATELLITE}


# ---- PRIMARY -----------------------------------------------------------------------------------------


def test_plain_behaviour_class_is_primary():
    assert _roles("class Repository: ...") == {"Repository": PRIMARY}


def test_protocol_contract_is_primary():
    """A Protocol is the file's SUBJECT (the contract), not a companion of something else."""
    assert _roles("class Store(Protocol): ...") == {"Store": PRIMARY}


def test_two_independent_peers_are_both_primary():
    assert _roles("class A: ...\nclass B: ...") == {"A": PRIMARY, "B": PRIMARY}


# ---- the gate ----------------------------------------------------------------------------------------


def _gate(write_pkg, tmp_path, name, src):
    return ClassIndex([write_pkg(tmp_path, name, src)]).multi_primary()


def test_gate_is_clean_for_one_primary_plus_its_satellites(write_pkg, tmp_path):
    """The idiomatic module: a subject, its config, its error family — one subject, so it passes."""
    src = "@dataclass\nclass Config: ...\n\n\nclass StoreError(Exception): ...\n\n\nclass Store: ...\n"
    assert _gate(write_pkg, tmp_path, "roles_clean", src) == []


def test_gate_is_clean_for_a_pure_error_module(write_pkg, tmp_path):
    """Zero primaries is fine — an error family has no subject of its own."""
    src = "class StoreError(Exception): ...\n\n\nclass MissingError(StoreError): ...\n"
    assert _gate(write_pkg, tmp_path, "roles_errors", src) == []


def test_gate_bites_on_two_primaries(write_pkg, tmp_path):
    violations = _gate(write_pkg, tmp_path, "roles_split", "class Reader: ...\n\n\nclass Writer: ...\n")
    assert len(violations) == 1
    assert "2 primary classes" in violations[0]
    assert "Reader" in violations[0] and "Writer" in violations[0]


def test_gate_reports_the_offending_file(write_pkg, tmp_path):
    violations = _gate(write_pkg, tmp_path, "roles_named", "class A: ...\n\n\nclass B: ...\n")
    assert violations[0].startswith("mod.py") or "/mod.py" in violations[0]


# ---- structural conformance (bd dun.1) ---------------------------------------------------------------

_STORE = """class Store(Protocol):
    def get(self, k): ...
    def put(self, k, v): ...
"""
_MEMORY = """class Memory:
    def get(self, k): ...
    def put(self, k, v): ...
"""
_PARTIAL = """class Partial:
    def get(self, k): ...
"""


def test_a_structural_implementation_of_a_same_file_protocol_is_a_satellite():
    """The rule already treats a same-file SUBCLASS as a local specialisation. Structural conformance is the
    same relationship without inheritance — and Protocol exists precisely so you do NOT inherit, so testing
    inheritance under-detected exactly where the modern idiom is used (bd dun.1)."""
    assert _roles(_STORE + "\n" + _MEMORY) == {"Store": PRIMARY, "Memory": SATELLITE}


def test_a_protocol_does_not_implement_itself():
    """A Protocol DECLARES the contract — it is the file's subject, not a companion. Matched against the
    same-file contracts it would satisfy its own methods and label itself a satellite of itself."""
    assert _roles(_STORE) == {"Store": PRIMARY}


def test_a_partial_implementation_stays_primary():
    """Precise but incomplete, matching the resolver's rule: only a SUPERSET of the contract counts, so a
    half-matching class is never mislabelled a companion of something it does not implement."""
    assert _roles(_STORE + "\n" + _PARTIAL) == {"Store": PRIMARY, "Partial": PRIMARY}


def test_an_empty_protocol_matches_nothing():
    """Every class satisfies a contract with no methods, so an empty Protocol must not turn a whole file
    into satellites."""
    src = "class Marker(Protocol): ...\n\n\nclass Real:\n    def run(self): ...\n"
    assert _roles(src) == {"Marker": PRIMARY, "Real": PRIMARY}
