"""Unit tests for devtools/pyproject.py — the shared `[tool.<section>]` reader and its TOML narrowers.

Written in the method-mirror convention (docs/UNIT_TESTS.md): one `test_<method>` per public method, each a
dense container of parameter combinations rather than one case per behaviour.
"""

import pytest

from devtools.plumbing.pyproject import STRUCTURE_DEFAULTS, Pyproject


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ({"a": 1}, {"a": 1}),
        ({}, {}),
        # Everything that is NOT a table narrows to {} rather than raising: these readers sit under
        # `.get(...)` chains, so a missing/wrong-shaped section has to be chainable, not fatal.
        (None, {}),
        ([{"a": 1}], {}),
        ("a", {}),
        (7, {}),
    ],
)
def test_table(value, expected):
    assert Pyproject.table(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["a", "b"], ["a", "b"]),
        ([], []),
        # Non-strings are DROPPED, not rejected — deliberate per the docstring: unlike a threshold, a stray
        # entry in a glob/alias list cannot make a gate quietly pass at a value nobody set.
        (["a", 1, None, {"b": 2}, "c"], ["a", "c"]),
        ([1, 2], []),
        (None, []),
        ("abc", []),  # a bare string is NOT iterated into ["a", "b", "c"] — the shape check comes first
        ({"a": "b"}, []),
    ],
)
def test_str_list(value, expected):
    assert Pyproject.str_list(value) == expected


@pytest.mark.parametrize(
    ("value", "default", "expected"),
    [
        ("x", "", "x"),
        ("", "fallback", ""),  # an empty string IS a string — the narrowing is by type, not truthiness
        (None, "", ""),
        (None, "fallback", "fallback"),
        (7, "fallback", "fallback"),
        (["x"], "fallback", "fallback"),
    ],
)
def test_str_of(value, default, expected):
    assert Pyproject.str_of(value, default) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ([{"name": "a"}, {"name": "b"}], [{"name": "a"}, {"name": "b"}]),
        ([], []),
        # An array-of-tables with a scalar mixed in keeps only the tables — the same drop-don't-raise policy
        # as str_list, and the reason `[[tool.arch.forbidden]]` can be read without a schema pass first.
        ([{"name": "a"}, "junk", 3], [{"name": "a"}]),
        (None, []),
        ({"name": "a"}, []),  # ONE table is not an array of tables
    ],
)
def test_rows(value, expected):
    assert Pyproject.rows(value) == expected


def test_tool_section(tmp_path):
    """The named table, and the two absences that must both read as `{}` rather than raise.

    A missing file is the common case for a fresh consumer repo, and a missing section is the common case
    for an engine nobody configured — neither is an error, both must chain.
    """
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[tool.structure]\nfile_max = 500\n\n[tool.pytest.ini_options]\npython_files = ['*.py']\n")
    assert Pyproject.tool_section("structure", str(pp)) == {"file_max": 500}, "the named [tool.<section>] table"
    assert Pyproject.tool_section("absent", str(pp)) == {}, "a missing section is an empty dict"
    assert Pyproject.tool_section("structure", str(tmp_path / "none.toml")) == {}, "a missing file is an empty dict"
    # Nested tables come back whole, which is what lets `mirror.misconfigured` reach [tool.pytest.ini_options].
    assert Pyproject.tool_section("pytest", str(pp)) == {"ini_options": {"python_files": ["*.py"]}}


def test_structure_cfg(tmp_path):
    """Defaults, valid overrides, and the four ways a malformed override must RAISE rather than be dropped.

    The raise is the whole point of this method existing: a silently-ignored override leaves the gate on its
    default and the repo reads as passing at a threshold nobody set. That is a config's worst failure mode,
    because it is indistinguishable from a clean run.
    """
    pp = tmp_path / "pyproject.toml"

    assert Pyproject.structure_cfg(str(tmp_path / "none.toml")) == STRUCTURE_DEFAULTS, "no file is all defaults"

    # `off` rather than `mirror`: the DEFAULT is `mirror`, so overriding to it would assert nothing.
    pp.write_text("[tool.structure]\nfile_max = 500\ntest_layout = 'off'\n")
    cfg = Pyproject.structure_cfg(str(pp))
    assert cfg["file_max"] == 500 and cfg["test_layout"] == "off", "overrides land"
    assert cfg["demeter_max_depth"] == STRUCTURE_DEFAULTS["demeter_max_depth"], "unset keys keep their default"
    assert set(cfg) == set(STRUCTURE_DEFAULTS), "the key space is closed — an override never ADDS a key"

    # A float threshold accepts an int (`betweenness_max = 0`), because TOML spells 0.0 as 0 given the chance.
    pp.write_text("[tool.structure]\nbetweenness_max = 0\n")
    assert Pyproject.structure_cfg(str(pp))["betweenness_max"] == 0

    for body, _why in (
        ("bottlneck_degree = 20", "a TYPO is the silent-drop shape this exists to stop"),
        ("file_max = 'lots'", "a str where an int belongs"),
        ("test_layout = 3", "an int where a str belongs"),
        # bool is an int subclass, so `isinstance(True, int)` is True — without the explicit bool guard
        # `file_max = true` would be accepted and compared against as 1.
        ("file_max = true", "a bool is never a valid threshold despite subclassing int"),
    ):
        pp.write_text(f"[tool.structure]\n{body}\n")
        with pytest.raises(ValueError, match="malformed"):
            Pyproject.structure_cfg(str(pp))

    # Every bad key is reported in ONE raise, so a reader fixes their config once instead of N times.
    pp.write_text("[tool.structure]\nnope = 1\nfile_max = 'lots'\n")
    with pytest.raises(ValueError, match="malformed") as caught:
        Pyproject.structure_cfg(str(pp))
    assert "nope" in str(caught.value) and "file_max" in str(caught.value)
