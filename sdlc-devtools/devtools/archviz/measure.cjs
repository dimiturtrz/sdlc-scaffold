/* Layout-measurement harness — turns "the layout makes no sense" into numbers that have to move.
 *
 * WHY this exists (bd 42b.1): the archviz auto-layout is force-directed (fcose), so "is it better?" was
 * being judged by eye, one screenshot at a time. This scores a candidate layout headlessly — no browser —
 * against the real graph, reporting the four things the requirements doc (docs/archviz_layout_requirements.md)
 * ranks: compression (per-compound fill), planarity (edge crossings), determinism (two runs identical), and
 * canvas size. Every layout change is scored HERE first; the browser look is the final confirmation, not the
 * debugging loop.
 *
 * It runs the SAME layout the viewer ships — the force pass AND the compaction — because both import it from
 * the one shared module, layout.js (bd 42b.2). So the numbers describe what the user actually sees, with no
 * copy to drift: retune the layout and both the page and this harness move together.
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

// The shipped layout, from its one home — the force pass and the deterministic compaction the viewer also
// uses (bd 42b.2). LAYOUT sets randomize:false, which fcose's spectral init makes byte-deterministic.
const { LAYOUT, compact } = require(path.join(HERE, 'layout.js'));

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
    return { data: { id: 'e' + i, source: s, target: t } };
  });
  return { nodes: cyNodes, edges: cyEdges };
}

// ---- metrics ---------------------------------------------------------------------------------------------
const area = (bb) => Math.max(0, bb.w) * Math.max(0, bb.h);
const GRID_GAP = 24;   // the gutter the ideal-pack reference assumes — matches layout.js's compaction GAP

// Ideal-pack fill: grid-pack k boxes (their own w/h) into ~square, report Σarea / gridArea. This is the
// DERIVED reference a real box is compared against — a box below half of its own ideal is "under-filled",
// a ratio not a pixel constant.
function idealFill(children) {
  const n = children.length;
  if (n === 0) return 1;
  const cols = Math.max(1, Math.round(Math.sqrt(n)));
  const rows = Math.ceil(n / cols);
  const cw = Math.max(...children.map((c) => c.w)) + GRID_GAP;
  const ch = Math.max(...children.map((c) => c.h)) + GRID_GAP;
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
function layoutOnce(elements, layout = LAYOUT) {
  const cy = cytoscape({ headless: true, styleEnabled: true, elements,
    style: [{ selector: 'node', style: { width: 'data(w)', height: 'data(h)' } }] });
  cy.layout(layout).run();   // fcose animate:false runs synchronously
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

// Score one graph across all views. `layout`/`settle` are injectable so an experiment can A/B a candidate
// engine or compaction pass without forking the harness (Stage A, bd 42b.2); the defaults ARE the shipped
// pipeline, which is what the committed baseline records.
function scoreGraph(graph, { layout = LAYOUT, settle = compact } = {}) {
  const report = { views: {} };
  for (const view of VIEWS) {
    const elements = buildView(graph, view.depth, view.kinds);
    const cy1 = layoutOnce(elements, layout);
    const cy2 = layoutOnce(elements, layout);   // determinism: two independent layouts of identical input
    const delta = maxDelta(positionsOf(cy1), positionsOf(cy2));
    settle(cy1);
    report.views[view.name] = { nodes: elements.nodes.length, edges: elements.edges.length,
      deterministic: delta === 0, maxPositionDelta: delta, ...measure(cy1) };
    cy1.destroy(); cy2.destroy();
  }
  return report;
}

function summarise(report) {
  return Object.entries(report.views).map(([name, v]) =>
    `${name.padEnd(16)} n=${String(v.nodes).padStart(3)} e=${String(v.edges).padStart(3)}  ` +
    `compounds=${v.compounds} under-filled=${v.underfilled}  medFill=${v.medianFill == null ? '—' : v.medianFill.toFixed(2)}  ` +
    `crossings=${v.crossings}  canvas=${v.canvas.w}x${v.canvas.h}  ${v.deterministic ? 'deterministic' : 'NON-DET Δ=' + v.maxPositionDelta}`
  ).join('\n');
}

function main() {
  const arg = process.argv[2];
  const fixture = path.join(HERE, '..', '..', 'tests', 'fixtures', 'archviz_graph.json');
  const graphPath = arg ? path.resolve(arg) : fixture;
  const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));
  const report = { source: path.relative(process.cwd(), graphPath), ...scoreGraph(graph) };
  process.stderr.write(summarise(report) + '\n');   // summary to stderr so `... > baseline.json` stays clean
  // Headless cytoscape leaves a handle open, so the process will not exit on its own; but exiting before a
  // piped stdout flushes truncates the JSON. Write with a completion callback, then exit.
  process.stdout.write(JSON.stringify(report, null, 2) + '\n', () => process.exit(0));
}

module.exports = { buildView, layoutOnce, compact, measure, scoreGraph, summarise, LAYOUT, KIND_BANDS, VIEWS };

if (require.main === module) main();
