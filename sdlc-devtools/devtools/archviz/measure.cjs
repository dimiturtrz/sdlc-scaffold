/* Layout-measurement harness — turns "the layout makes no sense" into numbers that have to move.
 *
 * WHY this exists (bd 42b.1): the archviz auto-layout is force-directed (fcose), so "is it better?" was
 * being judged by eye, one screenshot at a time. This scores a candidate layout headlessly — no browser —
 * against the real graph, reporting the four things the requirements doc (docs/archviz_layout_requirements.md)
 * ranks: compression (per-compound fill), planarity (edge crossings), determinism (two runs identical), and
 * canvas size. Every layout change is scored HERE first; the browser look is the final confirmation, not the
 * debugging loop.
 *
 * It runs the SAME fcose constants and the SAME parking pass the viewer ships (LAYOUT, below, and park()),
 * so the numbers describe what the user actually sees. Those two blocks are duplicated from viewer.js on
 * purpose for now: viewer.js is a browser IIFE with no exports, and Stage A (bd 42b.2) rewrites the parking
 * pass anyway — unifying the source of truth is part of that rework, not this precondition. Until then, a
 * guard test (tests/unit/test_archviz_layout_baseline.py) holds these copies to viewer.js so they cannot
 * drift silently.
 *
 * NODE SIZES are DERIVED, not rendered: headless cytoscape has no text metrics, so a node's width is modelled
 * from its label length (CHAR_W below). Fill is a RATIO (child area / box area) so the size model cancels;
 * canvas numbers are model-relative and only meaningful compared against another run of THIS harness.
 *
 * Usage:  node measure.cjs [path/to/graph.json]
 *   defaults to the pinned fixture (tests/fixtures/archviz_graph.json) so the baseline is stable across
 *   codebase changes. Pass a live docs/architecture/graph.json to score the current tree.
 */
'use strict';
const Module = require('module');
const path = require('path');
const fs = require('fs');

// The vendored fcose stack uses npm-style requires (`cose-base` -> `layout-base`) but ships as sibling files
// here, not under node_modules. Map those two names to the vendored files so the harness needs no install —
// same dependency-free footprint as the browser page.
const HERE = __dirname;
const VENDORED = { 'cose-base': path.join(HERE, 'cose-base.js'), 'layout-base': path.join(HERE, 'layout-base.js') };
const _resolve = Module._resolveFilename;
Module._resolveFilename = function (request, ...rest) {
  return VENDORED[request] || _resolve.call(this, request, ...rest);
};
const cytoscape = require(path.join(HERE, 'cytoscape.min.js'));
cytoscape.use(require(path.join(HERE, 'cytoscape-fcose.js')));

// ---- shipped layout (MIRROR of viewer.js FCOSE — held by test_archviz_layout_baseline.py) ----------------
const LAYOUT = {
  name: 'fcose', quality: 'proof', animate: false,
  nodeSeparation: 130, idealEdgeLength: 80, nestingFactor: 0.8, gravity: 0.25, numIter: 2500,
  edgeElasticity: (e) => (e.data('crossModule') ? 0.05 : 0.45),
  gravityCompound: 8, gravityRangeCompound: 5,
  nodeDimensionsIncludeLabels: true,
  // fcose's spectral init is deterministic, so randomize:false gives byte-identical runs (the harness's own
  // determinism check confirms Δ=0). The VIEWER reseeds (randomize:true) on every depth change — that, and
  // only that, is why the shipped viewer is non-deterministic on load; the ENGINE is not the obstacle to
  // req #3. Measuring with the deterministic setting is the fair floor for the other three metrics.
  randomize: false,
};

// ---- node size model (DERIVED — see header) --------------------------------------------------------------
const CHAR_W = 7;   // ~advance of an 11px sans glyph
const PAD_W = 12;   // left+right node padding
const LEAF_H = 24;  // a leaf/method box height at 11px + padding
const sizeOf = (label) => ({ w: Math.max(30, label.length * CHAR_W + PAD_W), h: LEAF_H });

// ---- the viewer's view model (MIRROR of viewer.js rebuild/refresh) ---------------------------------------
// A "view" is a (depth, kinds) pair. These reproduce the element set the viewer builds for that view, FULLY
// EXPANDED (nothing folded) — the maximal, hardest-to-compress picture and the one the complaints were about.
const DEPTHS = ['module', 'class', 'public', 'all'];
const KIND_BANDS = {
  imports: ['import'],
  structure: ['inherits', 'holds', 'references'],
  behaviour: ['calls', 'construct'],
};
const isPrivate = (label) => label.startsWith('_');

function moduleOfMap(nodes) {
  // outermost ancestor (the top module) for every id — the viewer's moduleOf, from the parent chain.
  const parent = {};
  for (const n of nodes) parent[n.id] = n.parent || null;
  const top = {};
  for (const n of nodes) {
    let at = n.id;
    while (parent[at]) at = parent[at];
    top[n.id] = at;
  }
  return top;
}

function buildView(graph, depth, kinds) {
  const d = DEPTHS.indexOf(depth);
  const wantClass = d >= 1, wantMethod = d >= 2, wantPrivate = d >= 3;
  const kindSet = new Set(kinds);
  const nodes = graph.nodes.filter((n) => {
    const level = n.level || 'module';
    if (level === 'module') return true;
    if (level === 'class') return wantClass;
    return wantClass && wantMethod && (wantPrivate || !isPrivate(n.label));
  });
  const present = new Set(nodes.map((n) => n.id));
  const top = moduleOfMap(graph.nodes);

  // climb an endpoint to the nearest present ancestor (a filtered-out method rolls up to its class/module)
  const climb = (id) => {
    let at = id;
    while (at && !present.has(at)) at = at.includes('.') ? at.slice(0, at.lastIndexOf('.')) : null;
    return at;
  };
  const contains = (outer, inner) => inner.startsWith(outer + '.');
  const agg = new Map();
  for (const e of graph.edges) {
    if (!kindSet.has(e.kind || 'import')) continue;
    const s = climb(e.source), t = climb(e.target);
    if (!s || !t || s === t) continue;                 // dropped, or collapsed onto one ancestor
    if (contains(s, t) || contains(t, s)) continue;    // containment is not a dependency
    const key = `${s}|${t}|${e.kind || 'import'}`;
    agg.set(key, (agg.get(key) || 0) + (e.weight || 1));
  }
  const cyNodes = nodes.map((n) => {
    const { w, h } = sizeOf(n.label);
    return { data: { id: n.id, parent: present.has(n.parent) ? n.parent : undefined, w, h } };
  });
  const cyEdges = [...agg.keys()].map((key, i) => {
    const [s, t] = key.split('|');
    return { data: { id: 'e' + i, source: s, target: t, crossModule: top[s] !== top[t] } };
  });
  return { nodes: cyNodes, edges: cyEdges };
}

// ---- parking pass (MIRROR of viewer.js parkEdgeless — held by the baseline guard test) --------------------
const PARK_GAP = 24;
function park(cy) {
  const groups = new Map();
  cy.nodes().forEach((n) => {
    if (n.isParent() || n.degree(false) > 0) return;
    const key = n.parent().empty() ? '' : n.parent().id();
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(n);
  });
  for (const [key, loose] of groups) {
    const siblings = key ? cy.getElementById(key).children() : cy.nodes().filter((n) => n.parent().empty());
    const looseIds = new Set(loose.map((n) => n.id()));
    const anchored = siblings.filter((n) => !looseIds.has(n.id()));
    const under = anchored.nonempty();
    const box = under ? anchored.boundingBox() : cy.collection(loose).boundingBox();
    const cellW = Math.max(...loose.map((n) => n.outerWidth())) + PARK_GAP;
    const cellH = Math.max(...loose.map((n) => n.outerHeight())) + PARK_GAP;
    const cols = Math.max(1, Math.min(loose.length, Math.round(box.w / cellW) || 1));
    const top = under ? box.y2 + PARK_GAP : box.y1;
    loose.forEach((n, i) => n.position({
      x: box.x1 + (i % cols) * cellW + cellW / 2,
      y: top + Math.floor(i / cols) * cellH + cellH / 2,
    }));
  }
}

// ---- metrics ---------------------------------------------------------------------------------------------
const area = (bb) => Math.max(0, bb.w) * Math.max(0, bb.h);

// Ideal-pack fill: grid-pack k boxes (their own w/h) into ~square, report Σarea / gridArea. This is the
// DERIVED reference a real box is compared against — a box below half of its own ideal is "under-filled",
// a ratio not a pixel constant.
function idealFill(children) {
  const n = children.length;
  if (n === 0) return 1;
  const cols = Math.max(1, Math.round(Math.sqrt(n)));
  const rows = Math.ceil(n / cols);
  const cw = Math.max(...children.map((c) => c.w)) + PARK_GAP;
  const ch = Math.max(...children.map((c) => c.h)) + PARK_GAP;
  const gridArea = cols * cw * rows * ch;
  const occupied = children.reduce((s, c) => s + c.w * c.h, 0);
  return occupied / gridArea;
}

const UNDERFILL_RATIO = 0.5;   // below half its own tidy-pack density = pathological (documented, derived ref)

function measure(cy) {
  // per-compound fill
  const compounds = [];
  cy.nodes(':parent').forEach((p) => {
    const kids = p.children();
    if (kids.length < 2) return;   // a 1-child box has nothing to compress
    const box = kids.boundingBox();
    const occupied = kids.reduce((s, k) => s + area(k.boundingBox()), 0);
    const fill = area(box) ? occupied / area(box) : 0;
    const ideal = idealFill(kids.map((k) => ({ w: k.outerWidth(), h: k.outerHeight() })));
    compounds.push({ id: p.id(), children: kids.length, fill, ratio: ideal ? fill / ideal : 0,
      boxW: Math.round(box.w), boxH: Math.round(box.h) });
  });
  compounds.sort((a, b) => a.ratio - b.ratio);
  const fills = compounds.map((c) => c.fill).sort((a, b) => a - b);
  const median = fills.length ? fills[fills.length >> 1] : null;
  const underfilled = compounds.filter((c) => c.ratio < UNDERFILL_RATIO);

  // crossings: straight center-to-center segments, edges not sharing an endpoint
  const pos = {};
  cy.nodes().forEach((n) => { pos[n.id()] = n.position(); });
  const segs = cy.edges().map((e) => ({ s: e.source().id(), t: e.target().id(),
    a: pos[e.source().id()], b: pos[e.target().id()] }));
  let crossings = 0;
  for (let i = 0; i < segs.length; i++) {
    for (let j = i + 1; j < segs.length; j++) {
      const A = segs[i], B = segs[j];
      if (A.s === B.s || A.s === B.t || A.t === B.s || A.t === B.t) continue;
      if (intersect(A.a, A.b, B.a, B.b)) crossings++;
    }
  }
  const bb = cy.elements().boundingBox();
  return {
    compounds: compounds.length, underfilled: underfilled.length,
    medianFill: median, crossings,
    canvas: { w: Math.round(bb.w), h: Math.round(bb.h), area: Math.round(area(bb)) },
    worst: compounds.slice(0, 5).map((c) => ({ id: c.id, fill: +c.fill.toFixed(3), ratio: +c.ratio.toFixed(3),
      children: c.children, box: `${c.boxW}x${c.boxH}` })),
  };
}

// segment intersection (proper crossing; collinear/touching ignored — good enough for a crossing count)
function ccw(a, b, c) { return (c.y - a.y) * (b.x - a.x) - (b.y - a.y) * (c.x - a.x); }
function intersect(a, b, c, d) {
  const d1 = ccw(a, b, c), d2 = ccw(a, b, d), d3 = ccw(c, d, a), d4 = ccw(c, d, b);
  return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
}

// ---- run a view ------------------------------------------------------------------------------------------
function layoutOnce(elements) {
  const cy = cytoscape({ headless: true, styleEnabled: true, elements,
    style: [{ selector: 'node', style: { width: 'data(w)', height: 'data(h)' } }] });
  cy.layout(LAYOUT).run();   // fcose animate:false runs synchronously
  return cy;
}

function positionsOf(cy) {
  const out = {};
  cy.nodes().forEach((n) => { const p = n.position(); out[n.id()] = [Math.round(p.x * 1e3), Math.round(p.y * 1e3)]; });
  return out;
}

function maxDelta(a, b) {
  let m = 0;
  for (const id of Object.keys(a)) {
    if (!b[id]) return Infinity;
    m = Math.max(m, Math.abs(a[id][0] - b[id][0]), Math.abs(a[id][1] - b[id][1]));
  }
  return m / 1e3;
}

const VIEWS = [
  { name: 'module/imports', depth: 'module', kinds: KIND_BANDS.imports },
  { name: 'class/structure', depth: 'class', kinds: KIND_BANDS.structure },
  { name: 'all/all', depth: 'all', kinds: [...KIND_BANDS.imports, ...KIND_BANDS.structure, ...KIND_BANDS.behaviour] },
];

function main() {
  const arg = process.argv[2];
  const fixture = path.join(HERE, '..', '..', 'tests', 'fixtures', 'archviz_graph.json');
  const graphPath = arg ? path.resolve(arg) : fixture;
  const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
  const report = { source: path.relative(process.cwd(), graphPath), views: {} };

  for (const view of VIEWS) {
    const elements = buildView(graph, view.depth, view.kinds);
    // determinism: two independent layouts of identical input
    const cy1 = layoutOnce(elements);
    const cy2 = layoutOnce(elements);
    const delta = maxDelta(positionsOf(cy1), positionsOf(cy2));
    park(cy1);
    const m = measure(cy1);
    report.views[view.name] = { nodes: elements.nodes.length, edges: elements.edges.length,
      deterministic: delta === 0, maxPositionDelta: delta, ...m };
    cy1.destroy(); cy2.destroy();
  }

  process.stdout.write(JSON.stringify(report, null, 2) + '\n');
  // human summary to stderr so `... > baseline.json` stays clean
  for (const [name, v] of Object.entries(report.views)) {
    process.stderr.write(
      `${name.padEnd(16)} n=${String(v.nodes).padStart(3)} e=${String(v.edges).padStart(3)}  ` +
      `compounds=${v.compounds} under-filled=${v.underfilled}  medFill=${v.medianFill == null ? '—' : v.medianFill.toFixed(2)}  ` +
      `crossings=${v.crossings}  canvas=${v.canvas.w}x${v.canvas.h}  ${v.deterministic ? 'deterministic' : 'NON-DET Δ=' + v.maxPositionDelta}\n`);
  }
  process.exit(0);
}

main();
