"""Unit tests for devtools/classes.py — class role classification + the one-subject-per-file gate.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import ast

import pytest

from devtools.primitives.classes import PRIMARY, SATELLITE, ClassIndex


def _roles(src: str) -> dict[str, str]:
    return dict(ClassIndex.classify(ast.parse(src)))


def _cls(src: str) -> ast.ClassDef:
    return next(n for n in ast.parse(src).body if isinstance(n, ast.ClassDef))


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


def test_role(make_cls):
    """The classifier's own parameter surface — `siblings` and `contracts` supplied DIRECTLY.

    `classify` derives both from a module, so driving them by hand is the only way to pin what they mean:
    a class is a satellite of a name it did not import, purely by that name being a same-file sibling. The
    `contracts=None` default matters too — `role` is a public seam callable without the Protocol tier, and
    a None that crashed would make the cheap call site impossible.
    """
    store = make_cls("class Store: ...")
    fast = make_cls("class Fast(Store): ...")
    assert ClassIndex.role(store, set()) == PRIMARY, "no siblings, no decorators — the file's subject"
    assert ClassIndex.role(fast, {"Store"}) == SATELLITE, "a local specialisation is not a competing subject"
    assert ClassIndex.role(fast, set()) == PRIMARY, "the SAME class is primary elsewhere — siblings decide"
    assert ClassIndex.role(fast, {"Other"}) == PRIMARY, "an unrelated sibling does not subordinate it"

    # `contracts` is the structural half: a superset of a same-file Protocol's public methods is a satellite
    # without inheriting anything. Passing None must behave exactly like passing no contracts at all.
    memory = _cls(_MEMORY)
    assert ClassIndex.role(memory, set(), [{"get", "put"}]) == SATELLITE
    assert ClassIndex.role(memory, set(), [{"get"}]) == SATELLITE, "a SUPERSET of the contract counts"
    assert ClassIndex.role(memory, set(), [{"get", "put", "drop"}]) == PRIMARY, "a partial match does not"
    assert ClassIndex.role(memory, set(), []) == PRIMARY
    assert ClassIndex.role(memory, set(), None) == ClassIndex.role(memory, set(), []), "None == no contracts"


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        # ---- SATELLITE: error ----
        ("class ThingError(Exception): ...", {"ThingError": SATELLITE}),
        # A domain error whose own name is convention-clean still reads as an error via its BASE.
        ("class Missing(StoreError): ...", {"Missing": SATELLITE}),
        ("class Thing(SomeException): ...", {"Thing": SATELLITE}),
        # ---- SATELLITE: declared data container, across every spelling ----
        ("@dataclass\nclass Config: ...", {"Config": SATELLITE}),
        ("@dataclasses.dataclass\nclass Config: ...", {"Config": SATELLITE}),
        # `@dataclass(frozen=True)` is an ast.Call, not a Name — the factory form must not read as a peer.
        ("@dataclass(frozen=True)\nclass Config: ...", {"Config": SATELLITE}),
        # A container is identified by being DECLARED, not by which library declares it. Keying on
        # @dataclass alone tested one MECHANISM and scored pydantic models — the config idiom in all three
        # consumer repos, and a dependency this template ships — as PRIMARY (bd az9).
        ("class Cfg(BaseModel): ...", {"Cfg": SATELLITE}),
        ("class Cfg(pydantic.BaseModel): ...", {"Cfg": SATELLITE}),
        ("class Cfg(NamedTuple): ...", {"Cfg": SATELLITE}),
        ("class Cfg(TypedDict): ...", {"Cfg": SATELLITE}),
        ("@define\nclass Cfg: ...", {"Cfg": SATELLITE}),
        ("@frozen\nclass Cfg: ...", {"Cfg": SATELLITE}),
        # `@attr.s` (attrs' pre-2020 API) reduces to the trailing name `s`, and admitting a bare `s` to the
        # decorator set would match ANY `@x.s` — a worse rule than the gap it closes. Recorded here so the
        # boundary is a decision rather than an oversight; a repo on the legacy API declares its own escape.
        ("@attr.s\nclass Cfg: ...", {"Cfg": PRIMARY}),
        # The counterpart guarantee: role follows the DECLARATION, never the name. A naming vocabulary is
        # only as sound as the gate enforcing it — `Error` is safe because ruff's N818 forces it, `*Cfg` has
        # no such backing, and keying on it would fit the rule to our own repos rather than to anything true.
        ("class Config: ...", {"Config": PRIMARY}),
        ("class Settings: ...", {"Settings": PRIMARY}),
        # ---- SATELLITE: enum / local specialisation ----
        ("class Mode(StrEnum): ...", {"Mode": SATELLITE}),
        ("class Mode(Enum): ...", {"Mode": SATELLITE}),
        ("class Store: ...\nclass Fast(Store): ...", {"Store": PRIMARY, "Fast": SATELLITE}),
        # ---- PRIMARY ----
        ("class Repository: ...", {"Repository": PRIMARY}),
        ("class A: ...\nclass B: ...", {"A": PRIMARY, "B": PRIMARY}),
        ("", {}),  # a module with no classes classifies to nothing, not an error
        # ---- structural conformance (bd dun.1) ----
        # The rule already treats a same-file SUBCLASS as a local specialisation. Structural conformance is
        # the same relationship without inheritance — and Protocol exists precisely so you do NOT inherit,
        # so testing inheritance under-detected exactly where the modern idiom is used.
        (_STORE + "\n" + _MEMORY, {"Store": PRIMARY, "Memory": SATELLITE}),
        # A Protocol DECLARES the contract — it is the file's subject, not a companion. Matched against the
        # same-file contracts it would satisfy its own methods and label itself a satellite of itself.
        (_STORE, {"Store": PRIMARY}),
        # Precise but incomplete, matching the resolver's rule: only a SUPERSET of the contract counts, so a
        # half-matching class is never mislabelled a companion of something it does not implement.
        (_STORE + "\n" + _PARTIAL, {"Store": PRIMARY, "Partial": PRIMARY}),
        # Every class satisfies a contract with no methods, so an empty Protocol must not turn a whole file
        # into satellites.
        (
            "class Marker(Protocol): ...\n\n\nclass Real:\n    def run(self): ...\n",
            {"Marker": PRIMARY, "Real": PRIMARY},
        ),
    ],
)
def test_classify(src, expected):
    assert _roles(src) == expected


def test_classify_preserves_source_order():
    """Split out because `by_file` and `report` both surface this list verbatim — a set-like return would
    make the explorer view reorder between runs for no reason a reader could explain."""
    src = "class Z: ...\n\n\nclass A: ...\n\n\n@dataclass\nclass M: ...\n"
    assert ClassIndex.classify(ast.parse(src)) == [("Z", PRIMARY), ("A", PRIMARY), ("M", SATELLITE)]


def test_by_file(write_pkg, tmp_path):
    """The containment tier: every module under the roots, INCLUDING the ones defining nothing.

    A classless file mapping to `[]` rather than being absent is load-bearing — `multi_primary` and
    `report` both iterate this, and an omitted key would silently narrow the population they walk.
    """
    src = "@dataclass\nclass Config: ...\n\n\nclass StoreError(Exception): ...\n\n\nclass Store: ...\n"
    index = ClassIndex([write_pkg(tmp_path, "byfile", src)]).by_file()
    by_name = {path.name: records for path, records in index.items()}
    assert set(by_name) == {"__init__.py", "mod.py"}, "every module in the package is a key"
    assert by_name["__init__.py"] == [], "a classless module is present and empty, not missing"
    assert by_name["mod.py"] == [("Config", SATELLITE), ("StoreError", SATELLITE), ("Store", PRIMARY)]


@pytest.mark.parametrize(
    ("name", "src", "primaries"),
    [
        # The idiomatic module: a subject, its config, its error family — one subject, so it passes.
        (
            "roles_clean",
            "@dataclass\nclass Config: ...\n\n\nclass StoreError(Exception): ...\n\n\nclass Store: ...\n",
            [],
        ),
        # Zero primaries is fine — an error family has no subject of its own.
        ("roles_errors", "class StoreError(Exception): ...\n\n\nclass MissingError(StoreError): ...\n", []),
        ("roles_empty", "", []),
        ("roles_split", "class Reader: ...\n\n\nclass Writer: ...\n", ["Reader", "Writer"]),
        ("roles_three", "class A: ...\n\n\nclass B: ...\n\n\nclass C: ...\n", ["A", "B", "C"]),
        # A local specialisation drops the count back under the threshold — the gate counts SUBJECTS, not
        # classes, which is the whole reason `role` exists rather than a bare class-per-file limit.
        ("roles_specialised", "class Store: ...\n\n\nclass Fast(Store): ...\n", []),
    ],
)
def test_multi_primary(write_pkg, tmp_path, name, src, primaries):
    found = ClassIndex([write_pkg(tmp_path, name, src)]).multi_primary()
    assert len(found) == (1 if primaries else 0), found
    for expected in primaries:
        assert expected in found[0], "the finding names every competing subject so the split is actionable"
    if primaries:
        assert f"{len(primaries)} primary classes" in found[0]
        assert "mod.py" in found[0], "the finding names the offending FILE — the fix is a file operation"


def test_report(write_pkg, tmp_path):
    """The explorer view: one line per file, then an indented `role name` per class, in source order.

    Classless files are SKIPPED here although `by_file` keeps them — the report is for a human scanning
    roles, and a page of bare `__init__.py` headers with nothing under them is noise, not information.
    """
    src = "@dataclass\nclass Config: ...\n\n\nclass Reader: ...\n\n\nclass Writer: ...\n"
    lines = ClassIndex([write_pkg(tmp_path, "report_pkg", src)]).report().splitlines()
    assert len(lines) == 4, lines
    assert lines[0].endswith("mod.py") and "__init__" not in "\n".join(lines), "classless files are omitted"
    assert lines[1:] == ["  satellite Config", "  primary   Reader", "  primary   Writer"]

    empty = ClassIndex([write_pkg(tmp_path, "report_empty", "x = 1\n")]).report()
    assert empty == "", "a package with no classes reports nothing at all, not a header"


def test_run_assert(write_pkg, tmp_path):
    """The gate's exit code, over the two outcomes and the zero-primary edge.

    Zero primaries returning 0 is the load-bearing one: the rule is "not more than one subject", so a
    module of pure errors must pass. A gate demanding exactly one would force a stub class into every
    `errors.py` in the tree.
    """
    clean = "@dataclass\nclass Config: ...\n\n\nclass Store: ...\n"
    assert ClassIndex([write_pkg(tmp_path, "assert_clean", clean)]).run_assert() == 0
    assert ClassIndex([write_pkg(tmp_path, "assert_errors", "class AError(Exception): ...\n")]).run_assert() == 0
    assert ClassIndex([write_pkg(tmp_path, "assert_empty", "")]).run_assert() == 0
    split = "class Reader: ...\n\n\nclass Writer: ...\n"
    assert ClassIndex([write_pkg(tmp_path, "assert_split", split)]).run_assert() == 1
