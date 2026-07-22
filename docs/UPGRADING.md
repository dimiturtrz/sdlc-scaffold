# Upgrading — adopter migration notes

`copier update` fetches the newest scaffold tag and re-renders the gate config. Most updates are
transparent. When a gate **graduates** (advisory → enforced) a repo can suddenly go red on pre-existing code
that was always non-compliant — that is the ratchet working, not a regression. This file is the recipe per
such change, so an adopter fixes the code the intended way instead of carving the gate back out (which
defeats the update for everyone downstream).

Entries are keyed by the version that introduced the change, newest first.

---

## v1.25.0 — the analyzers move into domain folders; every `python -m devtools.<gate>` path gains its folder

**What you'll see.** After `copier update` past v1.25.0, every devtools gate is invoked at a folder-qualified
module path. The engines' behaviour, flags and output are unchanged — only the dotted path moved, and `--help`
prints the new one (the invocation header resolves the subpackage segment).

| folder | was → now |
|---|---|
| `graph/` | `devtools.graph` → `devtools.graph.fitness` · `devtools.archmap` → `devtools.graph.archmap` · `devtools.arrows\|calls\|classes` → `devtools.graph.arrows\|calls\|classes` |
| `coupling/` | `devtools.{demeter,envy,composition,contracts,purity}` → `devtools.coupling.{…}` |
| `cohesion/` | `devtools.{lcom,data_clumps,state_candidates,complexity}` → `devtools.cohesion.{…}` |
| `hygiene/` | `devtools.{magic_literals,small,mirror}` → `devtools.hygiene.{…}` |
| `tools/` | `devtools.config` → `devtools.tools.config` · `devtools.analytics` → `devtools.tools.analytics` |
| root (unchanged) | `devtools.astgrep`, `devtools.shape_contracts`, `devtools.run` |

Note `graph` renamed to `graph.fitness`: a module named `graph` cannot live in a package named `graph`, and
the new name says what it is (the arch-FITNESS gate).

**Nothing to do by hand.** Every one of these paths is copier-rendered — they live in the template's
`noxfile.py`, CI workflow and pre-commit config, so `copier update` rewrites them all. The only way to see an
old path after an update is a devtools invocation you added yourself in a LOCAL-SLOT; if so, fold in the
folder segment. `$(python -m devtools.tools.config …)` substitutions in your own scripts likewise move.

**Why it moved.** Thirty-one flat modules had outgrown a flat directory. `plumbing/` (machinery) and `graph/`
(the read-model + fitness gate + viewer that all consume it) are genuine co-use clusters. The gate folders —
`coupling/`, `cohesion/`, `hygiene/` — group by the question a gate answers; that is a *by-domain* layout
rather than a by-import one (the gates wire to `plumbing`, not to each other), chosen so the tree is legible
to a maintainer. The table above is the full path map.

**This is not a breaking change you can be caught by.** An old path simply stops existing; a script that still
calls `python -m devtools.demeter` fails loudly with "No module named devtools.demeter" rather than silently
doing nothing.

---

## v1.12 — `SLF001` (private-member access) is now an enforced ruff gate

**What you'll see.** After `copier update` past v1.12, `ruff` fails with a wall of `SLF001 Private member
accessed: _foo` — often dozens to hundreds of hits, concentrated in the op-namespace helper classes the
`py-top-level-function` ast-grep gate already mandates. On mindscape this was **102 hits across ~30 files**.

**Why it is not a rule bug.** `SLF001` and the op-namespace mandate are **independent axes**.
`py-top-level-function` only requires *a helper lives on a class* — it says nothing about static-vs-instance,
private naming, or how you call a sibling. The wall of hits comes from **one self-imposed style**: a stateless
`@staticmethod` calling a sibling private as `Cls._helper()`. A `@staticmethod` has no `self`, so a same-class
call must name the class; `ruff` does no class-scope analysis, so it reads `Cls._helper` as an outside
reach-in and flags it. Genuine cross-class reaches (`OtherCls._private`) are flagged too — and *those* are
real. The fix keeps the compliant idiom clean and lets the real reaches surface.

**Do not** carve `SLF001` back out tree-wide in the `per-file-ignores` LOCAL-SLOT — that silences the real
reaches too and forfeits the gate.

**The recipe** (validated on mindscape PR #66: 102 → 0 with no per-file carve, `nox -s lint` green with
`SLF001` enforced + `shape_contracts --assert`, 332 tests passing). Apply in order — it parallelizes across
files and ruff self-verifies each step:

1. **`@staticmethod` → `@classmethod`; same-class sibling calls `Cls._x` → `cls._x`.** `cls` is allowlisted,
   so same-class access goes clean. The class stays **stateless** (no instance, no state — `cls` is the class
   object, not `self`). **External callers do not change** — a `@classmethod` is still called `Cls.method(x)`.
   This clears the bulk of the hits mechanically.
2. **Module-level `def main()` → `@classmethod main(cls)` on its class; the entrypoint guard calls
   `Cls.main()`.** A free `main` reaching into a class's privates is the same pattern one level up.
3. **Genuine cross-module shared privates → promote to public API.** These are the *real* reach-ins the rule
   exists to catch. Rename `_thing` → `thing` and expose it deliberately. Note: a newly-public **array/tensor**
   boundary then needs a jaxtyping shape if `shape_contracts` runs with `--assert` (ml repos) — type it.
4. **Library-private monkeypatches** (reaching into a third-party lib's `_internal` on purpose) → keep a
   per-line `# noqa: SLF001`. This is the honest, localized exception; it does not spread.

**Result.** The compliant op-namespace idiom is `@classmethod` + `cls._helper`; SLF001 stays fully enforced;
the only surviving hits are deliberate `# noqa`. See [`SPEC.md`](SPEC.md) for why SLF001 is a gate.

---

## v1.24.0 — the method-level test mirror, unit-test size, and the `bare` layout

Two new **blocking** gates ship in `nox -s lint`, in CI, and in the batch runner. Both are clean on a fresh
generation, so a new project ratchets from day one. An **existing** repo will very likely open red — that is
the point of the gate, and the paragraph below is how to land it without a big-bang conversion.

The convention, the trade-off, and the case *against* it are in [`UNIT_TESTS.md`](UNIT_TESTS.md).

### `mirror.py` — every public method has a `test_<method>` that calls it and asserts

`graph.py`'s existing mirror asks whether a module **has a test file**. One smoke test satisfies that for a
module of twenty methods. `mirror.py` asks the question people mean, per method.

Findings come in three kinds and cost wildly different amounts, so the message tells you which:

| the message says | what it is | the fix |
|---|---|---|
| `...is not named 'test_x'; rename it` | a test already calls it and asserts | rename (and merge, if several) |
| `reached by N other module(s)` | a contract with no test | write the test |
| `called only inside its own file` | public by naming accident | add the underscore |

The third is not noise — on this repo 15 of 119 findings were methods that were never meant to be public.

**Landing it on an existing repo.** Do not convert everything at once. In order of preference:

1. Set `test_layout = "off"` in `[tool.structure]`, land the update, then turn it back on and work the list
   down. This is the honest temporary state and it disables **both** mirrors, so say so in a ticket.
2. Take the `rename it` findings first — they are mechanical and usually most of the list. On this repo they
   were 60 of 119.
3. Use `# devtools-ignore: test-mirror` on individual methods for the genuine residue. **The list is the
   signal**: short is fine, growing means the convention is pointing at something.

**Ambiguity.** Two classes in one module can share a method name. The gate then demands the qualified
`test_<class>_<method>` and names the exact function in the message. The qualified form is always accepted.

**Properties are covered too**, and are matched by attribute *access* rather than by a call — `test_total`
must read (or write, or delete) `obj.total` and assert. A getter, its setter and its deleter are **one**
member, so one `test_total` covers all three.

**Exempt by kind:** `main()`, private *methods*, declarations (a `Protocol` member or abstract method — its
body is `...`, so there is nothing to call and nothing to assert), and an override of a same-module base
(one polymorphic contract, covered by the base's test).

Every class in the module is in scope. Whether a method needs a test is a question about the method; the
class only supplies the name the finding is reported under.

### `small.py` — a unit test touches nothing it did not create

No external data root, no network, no sleep, no unseeded RNG. **Unit tests only** — an integration test
SHOULD read a real fixture and an e2e SHOULD shell out; the gate reads the unit tree and nothing else.

Absolute paths are only flagged when passed to something that opens them, so a `"/mod.py"` substring
assertion or a `/*...*/` marker in generated HTML is not a finding.

The usual fixes: `tmp_path` instead of a data root, a fake at the I/O boundary instead of the network,
removing the race instead of sleeping through it, and `random.seed(0)` / `np.random.default_rng(0)` once per
file (the seed rule is per-file, so a seed in a fixture covers the module).

### `test_layout` — two values now, and `mirror` changed meaning

`tests/unit/<pkg>/store.py` mirrors `<pkg>/store.py`. **The test file carries its module's name** — so what
a test covers is visible in its path rather than reconstructed by the reader. `test_` is how pytest *finds*
files, not a convention, and a path mirror whose path doesn't match the name isn't one.

**Two breaking changes to the setting:**

| was | now |
|---|---|
| `"mirror"` = `tests/unit/<pkg>/test_store.py` | `"mirror"` = `tests/unit/<pkg>/store.py` |
| `"flat"` = a `test_store.py` anywhere under `tests/` | **removed** |
| `"off"` | unchanged |

An old value left in your `pyproject.toml` fails loudly (`unknown test_layout`) rather than resolving to
something else — a config error must not be able to look like an answer.

**Why `flat` is gone.** It wasn't a threshold, it was a *different predicate*: "a file with this name exists
somewhere" instead of "this module's test is at its mirror path." `RULE_INVENTORY.md`'s union law says a
universal rule never varies per repo — only thresholds and vocabulary move. It was also quietly worthless:
with no single file to read, the method-level gate stood down, so a repo on `flat` got the *appearance* of
the mirror convention.

The template ships all three settings together, because the layout without the pytest ones is a trap —
pytest would collect nothing and the suite would report green while running zero tests:

```toml
[tool.structure]
test_layout = "mirror"

[tool.pytest.ini_options]
python_files = ["*.py"]     # REQUIRED — without it nothing is collected
python_classes = []         # the convention is test_<method> functions; no test classes
```

`mirror.py --assert` fails on that config rather than passing, so the failure mode cannot hide.

Then drop the prefix from every mirror file — one `git mv` per file, and the gate tells you immediately if
you miss one:

```bash
cd tests/unit/<pkg> && for f in test_*.py; do git mv "$f" "${f#test_}"; done
```

**There is no partial escape, and that is deliberate.** `off` turns off *both* mirror gates — including the
file-level "every module has a test" check you are passing today. So a repo with a large method-mirror
backlog has two honest options: work the list down with per-method `# devtools-ignore: test-mirror`, or set
`off` and accept that it drops a gate too. A knob whose only purpose is to make a rule optional is the thing
the union law rejects; if the ignore list runs to hundreds of lines, that is the convention telling you
something rather than a case for a third setting.

`sdlc-devtools` made this move first; the conversion immediately caught a test asserting
`python -m devtools.test_cli`, a module that has never existed and read as correct only because the prefix
made the mirror's name differ from its subject's.
