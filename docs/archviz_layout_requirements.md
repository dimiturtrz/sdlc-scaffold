# Archviz layout — requirements & acceptance

The interactive architecture viewer (`sdlc-devtools/devtools/archviz/viewer.js`, emitted by
`python -m devtools.graph.archmap`) renders the marked package tree as nested compound boxes
(`module ⊃ class ⊃ method`) joined by typed arrows. Its **content and controls are done and good**
(depth toggles, per-kind, legend, bands, collapse/expand, greyscale-safe styling). The open problem is the
**auto-layout**: placement, sizing, order, compression. This file is the spec that layout work is measured
against — it exists so "is it better?" is a check, not a vibe.

## What is wrong today

The layout is `cytoscape-fcose` (a force-directed compound layout) plus a hand-written "parking" pass that
grids *edgeless* children. Force layout cannot **guarantee** a tight compound box: a single edge can fling
one child to its box's far edge, and because a box is sized to bound *all* its children, one outlier makes
the whole box enormous and near-empty. Observed failure modes: a module box stretched to a full-width or
full-height empty strip with two nodes in opposite corners; a wide empty box with everything clustered in a
corner. Tuning force constants (`gravityCompound`, `gravityRangeCompound`, `nodeRepulsion`, `edgeElasticity`)
is whack-a-mole — tightening one axis loosens another — and every constant is an unprincipled magic number.

The current committed state carries interim force-constant tweaks (cross-module edges weakened,
`gravityCompound 8 / gravityRangeCompound 5`). They are strictly better than the untuned baseline but are
exactly the magic constants this effort exists to remove; treat them as the BASELINE to improve on, not the
target.

## Requirements (ranked — the ranking is the tie-breaker when two pull apart)

1. **Compression.** Every compound box shrink-wraps its content. No large empty regions; no child stranded
   far from its siblings. This is the loudest, most-repeated complaint and the top priority.
2. **Position encodes structure.** Placement is legible as *architecture*: related nodes near each other, a
   class's call-flow readable, arrows telling a real story. A tight-but-arbitrary layout still fails.
3. **Deterministic.** Same `graph.json` → same layout, every run. Reliably good beats occasionally-great.
4. **As planar as possible.** Minimise edge crossings. Force layout does none; this is a real want.
5. **No magic constants.** Every layout parameter is DERIVED — from node sizes, the graph, the siblings'
   own spread — not a tuned guess. (House rule; see `CLAUDE.md`.)
6. **Up-down logic is acceptable.** A hierarchical top-down (layered / Sugiyama) arrangement is fine, and is
   a natural fit for the directional call/construct/import edges.
7. **Keep the compound-map metaphor.** Nested boxes + typed arrows. Not a flat flowchart.
8. **Arrows stay legible** (secondary). The point is reading calls / construct / holds; compaction must not
   turn them into a hairball.
9. **Preserve the UI/UX.** Depth, per-kind, legend, bands, collapse/expand, styling all stay — they are
   done. Layout work touches placement/sizing/order/compression ONLY.

## Acceptance criteria (the measurable now → then diff)

Verified by a Node harness against the real `graph.json` (see below), so a change is scored BEFORE any
browser look; the owner confirms the final visual.

- **Compression:** no compound box below a derived fill floor (node+routing area vs box area). Report the
  count of under-filled boxes and the median fill; target is zero pathological boxes (the full-width/height
  empty strips) and a materially higher median than the fcose baseline.
- **Crossings:** total edge-crossing count strictly lower than the fcose baseline at each depth.
- **Determinism:** two consecutive layout runs on the same input produce byte-identical positions.
- **No magic constants:** the layout code review shows every numeric derived or justified; the interim
  `gravityCompound`/`edgeElasticity`/`nodeRepulsion` tweaks are gone.
- **UI intact:** depth, per-kind, collapse/expand, legend still work (manual + the existing e2e/unit checks
  that touch the viewer contract).
- **Weight budget:** if a layout dependency is added, its inlined page-weight cost is stated and accepted
  explicitly (current page ≈ 0.7 MB; `elkjs` alone is ~1.6 MB).

## Candidate approaches (decided per-stage in the epic, not up front)

- **A — deterministic compaction on fcose.** *(SHIPPED — see Stage A result above.)* Extend the existing parking pass to recapture *any* geometric
  outlier (not just edgeless) into the tidy block. Lowest risk, no new dependency, keeps the working viewer,
  guarantees compression (#1) and determinism (#3), threshold derived from sibling spread (#5). Does NOT
  deliver planarity (#4) or up-down (#6).
- **B — layered engine (ELK / `cytoscape-elk`).** Deterministic, crossing-minimising, up-down, compound-aware
  — hits #1–#7 by construction. Costs ~1.6 MB inlined and a full engine swap (rewire relayout / collapse /
  expand, delete parking), with the risk of regressing the *working* interactive features. Prototyped in
  Node: module boxes come out 80–87 % filled; class boxes are spacious (layered routing room); canvas is
  large but structured.

Prototype data lives in the epic. The decision between A and B is a stage gate, not a foregone conclusion:
A is the proportionate fix for the actual complaint (compression); B is only worth its cost if planarity /
up-down prove to matter after A lands.

## Measured baseline (fcose as shipped, `randomize:false`)

Run: `node sdlc-devtools/devtools/archviz/measure.cjs` (defaults to the pinned fixture
`sdlc-devtools/tests/fixtures/archviz_graph.json`; the full JSON is recorded at
`sdlc-devtools/tests/fixtures/archviz_baseline.json`). Three fully-expanded views, the maximal picture the
complaints were about:

| view | nodes/edges | compounds | under-filled | median fill | crossings | canvas | deterministic |
|------|-------------|-----------|--------------|-------------|-----------|--------|---------------|
| module / imports  |  37 / 79 |  7 | **3** | 0.16 |  509 | 1171×1008  | yes |
| class / structure |  84 / 29 | 17 |  0    | 0.29 |   10 | 1756×1733  | yes |
| all / all         | 370 / 459 | 51 | **25** | 0.15 | 3183 | 7649×9670 | yes |

This is the floor. The numbers Stage A must move: **under-filled 25→0** and **median fill 0.15→materially
higher** at all/all (the empty-box complaint, quantified — the worst boxes fill under 2%), and **crossings
down** at every view. Determinism is a solved problem, not a Stage-A goal: fcose's spectral init is
byte-deterministic with `randomize:false` (the harness confirms Δ=0). The *viewer* is non-deterministic on
load only because it reseeds (`randomize:true`) on depth changes — a viewer choice Stage A drops, not an
engine limitation. The 509 crossings on a 37-node import graph, and 25 of 51 compounds under a tidy-pack
half-density, are the concrete evidence force layout ignores both planarity and compression.

## Stage A result (fcose defaults + deterministic compaction, bd 42b.2)

The force pass and the compaction now live in one shared module (`devtools/archviz/layout.js`), imported by
both the viewer and the harness. The two interim magic knobs are gone (fcose keeps its own defaults);
`compact` shrink-wraps every compound structurally instead. Measured against the floor above:

| view | under-filled | median fill | crossings | canvas | determinism |
|------|--------------|-------------|-----------|--------|-------------|
| module / imports  | 3 → **0** | 0.16 → **0.35** | 509 → 601 | 1171×1008 → 1219×963 | yes |
| class / structure | 0 → 0 | 0.29 → 0.28 | 10 → 14 | 1756×1733 → **1274×1329** | yes |
| all / all         | **25 → 0** | 0.15 → **0.37** | 3183 → 5562 | 7649×9670 → **4803×4902** | yes |

**What Stage A delivered:** compression (#1) — zero pathological boxes in every view, median fill up 2.5× at
all/all, canvas roughly halved in each axis; determinism (#3) — every view byte-identical across runs, the
viewer's reseed dropped; no magic constants (#5) — the two interim knobs retired, guarded against return.
Compaction preserves well-filled clusters (structure #2) and only tidies boxes the harness flags under-filled,
so module/class views are near-untouched.

**The cost, and what it hands the decision gate (42b.3):** crossings rose, sharply at all/all (3183 → 5562).
That is the compression↔planarity tension made concrete — packing boxes tight forces edges to cross more, and
fcose's larger, airier baseline had room to avoid them. Compaction does NOT deliver planarity (#4) or up-down
(#6); it grids under-filled boxes in reading order, which reads as adjacency, not flow. So the gate's question
is sharp: is 5562 crossings (with guaranteed compression + determinism, zero new deps, a working viewer) good
enough — or does the crossing count + the want for #4/#6 justify ELK's 1.6 MB and a full engine swap? The
fixture `archviz_baseline.json` holds the fcose floor; `node measure.cjs` reports the Stage A numbers above.

## The measurement harness (why this can be verified without a browser)

Both fcose (via a headless cytoscape run or the emitted positions) and ELK run in Node. A small harness
loads `graph.json`, runs a candidate layout, and reports: per-compound fill, count of under-filled boxes,
total edge crossings, canvas size, and a determinism check (two runs identical). Every layout change is
scored by the harness first; the browser look is the final confirmation, not the debugging loop. This is what
turns "makes no sense" into a number that has to go down.
