"""The METHOD-level test mirror: every public method has a test that CALLS it and ASSERTS (bd c6b).

`graph`'s file-level mirror asks whether a module has a test FILE. That is the coarse OR of "is this module
tested", and a file containing one smoke test satisfies it for a module of twenty methods. This asks the
question people mean: for each public method `A.a`, the mirror file holds a `test_a` that calls it and then
asserts something about the returned value or the resulting state.

THE CONVENTION (the owner's design, bd mjo — recorded because the gate is only the enforcement of it):

    class A -> its module's mirror file; public method A.a -> `test_a` in that file
    `test_a` is a CONTAINER, not a case: doubles for setup, n parameter combinations x m assertions, so one
    test verifies n*m things about one method. Systematic and dense, and the name is the traceability link.
    A method that needs no assertion after the call is suspect — that is rule 3, and the ignore list is
    rule 4 for the residue.

WHY THE NAME IS ENFORCED and not merely the call. A positional check ("SOME test in the file calls it and
asserts") passes a file where one broad test happens to touch nine methods on its way somewhere else, and
it leaves the naming as an unenforced preference — which is the thing the epic rejects, because a
convention nothing enforces drifts. The name is also the cheap lookup: "what covers `A.a`?" is answered by
reading one function name, not by tracing call graphs. A test that calls the method and asserts but is
NAMED something else gets its own message — that is a RENAME, not a missing test, and saying so is the
difference between a gate that guides and a gate that scolds.

AMBIGUITY IS RESOLVED, NOT LEGISLATED. Two classes in one module can share a method name (`CallEdge.source_id`
and `CallSite.source_id` both exist in `calls.py`), and one `test_source_id` cannot mean both. So when a
name is unique in the module, `test_<method>` is expected; when it is shared, the qualified
`test_<Class>_<method>` is demanded — and the message names the exact function to write. The qualified form
is always accepted, so a repo that prefers it everywhere is never fought.

EXEMPT: `main()` (argparse plumbing exercised by the e2e) and `@property`. A property is READ as an
attribute, not called — a Call-node counter reports every property as untested, which produced 11 phantom
findings in the measurement that scoped this gate.

TWO REMEDIES, and the message names both, because "nothing tests this" has two correct fixes:

    reached by another module   -> a contract with no test. Write the test.
    called only in its own file -> public by naming accident. Add the underscore.

The second is not noise. It is a real defect of a different kind, and the gate finding it is the gate
working — 17 of devtools' own 76 public methods were this.

THE ASSERT HALF resolves DELEGATION transitively. A test that calls a local `_assert_wiring(...)` helper
which asserts, asserts. Without that, the gate over-fires on exactly the extraction that the complexity
limits (PLR0915) encourage — a naive detector produced 19 false positives out of 19 on the e2e suite for
this reason alone. `raise AssertionError` and `pytest.raises` count too; a "does not raise" test with no
observable state has two honest outcomes, give the collaborator state worth asserting on, or put the method
on the ignore list. There is deliberately no third mechanism.

THE IGNORE is per-method and RULE-NAMED, never blanket — `# devtools-ignore: test-mirror` on the method (or
one of its decorators), matching what the scaffold already ships for ast-grep. THE LIST IS THE SIGNAL: short
is fine, growing is the smell rule 3 points at.

PRECISE BUT INCOMPLETE, in the direction that costs a missing finding rather than a wrong one. A call is
credited by method NAME within the mirror file. Resolving the real call graph through test doubles is not
possible in principle — a fake is deliberately not the class under test — so a name match inside a file
whose declared subject IS that module is the honest reading, and a name collision there is itself a smell.

Run: `python -m devtools.mirror [pkgs...]` (report) | `--assert` (gate).
"""

from __future__ import annotations

import ast
import logging
from collections import Counter, defaultdict
from functools import cached_property
from pathlib import Path

from devtools._common import ENCODING
from devtools.cli import Cli
from devtools.layout import TestLayout
from devtools.purity import PropertyPurity
from devtools.pyproject import Pyproject
from devtools.trees import Trees

log = logging.getLogger("devtools.mirror")

# `main()` is argparse plumbing driven by the e2e, not a unit-testable seam — the one universal exemption.
EXEMPT = frozenset({"main"})
IGNORE = "devtools-ignore: test-mirror"
# What counts as asserting, beyond a bare `assert`: `raise AssertionError` is the same statement with the
# ruff S101 escape hatch on, and `pytest.raises` is the assertion when the outcome IS the exception.
ASSERT_CALLS = ("raises", "assert")

Function = ast.FunctionDef | ast.AsyncFunctionDef


class MethodMirror:
    """Public methods whose mirror test file holds no `test_<method>` that calls them and asserts."""

    def __init__(self, packages: list[str], trees: list[tuple[Path, ast.Module]] | None = None) -> None:
        self.packages = packages
        # Takes the TREES (bd 5cg): this reads method names and test bodies, and never resolves a name to a
        # class, so asking for a Resolver would make a standalone run build an index it never opens.
        self.trees = trees if trees is not None else list(Trees(packages).walk())

    @staticmethod
    def layout(pyproject: str = "pyproject.toml") -> TestLayout:
        """The mirror convention this repo declares — one home for it, shared with the file-level gate."""
        return TestLayout.of(str(Pyproject.structure_cfg(pyproject)["test_layout"]))

    @staticmethod
    def misconfigured(pyproject: str = "pyproject.toml") -> list[str]:
        """Config errors that would make this gate lie, reported as ERRORS rather than passing quietly.

        `test_layout = "bare"` needs `[tool.pytest.ini_options] python_files` to collect unprefixed files;
        pytest's default is `test_*.py`, so a bare tree without it is not collected AT ALL. That is the worst
        failure available here — an uncollected suite reports green, and this gate would agree with it,
        because every method's mirror file exists and is full of tests that never run.

        Same reasoning as `contracts.malformed`: something that cannot fire looks exactly like something
        clean, so the config error has to be louder than the finding it suppresses.
        """
        cfg = Pyproject.structure_cfg(pyproject)
        if str(cfg["test_layout"]) != "bare":
            return []
        ini = Pyproject.table(Pyproject.tool_section("pytest", pyproject).get("ini_options"))
        if any(not p.startswith("test") for p in Pyproject.str_list(ini.get("python_files"))):
            return []
        return [
            'test_layout = "bare" but [tool.pytest.ini_options] python_files does not collect unprefixed '
            'files — the suite is not collected at all. Set python_files = ["*.py"]'
        ]

    @staticmethod
    def is_public(fn: Function) -> bool:
        """A method this rule applies to: not private, not `main`, not a `@property`.

        A property is read as an ATTRIBUTE. Demanding a CALL to one is demanding something the language does
        not let a caller write, so it is exempt by kind rather than by convention.
        """
        return not fn.name.startswith("_") and fn.name not in EXEMPT and not PropertyPurity.is_property(fn)

    @staticmethod
    def ignored(fn: Function, lines: list[str]) -> bool:
        """Is this method excused by a rule-named `# devtools-ignore: test-mirror`?

        Read from the `def` line or any DECORATOR line, so the marker sits where a reader looking at the
        method will see it. Rule-named rather than blanket, so silencing this gate never silences another.
        """
        first = min([fn.lineno, *(d.lineno for d in fn.decorator_list)])
        return any(IGNORE in lines[i - 1] for i in range(first, fn.lineno + 1) if 0 < i <= len(lines))

    @staticmethod
    def overrides(cls: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> set[str]:
        """Method names this class inherits from an ancestor DEFINED IN THE SAME MODULE.

        An override is not a second obligation. `_Mirror.mirror_of` and `_Off.mirror_of` are one polymorphic
        contract declared by `TestLayout.mirror_of`, and the base's `test_mirror_of` — driven over every
        strategy, which is what a dense container test is FOR — covers all of them. Counting them separately
        did two wrong things at once: it demanded a test per strategy, and it made the name look ambiguous,
        so the gate asked for `test___mirror_mirror_of`.
        """
        seen: set[str] = set()
        queue = [base.id for base in cls.bases if isinstance(base, ast.Name)]
        while queue:
            ancestor = classes.get(queue.pop())
            if ancestor is None or ancestor.name in seen:
                continue
            seen.add(ancestor.name)
            queue += [base.id for base in ancestor.bases if isinstance(base, ast.Name)]
        return {
            fn.name
            for name in seen
            for fn in classes[name].body
            if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
        }

    def methods(self) -> dict[Path, list[tuple[str, Function]]]:
        """{module: [(class, method)]} — every public method the rule covers, by the module that owns it.

        A PRIVATE class is skipped whole. `_Mirror.mirror_of` is not a public seam however public the method
        name looks — the class is the API boundary, and nothing outside the module can reach it.
        """
        covered = set(TestLayout.testable(self.packages))
        out: dict[Path, list[tuple[str, Function]]] = {}
        for path, tree in self.trees:
            if path not in covered:
                continue
            classes = {c.name: c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
            out[path] = [
                (cls.name, fn)
                for cls in classes.values()
                if not cls.name.startswith("_")
                for fn in cls.body
                if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)
                and self.is_public(fn)
                and fn.name not in self.overrides(cls, classes)
            ]
        return out

    @cached_property
    def callers(self) -> dict[str, set[Path]]:
        """{method name: files that CALL it} — the input to picking which remedy a finding names.

        Coarse by name and deliberately so: this decides the WORDING of a message, not whether it fires, so
        over-crediting a method as "reached elsewhere" costs a slightly wrong suggestion, not a wrong verdict.

        Cached because it is a full walk of the tree and every finding asks for it — computing it per finding
        made the gate quadratic in the thing it is reporting.
        """
        out: dict[str, set[Path]] = defaultdict(set)
        for path, tree in self.trees:
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    out[node.func.attr].add(path)
        return out

    @staticmethod
    def functions(tree: ast.Module) -> dict[str, Function]:
        """{name: function} for every function in a test module — tests AND the helpers they delegate to."""
        return {fn.name: fn for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef)}

    @staticmethod
    def called_names(fn: Function) -> set[str]:
        """Every name called in this body, however the callee is spelled (`x.y.a()`, `a()`)."""
        return {
            name
            for node in ast.walk(fn)
            if isinstance(node, ast.Call) and (name := MethodMirror.name_of(node.func))
        }

    @staticmethod
    def name_of(func: ast.expr) -> str:
        """The trailing name of a callee — `a` for both `x.y.a` and `a`, empty for anything else."""
        if isinstance(func, ast.Attribute):
            return func.attr
        return func.id if isinstance(func, ast.Name) else ""

    @staticmethod
    def snake(name: str) -> str:
        """`CallEdge` -> `call_edge` — the class half of a qualified test name, in test-function casing."""
        return "".join(f"_{c.lower()}" if c.isupper() and i else c.lower() for i, c in enumerate(name))

    @staticmethod
    def reachable(start: Function, helpers: dict[str, Function]) -> list[Function]:
        """`start` plus every helper it reaches, transitively.

        This is the whole delegation fix, and it is one traversal rather than two because the CALL check and
        the ASSERT check need the same reachable set: a test that calls `_hits()` both calls what `_hits`
        calls and asserts what `_hits` asserts.
        """
        seen: dict[str, Function] = {start.name: start}
        queue = [start]
        while queue:
            for name in MethodMirror.called_names(queue.pop()):
                if name in helpers and name not in seen:
                    seen[name] = helpers[name]
                    queue.append(helpers[name])
        return list(seen.values())

    @staticmethod
    def asserts(bodies: list[Function]) -> bool:
        """Does anything in this reachable set assert — `assert`, `raise AssertionError`, `pytest.raises`?"""
        for fn in bodies:
            for node in ast.walk(fn):
                if isinstance(node, ast.Assert):
                    return True
                if isinstance(node, ast.Raise) and "AssertionError" in ast.dump(node):
                    return True
                if isinstance(node, ast.Call) and MethodMirror.name_of(node.func).startswith(ASSERT_CALLS):
                    return True
        return False

    @staticmethod
    def expected(cls: str, method: str, shared: bool) -> list[str]:
        """The test function name(s) that satisfy this method — qualified when the bare name is ambiguous.

        The qualified form is ALWAYS accepted, so a repo that prefers `test_<Class>_<method>` everywhere is
        never fought by a gate that only knows one spelling.
        """
        qualified = f"test_{MethodMirror.snake(cls)}_{method}"
        return [qualified] if shared else [f"test_{method}", qualified]

    def _finding(self, path: Path, cls: str, fn: Function, mirror: Path, names: list[str], covers: bool) -> str:
        """The message for one uncovered method — a RENAME when a test already covers it under another name,
        otherwise the missing test plus the remedy its call sites point at."""
        where = f"{path.as_posix()}:{fn.lineno}: `{cls}.{fn.name}`"
        if covers:
            return f"{where} — a test in {mirror.as_posix()} calls it and asserts, but is not named `{names[0]}`; rename it"
        reached = self.callers[fn.name] - {path}
        remedy = (
            f"reached by {len(reached)} other module(s) — a contract with no test; write `{names[0]}`"
            if reached
            else "called only inside its own file — public by naming accident; add the underscore, or write "
            f"`{names[0]}`"
        )
        return f"{where} — no `{names[0]}` in {mirror.as_posix()} that calls it and asserts. It is {remedy}"

    def violations(self) -> list[str]:
        """Every public method whose mirror file holds no correctly-named test that calls it and asserts."""
        convention = self.layout()
        out = []
        for path, members in self.methods().items():
            mirror = convention.mirror_of(path)
            # A layout naming no single file (`flat`, `off`) leaves this gate nowhere to look, and a module
            # with NO mirror file at all is already the file-level gate's finding — reporting every one of
            # its methods here would bury that one line under twenty.
            if mirror is None or not mirror.exists():
                continue
            lines = path.read_text(encoding=ENCODING).splitlines()
            out += self._violations_in(path, members, mirror, lines)
        return out

    def _violations_in(
        self, path: Path, members: list[tuple[str, Function]], mirror: Path, lines: list[str]
    ) -> list[str]:
        """The uncovered methods of ONE module, against its mirror file."""
        helpers = self.functions(ast.parse(mirror.read_text(encoding=ENCODING)))
        shared = {m for m, n in Counter(fn.name for _cls, fn in members).items() if n > 1}
        covered, asserting = self._coverage(helpers)
        out = []
        for cls, fn in members:
            if self.ignored(fn, lines):
                continue
            names = self.expected(cls, fn.name, fn.name in shared)
            if any(name in asserting and fn.name in covered.get(name, set()) for name in names):
                continue
            elsewhere = any(fn.name in covered.get(name, set()) for name in asserting)
            out.append(self._finding(path, cls, fn, mirror, names, elsewhere))
        return out

    def _coverage(self, helpers: dict[str, Function]) -> tuple[dict[str, set[str]], set[str]]:
        """({test name: names it calls transitively}, {test names that assert}) for one mirror file."""
        calls, asserting = {}, set()
        for name, fn in helpers.items():
            if not name.startswith("test"):
                continue
            bodies = self.reachable(fn, helpers)
            calls[name] = {called for body in bodies for called in self.called_names(body)}
            if self.asserts(bodies):
                asserting.add(name)
        return calls, asserting

    def report(self) -> str:
        """The findings as one text block — the explorer view, paired with run_assert's gate view."""
        found = self.violations()
        return "\n".join([f"untested public methods: {len(found)}", *found])

    def run_assert(self) -> int:
        """The gate: fail on a config error FIRST (it would otherwise let an uncollected suite read as
        clean), then on every public method without its named, asserting test."""
        if broken := self.misconfigured():
            log.error("method test-mirror — MISCONFIGURED (%d):\n  %s", len(broken), "\n  ".join(broken))
            return 1
        found = self.violations()
        if found:
            log.error("method test-mirror — BLOCKING (%d):\n  %s", len(found), "\n  ".join(found))
            return 1
        log.info("method test-mirror: clean (every public method has a named test that calls and asserts)")
        return 0


def main():
    Cli(
        MethodMirror,
        "Method-level test mirror — every public method has a named test that calls it and asserts.",
        gate="exit 1 on a public method with no `test_<method>` that calls it and asserts",
    ).run()


if __name__ == "__main__":
    main()
