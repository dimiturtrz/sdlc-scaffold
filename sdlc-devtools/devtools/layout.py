"""Where a module's unit test lives — the mirror convention, as ONE strategy both mirror gates resolve
through (bd 1a8).

Two gates ask the same question about the same path. `graph.unmirrored` asks "does a test file EXIST for
this module"; `mirror.MethodMirror` asks "does a test IN THAT FILE reach this member and assert". If each
spelled the path itself, the convention would have two homes — and worse, the two gates could disagree,
which reads as a clean tree from one and a broken one from the other.

TWO VALUES, `[tool.structure] test_layout`:

    mirror  tests/unit/<pkg>/<path>/<name>.py   the module's test carries the module's name — the DEFAULT
    off     nothing is demanded

THE MIRROR IS A PATH MIRROR, so the path has to mirror. `<pkg>/store.py` is covered by
`tests/unit/<pkg>/store.py`: the same name, so what a test file covers is visible in its path rather than
reconstructed by the reader. `test_` is how PYTEST FINDS FILES, not a convention — a prefixed variant was
shipped briefly beside this one and it was the same rule with a discovery mechanism baked into it, which is
a fork, not a choice.

IT COSTS A PYTEST SETTING, and the gate says so rather than letting it fail silently: pytest collects
`test_*.py` by default, so this layout needs `python_files = ["*.py"]` under `[tool.pytest.ini_options]`.
Without it the suite is not collected at all — and an uncollected suite reports green while running zero
tests, which is the worst failure mode available here. `mirror.misconfigured` fails the gate on that config
rather than passing.

THERE IS NO LENIENT VALUE. A `flat` mode once accepted a `test_<name>.py` anywhere under `tests/`, so a repo
could satisfy the gate without adopting the convention. That is not a threshold, it is a DIFFERENT
PREDICATE — the o70 union law in docs/RULE_INVENTORY.md says a universal rule never varies per repo, and
only thresholds and vocabulary move. It was also quietly worthless: with no single file to read, the
method-level gate stood down, so a repo on `flat` got the APPEARANCE of the mirror convention.

`off` is categorically different and stays. It is the gate not running, which is ordinary ratchet posture —
not the rule meaning something else here.
"""

from __future__ import annotations

from collections.abc import Callable
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
    rule covers at all, `mirror_of` names the ONE file that must hold a module's tests (None when nothing is
    demanded), and `missing` is the file-level gate's finding when nothing covers the module.
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
        degraded to the mirror would gate a tree it was never meant to gate; one that degraded to `off`
        would turn two gates off and report clean. A config error must not be able to look like an answer.
        """
        build = _LAYOUTS.get(name)
        if build is None:
            raise SystemExit(f"unknown test_layout {name!r} (known: {', '.join(TestLayout.names())})")
        return build(test_root)

    def mirror_of(self, module: Path) -> Path | None:
        """The one file that must hold this module's unit tests, or None when nothing is demanded — and
        `off` is exactly when the METHOD-level gate has nowhere to look and stands down rather than
        guessing."""
        raise NotImplementedError

    def missing(self, module: Path) -> str | None:
        """The file-level finding for a module nothing covers, or None when it is covered."""
        raise NotImplementedError


class _Mirror(TestLayout):
    """The strict path mirror: `<pkg>/<path>/foo.py` is covered iff `<test_root>/<pkg>/<path>/foo.py`
    exists. A same-purpose test under a different name or path does not count — one home per module."""

    @override
    def mirror_of(self, module: Path) -> Path:
        return self.test_root / module.parent / module.name

    @override
    def missing(self, module: Path) -> str | None:
        mirror = self.mirror_of(module)
        return None if mirror.exists() else f"{module.as_posix()} — no mirrored {mirror.as_posix()}"


class _Off(TestLayout):
    """No test-existence gate. The null object, so "the gate is off" costs no branch at either call site."""

    @override
    def mirror_of(self, module: Path) -> Path | None:
        return None

    @override
    def missing(self, module: Path) -> str | None:
        return None


# Declaration-only dispatch: a value -> the layout it names.
_LAYOUTS: dict[str, Callable[[str], TestLayout]] = {"mirror": _Mirror, "off": _Off}
