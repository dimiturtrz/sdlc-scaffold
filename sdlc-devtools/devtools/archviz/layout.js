/* The layout: ONE home for how the graph is placed, shared by the interactive viewer (viewer.js) and the
 * headless measurement harness (measure.cjs). It loads as a plain <script> in the page (exposing
 * `window.archvizLayout`) and as a CommonJS require in Node — no bundler, no DOM, cytoscape's collection API
 * only, so the same code runs in both. Sharing it is what lets the harness score the layout the page actually
 * renders instead of a copy that drifts (bd 42b.2).
 *
 * TWO PARTS:
 *   LAYOUT   — the fcose force pass. It gives a good GLOBAL arrangement (which module sits near which, a
 *              class's call-flow) but cannot guarantee a tight compound box: sized to bound ALL its children,
 *              one child dragged out by a cross-boundary edge blows the box open, empty. That was fought with
 *              tuned force constants (gravityCompound, a weakened cross-module edge spring) — whack-a-mole
 *              magic numbers that traded one axis for another and never actually guaranteed compression.
 *   compact  — a deterministic post-pass that GUARANTEES compression, so the force constants no longer have
 *              to. fcose is left at its own defaults for the knobs the tuning used to override; `compact`
 *              does the shrink-wrapping structurally. Two passes, escalating only as far as a box needs:
 *
 *                1. PARK: a child whose edges all leave its box (zero in-box degree) has a meaningless
 *                   position inside it — physics placed it by a spring pulling OUT. Grid those under the
 *                   connected cluster. This alone recaptures the classic flung-outlier.
 *                2. TIDY: any compound STILL under-filled — packed below half the density a tidy grid of the
 *                   same children would reach (the harness's own `ratio < 0.5`, a measured definition, not a
 *                   tuned constant) — has its children repacked into a grid in fcose READING ORDER (row-major
 *                   by their solved position), so spatial adjacency the force pass found is preserved while
 *                   the empty gaps are removed. Well-filled boxes (a real, taut call cluster) are left
 *                   untouched, so the arrangement that reads as architecture survives where it exists.
 *
 * DETERMINISM: fcose's spectral init is deterministic, so `randomize:false` gives byte-identical runs; the
 * viewer must therefore NOT reseed. `compact` is pure geometry over the solved positions, so the whole
 * pipeline is a function of graph.json alone (req #3).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.archvizLayout = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  const LAYOUT = {
    name: 'fcose', quality: 'proof', animate: false, randomize: false,
    // nodeSeparation/idealEdgeLength/gravity are fcose's scale knobs; nestingFactor scales an edge's ideal
    // length by how many compound boundaries it crosses (the deeper tiers need more room), which is why a
    // cross-module method edge does not collapse two whole module boxes onto each other. These set the force
    // pass's SPACING; `compact` owns COMPRESSION, so the two interim knobs that used to (gravityCompound and a
    // per-edge edgeElasticity split) are gone — fcose keeps its own defaults for them.
    nodeSeparation: 130, idealEdgeLength: 80, nestingFactor: 0.8, gravity: 0.25, numIter: 2500,
    // Nodes are sized to their label, and a compound draws its title above its children; without this fcose
    // measures raw boxes and packs siblings into each other's labels.
    nodeDimensionsIncludeLabels: true,
  };

  const GAP = 10;   // the visual gutter between packed boxes — a minimal breathing margin, not a tuning knob
  const VIEWPORT_ASPECT = 1.6;   // target width:height for a shelf pack — a plain landscape default (16:10)

  const parentId = (n) => (n.parent().empty() ? '' : n.parent().id());

  // edges to a SIBLING (same parent). Zero => every edge leaves the box, so the node's in-box position is an
  // artifact of an outward spring and it can be gridded without scrambling any internal structure.
  function inBoxDegree(n) {
    const pid = parentId(n);
    return n.connectedEdges().filter((e) => {
      const other = e.source().id() === n.id() ? e.target() : e.source();
      return parentId(other) === pid;
    }).length;
  }

  // grid `loose` under the connected `anchored` cluster of the same compound (structure first, companions
  // beneath); with nothing connected to anchor to, tidy them where they already are.
  function gridUnder(cy, key, loose) {
    const siblings = key ? cy.getElementById(key).children() : cy.nodes().filter((n) => n.parent().empty());
    const looseIds = new Set(loose.map((n) => n.id()));
    const anchored = siblings.filter((n) => !looseIds.has(n.id()));
    const under = anchored.nonempty();
    const box = under ? anchored.boundingBox() : cy.collection(loose).boundingBox();
    const cellW = Math.max(...loose.map((n) => n.boundingBox().w)) + GAP;
    const cellH = Math.max(...loose.map((n) => n.boundingBox().h)) + GAP;
    const cols = Math.max(1, Math.min(loose.length, Math.round(box.w / cellW) || 1));
    const top = under ? box.y2 + GAP : box.y1;
    loose.forEach((n, i) => n.position({
      x: box.x1 + (i % cols) * cellW + cellW / 2,
      y: top + Math.floor(i / cols) * cellH + cellH / 2,
    }));
  }

  // pack a compound's children in reading order (their solved position, grouped into rows by y then left to
  // right) so the force pass's spatial adjacency is kept while the gaps are squeezed out. A SHELF pack, not a
  // uniform grid: each box takes its OWN width and a row wraps at a width budget, so a narrow method next to a
  // wide one does not inherit the wide one's column. The uniform grid was the real "drawn out" — cells sized
  // to the widest child left every narrow child ringed with empty space (a 13-method class came out ~26%
  // full). The budget is sqrt(total footprint), which lands roughly square; rows are as tall as their tallest
  // box, so variable sizes nest instead of quantising to a cell.
  //
  // A child may itself be a COMPOUND (a class box inside a module, a subpackage inside a package). A compound's
  // geometry is DERIVED from its children, so its `position()` is unreliable to read or write — moving one
  // means translating its whole subtree by a delta, and its CENTRE must be read from its bounding box, not its
  // position (they disagree, badly, once children have been moved). Reading centre/size uniformly from the
  // bounding box is correct for a leaf too, so one path serves both. Without this the higher levels never
  // compacted: a class flung to the far corner of its module (all its edges leaving the box) stayed there,
  // holding the module box open around a sea of empty space — exactly the untidied box the owner saw.
  const centre = (n) => { const b = n.boundingBox(); return { x: (b.x1 + b.x2) / 2, y: (b.y1 + b.y2) / 2 }; };

  function place(node, x, y) {
    if (!node.isParent()) { node.position({ x, y }); return; }
    const c = centre(node);
    const dx = x - c.x, dy = y - c.y;
    node.descendants().forEach((d) => {
      if (d.isParent()) return;                      // parents follow their leaves; move only the leaves
      const p = d.position();
      d.position({ x: p.x + dx, y: p.y + dy });
    });
  }
  function packInReadingOrder(kids) {
    const arr = kids.toArray().slice().sort((a, b) => {
      const pa = centre(a), pb = centre(b);
      const sameRow = Math.abs(pa.y - pb.y) <= (a.boundingBox().h + b.boundingBox().h) / 2;
      return sameRow ? pa.x - pb.x : pa.y - pb.y;
    });
    const cell = (n) => ({ w: n.boundingBox().w + GAP, h: n.boundingBox().h + GAP });
    // Row width budget = sqrt(total footprint) targets a square block; scaling the footprint by the viewport's
    // aspect before the sqrt makes the block land at THAT aspect instead — so a shelf pack fills a landscape
    // screen rather than stacking into a portrait column. VIEWPORT_ASPECT is a plain landscape default (16:10).
    const budget = Math.sqrt(arr.reduce((s, n) => { const c = cell(n); return s + c.w * c.h; }, 0) * VIEWPORT_ASPECT);
    const bb = kids.boundingBox();
    let x = bb.x1, y = bb.y1, rowH = 0;
    for (const n of arr) {
      const c = cell(n);
      if (x - bb.x1 + c.w > budget && x > bb.x1) { x = bb.x1; y += rowH; rowH = 0; }  // wrap the shelf
      place(n, x + c.w / 2, y + c.h / 2);
      x += c.w;
      rowH = Math.max(rowH, c.h);
    }
  }

  // fill a compound reaches vs the fill a tidy square grid-pack of the SAME children would. Both numerator and
  // denominator use the children's OWN sizes, so what the trigger compares against is derived from the graph,
  // not a pixel constant — only the tolerance it is compared to (SPREAD_TOLERANCE) is a policy.
  function fillRatio(kids) {
    const arr = kids.toArray();
    const box = kids.boundingBox();
    const occupied = arr.reduce((s, k) => { const b = k.boundingBox(); return s + b.w * b.h; }, 0);
    const fill = box.w * box.h ? occupied / (box.w * box.h) : 0;
    const cols = Math.max(1, Math.round(Math.sqrt(arr.length)));
    const rows = Math.ceil(arr.length / cols);
    const cw = Math.max(...arr.map((c) => c.boundingBox().w)) + GAP;
    const ch = Math.max(...arr.map((c) => c.boundingBox().h)) + GAP;
    const ideal = occupied / (cols * cw * rows * ch);
    return ideal ? fill / ideal : 0;
  }

  // Tidy a box unless it is ALREADY within 80% of a tidy pack's density. This is the compaction's tolerance
  // for fcose spread, and it is deliberately tight: the deep tiers (public/all) read as "drawn out" at the
  // looser 0.5, because a box packed at 0.5–0.8 of ideal still carries visible empty gaps. The ceiling is 0.8
  // rather than 1.0 because re-gridding a box that is ALREADY near-tidy only churns its arrangement without
  // saving space (measured: a 1.0 trigger came out slightly larger). This is a spread POLICY, distinct from
  // the harness metric's 0.5 "pathologically empty" floor — the metric reports, this acts.
  const SPREAD_TOLERANCE = 0.8;

  // The deterministic compression pass. Run AFTER fcose settles (positions are what it reads); pure geometry,
  // no viewport side effects (the viewer fits the camera itself).
  function compact(cy) {
    // 1. park the outward-only children of every compound
    const groups = new Map();
    cy.nodes().forEach((n) => {
      if (n.isParent() || inBoxDegree(n) > 0) return;
      const pid = parentId(n);
      if (!groups.has(pid)) groups.set(pid, []);
      groups.get(pid).push(n);
    });
    for (const [key, loose] of groups) gridUnder(cy, key, loose);

    // 2. tidy every compound looser than the tolerance — deepest first, so a parent repacks after its children
    // have their final sizes.
    const parents = cy.nodes(':parent').toArray().sort((a, b) => b.id().length - a.id().length);
    for (const p of parents) {
      const kids = p.children();
      if (kids.length >= 2 && fillRatio(kids) < SPREAD_TOLERANCE) packInReadingOrder(kids);
    }
  }

  return { LAYOUT, compact };
});
