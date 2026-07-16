# Interactive Architecture-Graph Viewer — Library Survey (build decision)

Date: 2026-07-16
Context: We already derive a Python-import architecture graph via **grimp** (nodes = modules/packages, folder≡package≡module). Two edge types: (1) a **containment DAG** (parent→child nesting, arbitrary depth) driving expand/collapse, and (2) **dependency edges** (import arrows). We want an interactive viewer meeting R1–R6 below, shipped from a doc-gen tool, private/self-contained.

## Requirement recap
- **R1** Expand/collapse containment, ARBITRARY depth (not C4's 4-level cap).
- **R2** Aggregating dependency arrows: collapsed parent → descendants' edges merge into one meta-edge carrying a **count** (e.g. `viewer→core [7]`); expand splits it back. *The hard ask.*
- **R3** Focus mode: select module → isolate importers+imports, dim rest.
- **R4** Auto-layout that handles compound/nested nodes.
- **R5** Self-contained/private: local render or single self-contained HTML; no remote round-trip; ideally no Java.
- **R6** (bonus) Diffable source: input is a committed text/JSON artifact so architecture diffs show in PRs, while render stays dynamic.

---

## Bottom line (ranked for OUR use case)

1. **cytoscape.js + `cytoscape.js-expand-collapse` + `fcose` + `view-utilities`** — the frontier fit. R2 meta-edges are AUTOMATIC and carry the underlying edge collection (count = its length). MIT throughout. Verdict: build here.
2. **AntV G6 v5 (combos + CollapseExpand behavior)** — strong, more "batteries-included" UI, arbitrary-depth combos, built-in collapsed-marker showing child count; but edge *merge-with-count* on collapse is less turnkey than cytoscape's meta-edges (edges reconnect to the combo; you decorate the count). MIT.
3. Everything else falls short of the R2+R4 combination (react-flow: all DIY; sigma: no compound; D2/Structurizr/Mermaid/Graphviz: static or capped; Sourcetrail forks: turnkey but not diffable).

**Nothing satisfies auto-derived + diffable-source + interactive simultaneously.** The real frontier is exactly the pattern in the task prompt: **commit `graph.json` (grimp output) + ship a self-contained cytoscape/G6 HTML viewer.** State that plainly to the user.

---

## Class A — Graph-explorer JS libs (feed them our JSON — most likely answer)

### cytoscape.js + expand-collapse — TOP PICK
- **R1**: `cytoscape.js-expand-collapse` (iVis-at-Bilkent) does arbitrary-depth compound expand/collapse. MIT. https://github.com/iVis-at-Bilkent/cytoscape.js-expand-collapse
- **R2 (the key win)**: collapsing a compound node **auto-generates "meta edges"** (class `cy-expand-collapse-meta-edge`). The collapsed edge carries a `directionType` (`unidirection`/`bidirection`) and, critically, a **`collapsedEdges` collection** holding the original edges it replaced — so **the count is `edge.data('collapsedEdges').length`**, i.e. the `viewer→core [7]` label is a one-liner from data the extension already stores. Option `groupEdgesOfSameTypeOnCollapse` (+ `edgeTypeInfo`) controls whether/how parallel edges fold into one. Expanding restores the real per-child edges. This is the single cleanest R2 mechanism found. (README, master.)
- **R3**: sibling extension `cytoscape.js-view-utilities` gives `highlightNeighbors()` / `neighborhood()` + dimming out of the box. MIT. https://github.com/iVis-at-Bilkent/cytoscape.js-view-utilities
- **R4**: `fcose` (fast compound spring embedder) and `cose-bilkent` are compound-aware; README recommends `cose-bilkent` with `randomize:false` to preserve the mental map across expand/collapse. https://github.com/iVis-at-Bilkent/cytoscape.js-fcose
- **R5**: pure client-side JS, bundles into one HTML file. No server. MIT (core + all three extensions from the same lab).
- Net: **R1+R2+R3+R4 with the least custom code.** This is the recommendation.

### AntV G6 v5 — strong runner-up
- **R1**: first-class **combos** (nested groups), arbitrary depth; built-in **`CollapseExpand`** behavior (double/single-click). https://g6.antv.antgroup.com/en/manual/behavior/collapse-expand and https://g6.antv.antgroup.com/en/manual/element/combo/overview
- **R2**: on collapse, "all connections will connect to the Combo" — edges reconnect to the combo node, but the docs do **not** promise automatic parallel-edge merge with a preserved numeric weight. The base combo does compute descendant info: `getCollapsedMarkerText` yields a **collapsed marker (child count badge)** on the combo (source: `packages/g6/src/elements/combos/base-combo.ts`, v5). So you get a node-level count for free; an edge-level `[7]` count requires a small custom aggregation (group descendant edges by target-combo, sum). Contender, but more glue than cytoscape for the specific meta-edge-count ask.
- **R3**: doable via element state API + `setItemState`/palette; not a single named helper like cytoscape's.
- **R4**: `combo-combined` layout is compound-aware and good. https://g6.antv.antgroup.com/en/manual/layout/combo-combined-layout
- **R5**: client-side, MIT. Heavier/more opinionated API than cytoscape; larger bundle.
- Net: excellent if you want richer built-in UI; slightly more code for R2-with-count.

### react-flow / @xyflow
- Subflows via `parentNode` (v10+). **Expand/collapse is DIY** (toggle `hidden`), and **edge aggregation is entirely hand-rolled** — no meta-edge primitive. Pro examples exist for expand/collapse trees (dagre). MIT core. Great for bespoke node UIs, wrong tool for auto R2. https://reactflow.dev/examples/layout/expand-collapse , https://reactflow.dev/learn/layouting/sub-flows
- Verdict: most custom code of the serious options; skip unless we want React node widgets.

### sigma.js
- WebGL, scales to huge graphs, but **no native compound/parent nodes and no expand/collapse** — you'd fake nesting. Focus/neighborhood is easy. Wrong shape for a containment DAG. Skip for R1/R2.

### vis-network
- Has **node clustering** (`cluster()`, `clusterByHubsize`, `clusterEdgeProperties`) that DOES aggregate edges into a cluster edge — conceptually R2-capable and it can carry a computed label. But clustering is not the same as a clean arbitrary-depth containment hierarchy with stable layout; compound layout is weaker than fcose/G6. BSD/Apache (visjs community). Plausible fallback, not first choice.

### d3 / d3-graphviz
- Maximum control, maximum code. d3-hierarchy + custom force = you reimplement expand-collapse, meta-edges, and layout yourself. d3-graphviz renders Graphviz DOT to SVG in-browser (static clusters). Only pick if the two dedicated libs somehow disqualify. BSD.

### elkjs (layout only)
- ELK's layered/`force` algorithms are **genuinely compound/hierarchy-aware** (this is ELK's strength) and elkjs runs in-browser. It's a **layout engine, not a viewer** — pair with cytoscape (`cytoscape-elk`) or react-flow if you outgrow fcose. EPL. Keep in back pocket for R4 quality.

### Ogma (Linkurious) — commercial
- Excellent grouping/expand-collapse/aggregation, but **paid commercial license** (quote-based, not free). Rules it out for an open portfolio tool. https://doc.linkurious.com/ogma/latest/

---

## Class B — Diagram-as-code with dynamic rendering

- **D2 (Terrastruct)**: first-class **arbitrarily nested containers**; SVG output supports interactive **tooltips + hyperlinks**, and `d2.js` runs dagre/elk layouts client-side. BUT the rendered output is **static** — no in-diagram expand/collapse of containers; you regenerate. Diffable source (nice), not interactively collapsible. MPL-2.0. https://d2lang.com/ , https://github.com/terrastruct/d2-playground
- **Structurizr vNext / Lite**: **Lite repo was archived read-only on 2026-02-04**, replaced by the consolidated (partly-closed) **vNext** — confirmed. https://github.com/structurizr/lite/releases , Patreon "Introducing Structurizr vNext". Also: **C4 is capped at 4 levels** (Context/Container/Component/Code), manual DSL, **Java runtime**, and layout is largely manual (its weak spot). Fails R1 (depth), R4 (auto-layout), R5 (Java). Reject.
- **Mermaid**: static; GitHub CSP blocks `click`/JS interactivity in READMEs. Fine for a committed static picture, not a viewer. Fails R1–R3.
- **Graphviz**: SVG hyperlinks + `cluster` subgraphs, but **static**; no collapse. This is what `tach show` emits locally (`.dot`). Good diffable source, not interactive.
- **PlantUML**: static, Java. Reject for a viewer.
- None of Class B round-trips a committed text source to a *genuinely interactive* (collapse/focus) view — they render static images.

## Class C — Turnkey code-architecture explorers

- **Sourcetrail forks (both alive in 2025/2026):**
  - **petermost/Sourcetrail** — actively maintained, frequent releases through **Dec 2025** (e.g. `2025.12.8`), Clang/LLVM 20, Qt 6.9; **dropped Python indexing support**, so it won't index our Python for us. https://github.com/petermost/Sourcetrail/releases
  - **quarkslab/NumbatUI** — WIP fork, must self-compile; pairs with `numbat` (Python lib to write Sourcetrail DBs) — you could feed grimp→numbat→NumbatUI. https://github.com/quarkslab/NumbatUI , https://github.com/quarkslab/numbat
  - These are the closest to R1–R5 as *desktop apps* (auto-index, interactive, local/private), but they are heavy native apps and **fail R6** (DB is a binary artifact, not a diffable text source) and aren't embeddable in generated docs.
- **Understand (SciTools)** — commercial, paid. Out.
- **Emerge** — Python, generates a browser **d3** force graph of code deps; interactive-ish but **no compound collapse (R1) / no aggregating meta-edges (R2)**. https://github.com/glato/emerge
- **CodeCharta** — code *cities* (metrics via 3D treemap), not a dependency-arrow explorer; wrong metaphor for R2/R3.
- **Gephi** — desktop graph analysis; manual import, not a shippable doc viewer.
- **repowise / misc** — commercial/SaaS, remote. Out on R5.
- **tach** — `tach show --web` **uploads `tach.toml` to gauge.sh servers** (remote — an R5 negative, confirmed); plain `tach show` only emits a local static `.dot`/mermaid. So it's either remote-interactive or local-static — never local-interactive. https://docs.gauge.sh/usage/commands/

**Why Class C ultimately loses on R6:** their state lives in a binary index/DB or a remote service, so the architecture can't be diffed as committed text in a PR. That's the structural reason to prefer the "commit graph.json + static viewer" pattern.

---

## Answering the pointed questions

- **Cleanest R1+R2+R3+R4, least code:** **cytoscape.js-expand-collapse.** Its automatic meta-edges + stored `collapsedEdges` collection give the R2 count nearly free; G6 v5 combos are a close second but need a small custom edge-aggregation for the numeric `[7]`.
- **R2 exact mechanism:** cytoscape — collapse creates a meta-edge (`cy-expand-collapse-meta-edge`) with `directionType` and a **`collapsedEdges` cytoscape-collection**; count = `.length` (label it in a style mapper). `groupEdgesOfSameTypeOnCollapse` + `edgeTypeInfo` control folding. **Weight/count IS recoverable** (from the collection). G6 — collapse reconnects edges to the combo and shows a **child-count marker** on the combo node (`getCollapsedMarkerText`); per-edge count is a custom reduce.
- **Any tool = auto-derived + diffable + interactive at once?** **No.** Interactivity needs a runtime; a commit is static. The resolution is to split them: **commit `graph.json` (the diffable artifact from grimp) and ship a static, self-contained HTML viewer** that hydrates it at view time. That IS the frontier for our case.
- **Build effort for "graph.json + self-contained cytoscape HTML viewer (+ expand-collapse + focus)":** **order of a few hundred lines** of HTML/JS (one page: load JSON, register `expand-collapse` + `fcose` + `view-utilities`, ~2 style blocks, ~3 event handlers for select/focus/collapse). Start from the official expand-collapse demo (`demo.html` in the repo) and the view-utilities highlight demo — both are near-drop-in templates. grimp→`graph.json` is trivial on our side. Inline the JS/CSS (or base64) to satisfy the single-file, no-remote R5 constraint.

## Recommendation
Build the **grimp → `graph.json` (committed, diffable) → single self-contained `architecture.html`** pipeline on **cytoscape.js + expand-collapse + fcose + view-utilities** (all MIT, all client-side). Keep G6 v5 as the fallback if we later want a richer built-in combo UI. Treat the diffable-source vs. interactive-runtime tension as inherent and solved by committing the JSON, not the render.

## Primary sources
- cytoscape.js-expand-collapse (README, options, meta-edge/collapsedEdges): https://github.com/iVis-at-Bilkent/cytoscape.js-expand-collapse
- cytoscape.js-view-utilities (highlightNeighbors): https://github.com/iVis-at-Bilkent/cytoscape.js-view-utilities
- cytoscape.js-fcose: https://github.com/iVis-at-Bilkent/cytoscape.js-fcose
- AntV G6 v5 combos: https://g6.antv.antgroup.com/en/manual/element/combo/overview ; CollapseExpand: https://g6.antv.antgroup.com/en/manual/behavior/collapse-expand ; base-combo source: https://github.com/antvis/G6/blob/v5/packages/g6/src/elements/combos/base-combo.ts
- react-flow subflows / expand-collapse: https://reactflow.dev/learn/layouting/sub-flows , https://reactflow.dev/examples/layout/expand-collapse
- elkjs: https://github.com/kieler/elkjs
- D2: https://d2lang.com/ ; playground: https://github.com/terrastruct/d2-playground
- Structurizr Lite archived 2026-02-04 / vNext: https://github.com/structurizr/lite/releases , https://www.patreon.com/Structurizr/posts/introducing-146923136 ; C4 levels/DSL: https://docs.structurizr.com/dsl
- tach (remote --web caveat, local .dot): https://docs.gauge.sh/usage/commands/ , https://github.com/tach-org/tach
- Sourcetrail forks: https://github.com/petermost/Sourcetrail/releases , https://github.com/quarkslab/NumbatUI , https://github.com/quarkslab/numbat
- Emerge: https://github.com/glato/emerge
- Ogma (commercial): https://doc.linkurious.com/ogma/latest/
