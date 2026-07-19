"""Unit tests for devtools/classes.py — class role classification + the one-subject-per-file gate."""

import ast

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
