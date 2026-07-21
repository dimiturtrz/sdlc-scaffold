"""Unit tests for devtools/pyproject.py — the shared `[tool.<section>]` reader."""

from devtools.pyproject import Pyproject


def test_pyproject_tool_section_reads_and_defaults(tmp_path):
    pp = tmp_path / "pyproject.toml"
    pp.write_text("[tool.structure]\nfile_max = 500\n")
    assert Pyproject.tool_section("structure", str(pp)) == {"file_max": 500}, "the named [tool.<section>] table"
    assert Pyproject.tool_section("absent", str(pp)) == {}, "a missing section is an empty dict"
    assert Pyproject.tool_section("structure", str(tmp_path / "none.toml")) == {}, "a missing file is an empty dict"
