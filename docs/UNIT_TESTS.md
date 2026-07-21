# Unit tests — the convention, its gates, and the case against it

This is the scaffold's unit-test doctrine. It is opinionated, it is enforced by three gates, and the
position it takes is a minority one in the current literature. Section 5 is the argument *against* it,
stated as strongly as we can make it, because a convention that only ever hears its own case stops being a
decision and becomes a habit.

**Scope: unit tests only.** Integration and e2e tests are deliberately out of scope here. They answer
questions a unit test cannot, and holding them to these rules would be the doctrine misunderstanding its
own subject. Their conventions are unfiled work, not an oversight.

---

## 1. The convention

1. **Mirror on the method.** A module has one mirror test file; each public method `A.a` has a `test_a` in
   it. Where the file lives is `[tool.structure] test_layout`.
2. **A test calls and asserts.** `test_a` must call `A.a` and then assert — on the returned value or on the
   resulting state.
3. **A method needing no assertion after the call is suspect.** If there is nothing to check, ask what the
   method is for. That question is the point of the rule; the answer is sometimes "nothing", and then the
   method should go.
4. **The residue is ignored explicitly**, per method and rule-named: `# devtools-ignore: test-mirror`.
   Never blanket, never a whole-file suppression.
5. **A test is a container, not a case.** `test_a` sets up doubles, runs *n* parameter combinations, and
   makes *m* assertions — one test verifies *n×m* facts about one method. Dense and systematic.
6. **Verify state and return values, never call chains.** What the code *did*, not who it *talked to*.
7. **Doubles stay close to real**: real object → fake → stub. Never a mock. (Note the irony that
   `unittest.mock` is named for the one thing rule 6 excludes.)
8. **Fixtures produce inputs, never expected outputs.** A fixture that computes the expected value agrees
   with the code by construction, and the test proves nothing.
9. **A unit test is small**: no external data root, no network, no sleep, seeded RNG.

## 2. Why the name is enforced

Rule 1 could have been checked positionally — "*some* test in the file calls it and asserts". It is not,
for three reasons:

- A positional check passes a file where one broad test happens to touch nine methods on its way somewhere
  else. That file has one test and nine methods, and the gate would call it covered.
- It leaves the naming as an unenforced preference, and an unenforced convention drifts. Measured before the
  gate existed: **0% naming compliance** — not one test in any of the four trees surveyed was named
  `test_<method>`.
- The name is the cheap lookup. "What covers `A.a`?" is answered by reading one function name.

A test that calls the method and asserts but is named something else produces a **different message** — a
rename, not a missing test. The distinction matters because the two cost wildly different amounts.

**Ambiguity is resolved, not legislated.** Two classes in one module can share a method name; `test_a`
cannot mean both. When the name is unique, `test_a` is expected. When it is shared, the qualified
`test_<class>_<method>` is demanded — and the gate names the exact function to write. The qualified form is
always accepted, so a repo preferring it everywhere is never fought.

## 3. The two remedies

"Nothing tests this method" has two correct fixes, and the gate names whichever fits:

| the gate sees | what it means | the fix |
|---|---|---|
| reached by another module | a contract someone depends on, with no test | write the test |
| called only inside its own file | public by naming accident | add the underscore |

The second is not noise to be filtered. It is a real defect of a different kind, and the gate finding it is
the gate working — **15 of this repo's own findings were this**, methods that were never meant to be public
and had simply never been asked.

## 4. What enforces it

| rule | gate | notes |
|---|---|---|
| 1, 2, 4 | `devtools/mirror.py` | per-method mirror; resolves the layout through `devtools/layout.py` |
| 9 | `devtools/small.py` | external data / network / sleep / unseeded RNG |
| module has a test at all | `devtools/graph.py` | the file-level mirror this refines |
| 5 | ruff `PLR0915` | not a constraint on density — a dense parametrized table costs ~1 statement, so the ceiling is only reachable by writing the same test longhand |

Rules 3, 6, 7 and 8 are **not mechanically enforced** and are not going to be. Rule 3 is a question, not a
predicate. Rules 6–8 are judgment about what a test *means*, and a gate that guessed at them would be
wrong in exactly the cases that matter. They live here, in review, and in the ignore list — which is the
signal: short is fine, growing is rule 3 pointing at something.

## 5. The case against this convention

Honest statement of where this sits: **the field has largely moved the other way.** The research is in
`research/deep_dives/2026-07-21_test_architecture_sota.md`; the short version:

- **Ian Cooper's "unit" is a behaviour, not a method.** The trigger for a test should be a requirement,
  not a public method — testing per-method couples the suite to structure, so every refactor that moves a
  method breaks tests that were describing nothing the user cares about. On this view rule 1 is precisely
  the anti-pattern.
- **The pyramid has flattened.** Testing Trophy, honeycomb, "write tests, not too many, mostly
  integration" — the mainstream position is now that integration tests buy more confidence per unit of
  maintenance, and that a dense per-method suite is where test-maintenance cost goes to hide.
- **Structural coverage is not behavioural coverage.** `test_a` exists and asserts; that says nothing about
  whether the assertion is *good*. This gate is checkable precisely because it measures shape, and shape is
  the cheap half.

**Why the scaffold takes the minority position anyway**, stated as a bet and not a proof:

- The gate is **precise but incomplete by construction** — it never reports a wrong edge, only a missing
  one. Its findings are always real, which is what lets it block.
- The refactor-brittleness objection is real and is the actual cost being paid. It is mitigated by rules 5
  and 6 — a container test verifying *state* survives an implementation change; it breaks when the method
  moves or is renamed, which is a signal, not a false alarm.
- **Nothing else enforces test-to-code traceability.** No tool surveyed does this. For a codebase that has
  to answer "what covers this?" — an audit, a regulated context, a handover — that traceability is the
  product, and it is worth the structural coupling.
- The alternative on offer is not "better tests", it is *no rule*. Measured: 0% naming compliance and
  15 methods that were public by accident. The unenforced version of this convention was not producing
  integration-first discipline; it was producing whatever each file's author felt like that day.

This is a live trade-off, not a settled one. If the maintenance cost shows up, rule 1 is the thing to
revisit first — and `test_layout` already makes the enforcement configurable rather than assumed.
