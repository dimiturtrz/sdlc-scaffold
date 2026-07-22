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

METHODS ARE CALLED, PROPERTIES ARE READ, and both are public API. A property was exempt at first because a
Call-node counter reports every one of them as untested — but that was a fact about the DETECTOR, not about
properties, and exempting the whole family to work around it also left an unreachable demand in the gate: a
`@x.setter` is not a pure read, so it was never exempt, and the gate asked for a `test_x` that CALLS `x()`.
Nothing can satisfy that. So the member kind picks the SYNTAX the matching site looks for — a call for a
method, an attribute touch for a property — and the message says "calls" or "reads" to match.

EXEMPT: `main()` (argparse plumbing exercised by the e2e), private methods, declarations (below), and a
method a same-module base already declares. Every class in the module is in scope — the rule is about the
METHOD, and where it happens to be defined is not a second question.

TWO REMEDIES, and the message names both, because "nothing tests this" has two correct fixes:

    reached by another module   -> a contract with no test. Write the test.
    called only in its own file -> public by naming accident. Add the underscore.

The second is not noise. It is a real defect of a different kind, and the gate finding it is the gate
working — 15 of the 119 findings on this package's first run were this, and every one of them turned out to
be a method that was genuinely worth testing rather than hiding, so all 15 got tests instead.

THE ASSERT HALF resolves DELEGATION transitively. A test that calls a local `_assert_wiring(...)` helper
which asserts, asserts. Without that, the gate over-fires on exactly the extraction that the complexity
limits (PLR0915) encourage — a naive detector produced 19 false positives out of 19 on the e2e suite for
this reason alone. `raise AssertionError` and `pytest.raises` count too; a "does not raise" test with no
observable state has two honest outcomes, give the collaborator state worth asserting on, or put the method
on the ignore list. There is deliberately no third mechanism.

THE IGNORE is per-method and RULE-NAMED, never blanket — `# devtools-ignore: test-mirror` on the method (or
one of its decorators), matching what the scaffold already ships for ast-grep. THE LIST IS THE SIGNAL: short
is fine, growing is the smell rule 3 points at.

PRECISE BUT INCOMPLETE, in the direction that costs a missing finding rather than a wrong one. A member is
credited by NAME within the mirror file. Resolving the real call graph through test doubles is not possible
in principle — a fake is deliberately not the class under test — so a name match inside a file whose
declared subject IS that module is the honest reading, and a name collision there is itself a smell.
"""

from __future__ import annotations

import ast
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from devtools.plumbing._common import ENCODING
from devtools.plumbing.cli import Cli
from devtools.plumbing.layout import TestLayout
from devtools.plumbing.pyproject import Pyproject
from devtools.plumbing.trees import Trees

log = logging.getLogger("devtools.hygiene.mirror")

# `main()` is argparse plumbing driven by the e2e, not a unit-testable seam — the one universal exemption.
EXEMPT = frozenset({"main"})
IGNORE = "devtools-ignore: test-mirror"
# What counts as asserting, beyond a bare `assert`: `raise AssertionError` is the same statement with the
# ruff S101 escape hatch on, and `pytest.raises` is the assertion when the outcome IS the exception.
ASSERT_CALLS = ("raises", "assert")
# The property FAMILY. All three are exercised by attribute access, so they share one rule here even though
# `purity` deliberately splits them (there, a setter is the declared exception; here it is the same shape).
PROPERTIES = frozenset({"property", "cached_property", "setter", "deleter"})

Function = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass
class Coverage:
    """What each test in one mirror file reaches: {test name: names it CALLS} and {test name: names it
    ACCESSES}, both resolved transitively through the helpers the test delegates to.

    Two maps rather than one union, because the member kinds are reached by different syntax and the check
    must demand the RIGHT one. A union read as harmless — the test still has to be named `test_<member>` and
    assert — but it weakened the method rule to "mentions it", and a gate whose message says "calls it and
    asserts" has to mean it.
    """

    called: dict[str, set[str]]
    accessed: dict[str, set[str]]


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

        The mirror names a test file after the module it covers, and pytest collects `test_*.py` by default —
        so without `[tool.pytest.ini_options] python_files` the suite is not collected AT ALL. That is the
        worst failure available here: an uncollected suite reports green, and this gate would agree with it,
        because every mirror file exists and is full of tests that never run.

        UNCONDITIONAL while the gate is on. It used to fire only for the unprefixed layout, back when a
        prefixed one existed beside it; with one mirror meaning, the setting is simply part of the layout and
        checking it sometimes was the leftover of a distinction that is gone.

        Same reasoning as `contracts.malformed`: something that cannot fire looks exactly like something
        clean, so the config error has to be louder than the finding it suppresses.
        """
        if str(Pyproject.structure_cfg(pyproject)["test_layout"]) == "off":
            return []
        ini = Pyproject.table(Pyproject.tool_section("pytest", pyproject).get("ini_options"))
        if any(not p.startswith("test") for p in Pyproject.str_list(ini.get("python_files"))):
            return []
        return [
            "the mirror names a test file after its module, but [tool.pytest.ini_options] python_files does "
            'not collect those — the suite is not collected at all. Set python_files = ["*.py"]'
        ]

    @staticmethod
    def is_declaration(fn: Function) -> bool:
        """Is this a method SIGNATURE with no behaviour — a `Protocol` member or an abstract method?

        Its body is a docstring and/or `...` / `pass` / `raise NotImplementedError`. There is nothing to
        call and nothing that could be asserted about the result, so demanding a test would be demanding a
        test of a no-op. The IMPLEMENTATIONS are covered by their own mirrors, which is where the behaviour
        actually is.

        Detected by BODY rather than by base class or decorator, because the three spellings that produce a
        declaration — `Protocol`, `ABC` + `@abstractmethod`, and a plain base raising NotImplementedError —
        agree on exactly this and on nothing else.
        """
        body = [node for node in fn.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
        return all(
            isinstance(node, ast.Pass)
            or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
            or (isinstance(node, ast.Raise) and "NotImplementedError" in ast.dump(node))
            for node in body
        )

    @staticmethod
    def is_property(fn: Function) -> bool:
        """Is this a member of the property FAMILY — getter, setter or deleter?

        Broader than `PropertyPurity.is_property`, which asks "is this a pure read" and therefore excludes
        setters on purpose. Here the question is only "how is this member EXERCISED", and all three are
        exercised the same way: by attribute access. So all three belong on the same side of the split.
        """
        names = {
            d.attr if isinstance(d, ast.Attribute) else d.id
            for d in fn.decorator_list
            if isinstance(d, ast.Attribute | ast.Name)
        }
        return bool(names & PROPERTIES)

    @staticmethod
    def is_public(fn: Function) -> bool:
        """A method this rule applies to: not a private METHOD, not `main`, not a declaration.

        PROPERTIES ARE IN. They were exempt, on the grounds that a Call-node counter reports every property
        as untested — but that was a statement about the DETECTOR, not about properties. A property is
        public API; it is simply exercised by attribute access rather than by a call, which is `accessed`
        rather than `called` at the matching site. Exempting it also left an unreachable demand in the gate:
        a `@x.setter` is not a pure read, so it was never exempt, and the gate asked for a `test_x` that
        CALLS `x()` — which nothing can satisfy.

        The question is asked of the METHOD alone. Its class is not a second filter: a strategy whose methods
        need no test of their own is already answered by `overrides`, which says so for a reason that is
        about the code rather than about how anyone spelled a name.
        """
        return not fn.name.startswith("_") and fn.name not in EXEMPT and not MethodMirror.is_declaration(fn)

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

        Every class in the module, without qualification. The class contributes the NAME a finding is
        reported under and nothing else; whether a method needs a test is decided by the method.
        """
        covered = set(TestLayout.testable(self.packages))
        out: dict[Path, list[tuple[str, Function]]] = {}
        for path, tree in self.trees:
            if path not in covered:
                continue
            classes = {c.name: c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)}
            out[path] = [m for cls in classes.values() for m in self._members(cls, classes)]
        return out

    def _members(self, cls: ast.ClassDef, classes: dict[str, ast.ClassDef]) -> list[tuple[str, Function]]:
        """The members of ONE class the rule covers — at most one entry per NAME.

        A property's getter, setter and deleter are three `def`s implementing ONE member. Listed separately,
        `A.size` looked like a name shared by two members, so the ambiguity rule demanded the qualified
        `test_a_size` to disambiguate a collision that does not exist. Within a class a name means exactly
        one thing, so keeping the first is not a heuristic — it is the member.
        """
        inherited = self.overrides(cls, classes)
        members: dict[str, Function] = {}
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if not self.is_public(fn) or fn.name in inherited or fn.name in members:
                continue
            members[fn.name] = fn
        return [(cls.name, fn) for fn in members.values()]

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
            name for node in ast.walk(fn) if isinstance(node, ast.Call) and (name := MethodMirror.name_of(node.func))
        }

    @staticmethod
    def name_of(func: ast.expr) -> str:
        """The trailing name of a callee — `a` for both `x.y.a` and `a`, empty for anything else."""
        if isinstance(func, ast.Attribute):
            return func.attr
        return func.id if isinstance(func, ast.Name) else ""

    @staticmethod
    def snake(name: str) -> str:
        """`CallEdge` -> `call_edge` — the class half of a qualified test name, in test-function casing.

        Leading underscores are stripped, because a doubled underscore inside a generated name is not
        something anyone would write by hand: `_Mirror` gives `test_mirror_of`, not `test__mirror_mirror_of`.
        Purely how the name READS — it changes nothing about which methods are in scope.
        """
        bare = name.lstrip("_")
        return "".join(f"_{c.lower()}" if c.isupper() and i else c.lower() for i, c in enumerate(bare))

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
    def expected(cls: str, method: str, *, shared: bool) -> list[str]:
        """The test function name(s) that satisfy this method — qualified when the bare name is ambiguous.

        The qualified form is ALWAYS accepted, so a repo that prefers `test_<Class>_<method>` everywhere is
        never fought by a gate that only knows one spelling.
        """
        qualified = f"test_{MethodMirror.snake(cls)}_{method}"
        return [qualified] if shared else [f"test_{method}", qualified]

    def _finding(
        self, path: Path, member: tuple[str, Function], mirror: Path, names: list[str], *, covers: bool
    ) -> str:
        """The message for one uncovered method — a RENAME when a test already covers it under another name,
        otherwise the missing test plus the remedy its call sites point at."""
        cls, fn = member
        # A property is READ, a method is CALLED. Saying "calls it" about a property would describe
        # something the language does not let anyone write, which is how a message stops being followable.
        verb, past = ("reads", "read") if self.is_property(fn) else ("calls", "called")
        where = f"{path.as_posix()}:{fn.lineno}: `{cls}.{fn.name}`"
        if covers:
            return (
                f"{where} — a test in {mirror.as_posix()} {verb} it and asserts, but is not named "
                f"`{names[0]}`; rename it"
            )
        reached = self.callers[fn.name] - {path}
        remedy = (
            f"reached by {len(reached)} other module(s) — a contract with no test; write `{names[0]}`"
            if reached
            else f"{past} only inside its own file — public by naming accident; add the underscore, or "
            f"write `{names[0]}`"
        )
        return f"{where} — no `{names[0]}` in {mirror.as_posix()} that {verb} it and asserts. It is {remedy}"

    def violations(self) -> list[str]:
        """Every public method whose mirror file holds no correctly-named test that calls it and asserts."""
        convention = self.layout()
        out: list[str] = []
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
        coverage, asserting = self._coverage(helpers)
        out = []
        for cls, fn in members:
            if self.ignored(fn, lines):
                continue
            names = self.expected(cls, fn.name, shared=fn.name in shared)
            # The member KIND picks the syntax: a method must be CALLED, a property must be ACCESSED.
            reached = coverage.accessed if self.is_property(fn) else coverage.called
            if any(name in asserting and fn.name in reached.get(name, set()) for name in names):
                continue
            elsewhere = any(fn.name in reached.get(name, set()) for name in asserting)
            out.append(self._finding(path, (cls, fn), mirror, names, covers=elsewhere))
        return out

    @staticmethod
    def accessed_names(fn: Function) -> set[str]:
        """Every attribute name TOUCHED in this body — `obj.total`, read, written or deleted.

        How a property is exercised. `ast.Attribute` covers all three contexts (Load / Store / Del), which
        is why a setter and a getter need no separate treatment: `s.total`, `s.total = 1` and `del s.total`
        all reach the member, and all three are what a `test_total` would legitimately do.
        """
        return {node.attr for node in ast.walk(fn) if isinstance(node, ast.Attribute)}

    def _coverage(self, helpers: dict[str, Function]) -> tuple[Coverage, set[str]]:
        """(what each test exercises transitively, the tests that assert) for one mirror file.

        CALLED and ACCESSED are kept APART rather than unioned. Unioning them was simpler and read as safe —
        the test still has to be named `test_<member>` and assert — but it quietly weakened the method rule
        to "mentions it", and a gate that says "calls it and asserts" has to mean it. Measured at the time of
        the split: 0 methods in this package were credited by mention alone, so precision here is free.
        """
        coverage = Coverage({}, {})
        asserting: set[str] = set()
        for name, fn in helpers.items():
            if not name.startswith("test"):
                continue
            bodies = self.reachable(fn, helpers)
            coverage.called[name] = {n for body in bodies for n in self.called_names(body)}
            coverage.accessed[name] = {n for body in bodies for n in self.accessed_names(body)}
            if self.asserts(bodies):
                asserting.add(name)
        return coverage, asserting

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
