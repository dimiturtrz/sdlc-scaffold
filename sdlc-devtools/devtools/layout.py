"""Where a module's unit test lives — the mirror convention, as ONE strategy both mirror gates resolve
through (bd 1a8).

Two gates now ask the same question about the same path. `graph.unmirrored` asks "does a test file EXIST
for this module"; `mirror.MethodMirror` asks "does a test IN THAT FILE call this method and assert". If
each spelled the path itself, the convention would have two homes — and worse, the two gates could
disagree, which reads as a clean tree from one and a broken one from the other.

THE CONVENTION IS CONFIG, not imposed architecture. `[tool.structure] test_layout`:

    bare    tests/unit/<pkg>/<path>/<name>.py        strict path mirror, one home per module — the DEFAULT
    mirror  tests/unit/<pkg>/<path>/test_<name>.py   the same mirror, prefixed
    flat    a test_<name>.py ANYWHERE under tests/   lenient; a flat repo passes without restructuring
    off     nothing is demanded

`mirror` and `bare` are the SAME strategy with a different prefix, not two — the mirror is the path rule,
the prefix is a spelling. Splitting them into two classes would duplicate the path arithmetic and invite
them to drift.

`bare` COSTS A PYTEST SETTING and the gate says so rather than letting it fail silently: pytest collects
`test_*.py` by default, so a bare tree needs `python_files = ["*.py"]` under `[tool.pytest.ini_options]`.
Without it the suite is not collected at all — and an uncollected suite is greener than a red one, which is
the worst failure mode available here.

WHY BARE IS WORTH THE SETTING: the mirror is a path mirror, and `test_` breaks it. `<pkg>/store.py` is
covered by `tests/unit/<pkg>/store.py` under `bare` — the same name, so the mirror is visible in the path
rather than reconstructed by the reader. The prefix is a discovery mechanism wearing a convention's
clothes.

`bare` IS THE DEFAULT, and the reasoning that first held it back was incoherent. The argument was that
switching costs an existing consumer a red gate on every module at once — true, but the METHOD-level mirror
already goes red on all three consumers the moment they update, because they have untested public methods.
Holding the prefix back spared them the rename script inside a change that hands them the conversion. The
prefix is a trivial part of adopting the convention, so the only real question is which spelling a consumer
converts TO — and converting to the one the scaffold itself rejected would leave the two permanently
different. One conversion, one convention.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import override

from devtools.omit import Omit

DEFAULT_TEST_ROOT = "tests/unit"

# Package plumbing — exempt from the test-mirror rule (and from graph's line floor, which reads it from
# here rather than keeping a second copy that could disagree about what "not real code" means).
STRUCTURAL = ("__init__.py", "__main__.py")


class TestLayout:
    """Where a module's unit test lives, per `[tool.structure] test_layout`.

    Three questions, because the gates need different parts of one answer: `testable` says WHICH modules the
    rule covers at all, `mirror_of` names the ONE file that must hold a module's tests (None when the layout
    names no single file), and `missing` is the file-level gate's finding when nothing covers the module.
    """

    def __init__(self, test_root: str = DEFAULT_TEST_ROOT) -> None:
        self.test_root = Path(test_root)

    @staticmethod
    def testable(packages: list[str]) -> list[Path]:
        """The LOGIC modules the test rule applies to, sorted.

        `__init__`/`__main__` are package plumbing; coverage-OMITTED shells (runners / adapters / GPU /
        download / viz glue, read from `[tool.coverage] omit`) are exempt too — a non-unit-testable shell is
        not forced to carry a stub test.

        It lives HERE, not on either gate, because the file-level and method-level mirrors must agree about
        what is even in scope. Two gates disagreeing on the population would be a worse defect than either
        gate being wrong about a module: the tree would read as covered from one and uncovered from the
        other, with no way to tell which is lying.
        """
        omit = Omit.coverage_omit()
        return [
            f
            for pkg in packages
            for f in sorted(Path(pkg).rglob("*.py"))
            if f.name not in STRUCTURAL and not Omit.matches_omit(f.as_posix(), omit)
        ]

    @staticmethod
    def names() -> list[str]:
        """The valid `test_layout` values, sorted — the public view of the dispatch table."""
        return sorted(_LAYOUTS)

    @staticmethod
    def of(name: str, test_root: str = DEFAULT_TEST_ROOT) -> TestLayout:
        """The layout a `test_layout` value names.

        An unknown value is a HARD error, not a fallback to the default. A typo'd layout that quietly
        degraded to `mirror` would gate a bare tree against the prefixed convention and report every module
        as untested — a config error must not be able to masquerade as a finding.
        """
        build = _LAYOUTS.get(name)
        if build is None:
            raise SystemExit(f"unknown test_layout {name!r} (known: {', '.join(TestLayout.names())})")
        return build(test_root)

    def mirror_of(self, module: Path) -> Path | None:
        """The one file that must hold this module's unit tests, or None when the layout names no single
        file — `flat` accepts any path and `off` demands nothing, and in both cases the METHOD-level gate
        has nowhere to look and stands down rather than guessing."""
        raise NotImplementedError

    def missing(self, module: Path) -> str | None:
        """The file-level finding for a module nothing covers, or None when it is covered."""
        raise NotImplementedError


class _Mirror(TestLayout):
    """The strict path mirror: `<pkg>/<path>/foo.py` is covered iff `<test_root>/<pkg>/<path>/<prefix>foo.py`
    exists. A same-purpose test under a different name or path does not count — one home per module."""

    def __init__(self, test_root: str = DEFAULT_TEST_ROOT, prefix: str = "test_") -> None:
        super().__init__(test_root)
        self.prefix = prefix

    @override
    def mirror_of(self, module: Path) -> Path:
        return self.test_root / module.parent / f"{self.prefix}{module.name}"

    @override
    def missing(self, module: Path) -> str | None:
        mirror = self.mirror_of(module)
        return None if mirror.exists() else f"{module.as_posix()} — no mirrored {mirror.as_posix()}"


class _Flat(TestLayout):
    """Lenient: a `test_<name>.py` exists ANYWHERE under `tests/`. Lets a flat-layout repo satisfy the
    file-level gate without restructuring its test tree — at the price of the method-level gate, which
    needs a known file to read and therefore does not run here."""

    @cached_property
    def _names(self) -> set[str]:
        return {p.name for p in Path("tests").rglob("test_*.py")}

    @override
    def mirror_of(self, module: Path) -> Path | None:
        return None

    @override
    def missing(self, module: Path) -> str | None:
        if f"test_{module.name}" in self._names:
            return None
        return f"{module.as_posix()} — no test_{module.name} anywhere under tests/"


class _Off(TestLayout):
    """No test-existence gate. The null object, so "the gate is off" costs no branch at either call site."""

    @override
    def mirror_of(self, module: Path) -> Path | None:
        return None

    @override
    def missing(self, module: Path) -> str | None:
        return None


# Declaration-only dispatch: a value -> the layout it names. `mirror` and `bare` differ ONLY in the prefix,
# which is the whole argument for one strategy rather than two.
_LAYOUTS: dict[str, Callable[[str], TestLayout]] = {
    "mirror": lambda test_root: _Mirror(test_root, "test_"),
    "bare": lambda test_root: _Mirror(test_root, ""),
    "flat": _Flat,
    "off": _Off,
}
