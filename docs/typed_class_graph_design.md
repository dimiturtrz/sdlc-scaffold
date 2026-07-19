# Typed class-relationship graph — design note

> Status: DESIGN (not yet built). Forward-looking; will be consolidated into SPEC/README once
> the first batch lands. Captures the reasoning so it isn't lost. No version bump until code ships.

## Motivation

`graph.py` today builds an **import-only** graph (grimp: module→module import edges) and ranks it with
networkx (cycles, god-module fan-in/out, instability). Import edges are **noisy** — importing a module ≠
really depending on it (type-only imports, re-exports, side-effect imports all look identical to a real
dependency). The goal: gates that talk about **real dependencies**, so AI-authored architecture can be
*trusted* because it's machine-enforced on meaningful rules, not import-noise.

The house invariants make this tractable where generic Python can't: **everything is a class**
(ast-grep `in-a-class` rule) and **everything is typed** (pyrefly strict — init args + fields annotated).

## The arrow taxonomy

Every class→class relationship, UML-grounded:

| arrow | endpoints | native level | source | notes |
|---|---|---|---|---|
| `import` | file → file | **file** | grimp | the roll-up projection (below); sound |
| `inherits` | class → class | **class** | ast bases | is-a (subclass / ABC / Protocol) |
| `holds` | class → class | **class** | ast field annotations | has-a (`self.repo: UserRepo`) — composition + resolver fuel |
| `calls` | method → method | **method** | ast Call + declared receiver | uses behavior; `via=construct` sub-tag = `B()` creation |
| `references` | method → class | **method** | ast signature annotations | API-surface dep; **kept as attribute, ungated** (rarely pure, low signal) |

Sound *modulo reflection* (the `calls` residual, below). **Folded:** `constructs` → a `via=construct`
sub-tag on `calls` (mechanically a call to `__init__`; still queried separately for the concrete-wiring
partition). **Demoted:** `references` computed but ungated until a real need. `raises`/`catches`/`decorates`
— deferred. So **four gated kinds**: `import` · `inherits` · `holds` · `calls`.

## Levels and roll-up — import is the coarsest projection

Everything is a node in one **fractal containment tree** — `package ⊃ file ⊃ class ⊃ method` — and each
arrow is emitted at its **native level**: `import` @ file, `inherits`/`holds` @ class, `calls`/`references`
@ method.

```
package ⊃ file ⊃ class ⊃ method          (containment tree — every container is a node)
   import@file   inherits/holds@class   calls/references@method
```

Any arrow **rolls up** by projecting its endpoints to a containing node. **`import` is just the file-level
roll-up of the finer arrows, minus self-loops** — roll a method→method `call` up to its owner classes, up
to their files, and you land on the import edge. The finer arrows **decompose** import by *why*, which is
why "imports are noisy": import is the coarsest fold, flattening every reason into one line. The diagnostic
falls out — an import whose roll-up carries only *structural* reasons and **no** `calls` = "you depend on
the type but never use it" = a noisy / dead-ish import.

**Two classes in the same file** roll up to a file **self-loop** → dropped → which is exactly why the module
import graph can't see intra-file relationships. So the class graph is strictly richer: cross-file, its
roll-up ↔ the grimp import set (every cross-file arrow needs an import); intra-file, it adds edges import
*structurally cannot represent* (the dropped self-loops). **Don't stop at files** — feature-envy lives @
method, composition @ class. The *data* goes to method level; the *view* defaults to file (folded) and
drills down. archmap's containment (parent/descendants) already IS this tree.

### One edge, many reasons

Between A and B several arrows co-exist (`inherits` + `holds` + `calls`×3). Represent as a **DiGraph with a
per-edge `{kinds: set, weights}` attribute**, not a MultiDiGraph: coupling metrics want one edge per pair
(A and B are coupled, once) with strength as weight; per-kind gates read the count off the attribute. The
import edge = every edge with a non-empty kind-set, rolled up to file level.

### Why `calls ⊆ import` here (the key result)

In generic Python, calls leak past imports (dynamic dispatch, duck typing) → unsound → advisory-only.
**Our constraints close the leak:**

- **Injected dep** — `def __init__(self, h: Handler)` → `Handler` is annotated → imported. `self.h.run()`
  resolves to `Handler` → import edge exists.
- **Inherited method** — to inherit B you import B; the call resolves to the imported base.
- **Interface call** — resolves to the declared *interface* (imported). We **do not trace the concrete
  impl, and shouldn't** — the code commits to the interface; that's the real architectural dependency.

So every call's declared receiver type is imported → `calls ⊆ import`. Call is **not** a behavioral
outlier — it's the 5th decomposition, and the whole graph is a **refinement of the sound import graph**.

**Consequence — call edges are ~sound → hard-gateable, not advisory.** Every receiver has an enforced
declared type; we attribute to the declared type (never guess the concrete) → resolution is deterministic
→ even absence-gates (dead-import = import with no call) become reliable. The typing constraint *buys back*
the soundness generic Python lacks.

**The concrete dependency isn't lost — `constructs` captures it, at the right place.** A concrete impl is
instantiated *somewhere* (factory / main / DI wiring), emitting `constructs → Concrete`. So:
`call → interface` (behavioral contract) and `construct → concrete` (wiring) **partition** the coupling —
behavioral on the interface, concrete at the wiring site where it architecturally belongs.

### Residual holes (honest soundness limit)

Resolution is complete *modulo* what breaks typing:
- **return-chains** `self.get_repo().save()` — needs return-type resolution (a second lookup; the
  annotation exists). Bounded extension, not a wall.
- **reflection** `getattr(self, n)()`, `**kwargs` forwarding, monkeypatch — genuinely untyped. But these
  are anti-patterns the type gate already discourages → rare, and become the documented escape-hatch
  (like the ML jaxtyping waiver). A per-repo `# arch: ignore` / config slot.

Direct cases (field / param / construct types) resolve soundly *today* from annotations.

## `has-a` is the resolver keystone

`holds` (field-type annotations) is not just an arrow — it's the **fuel for resolving `calls`.**
`self.repo: UserRepo` (the has-a edge) is exactly how `self.repo.save()` resolves to `UserRepo.save`.
So building the `holds` edges and building the call resolver are the **same annotation-reading pass**.

## Nodes

Nodes = **classes** (our one-class-per-file invariant makes class ≈ file, and aligns the graph with the
taxonomy unit lcom/ast-grep already reason about). But a file legitimately holds one **primary** class +
**satellites** (its config dataclass / enum / helper). So:
- tag node **roles**: `primary` vs `satellite` (config/enum/helper subordinate to a primary).
- satellites are excluded from coupling metrics (same move lcom makes for ABC/stub).
- **two *primary* classes in one file = a Structure gate firing** — the invariant violation *is* the smell.

Layering (import-linter's job) is package-level, so keep module/package as a **containment** attribute on
class nodes (archmap already models parent/descendants). The graph is hierarchical:
`package ⊃ module ⊃ class ⊃ method`; each metric queries the right tier.

## Metrics = edge-subset queries

The networkx engine is edge-agnostic. Every metric becomes a query over an edge-subset:

| metric / gate | edge-subset | blocks? |
|---|---|---|
| cycles / layering / build-order | `import` (or `import`-reasons) | yes (sound) |
| real fan-in/out, usage-instability | `calls` | yes (sound under our constraints) |
| **dead import** | `import` minus `calls` | yes (reliable under full resolution) |
| **feature-envy** | `calls`, own-class vs foreign ratio | yes, with a resolution-confidence guard |
| **forbidden-use contracts** | `import` ∪ `calls` — "domain must not *use* infra" | yes |
| composition cycles | `holds` (A has B, B has A) | yes |
| interface-segregation / LSP / "abstract with no impl" | `inherits` / `implements` | yes |

**Demeter** stays *outside* the graph — it's chain-depth *inside* a method body (`a.b.c.d`), pure
AST-local, a standalone check (or ast-grep rule). Don't force it into an edge.

Contract DSL: generalize import-linter's forbidden/layers/independence from `import`-only to **edge-kind
aware** ("must not *call*", "must not *hold*", "must not *construct*"). Once matched + extended, import-linter
can be retired (absorbed into the graph's contract engine).

## Build batches (sequencing falls out of the hierarchy)

**Batch 1 — decompose import into reasons** (structural, cheap, one AST pass):
`inherits` + `holds` (+ `references` as ungated attribute) @ class level, node re-key to the containment
tree + roles, tag edges with their `kinds` set. Self-check: **cross-file** structural arrows roll up to a
grimp import; **intra-file** arrows are file self-loops with no import (expected, not a bug). Kills
import-noise. Value without calls.

**Batch 2 — call layer** (the resolver): annotation/declared-type attribution, `call→interface` /
`construct→concrete` partition, return-chain extension, reflection escape. Fuel = Batch 1's `holds` edges.

**Batch 3 — new gates + contract DSL**: feature-envy, forbidden-use, dead-import, composition cycles;
edge-kind-aware contracts. Nearly free once edges exist.

**Standalone — Demeter**: AST-local, no graph dependency, ship anytime.

## Zero new dependencies

`ast` (parse — we already walk Call/Attribute/bases; lcom is the richest at 27 ast refs, and its
per-method access collection is the feature-envy seed), `grimp` (import resolution + the sound base),
`networkx` (metric engine, edge-agnostic). No jedi/griffe/pyrefly-consumption — annotation-only resolution
needs none.

## Visualization (archmap extension)

- **edge coloring + line-style** by kind (`import` grey/thin, `calls` accent/solid/weighted, `inherits`
  dashed) — encode the sound/approximate split *structurally* (line style), not hue alone.
- **filtering**: toggle edge-kind / node-role / fold-level; a **"sound-only"** toggle renders the provable
  subgraph.
- **method-level drill-down** — collapsed by default (else node count explodes), expand-a-class on demand.
- **changelog / diff view** — `archmap --diff <ref>` renders added (green) / removed (red) edges at class
  level; surface on the PR ("this change added `call` edge domain→infra"). This is the **trust
  centerpiece**: the gate enforces, the diff *explains* how a change moved the architecture in
  real-dependency terms.
- `graph.json` extended with edge kinds + node roles, kept deterministic (don't regress the diff-truth).

## Parked / open

- Contract-DSL syntax for edge-kind-aware rules (extend `[tool.importlinter]` vs a new `[tool.arch]`).
- Whether to retire import-linter or keep it alongside.
- Return-chain resolution depth (how far to chase).
- `references`/`raises`/`decorates` — include only when a gate needs them.
