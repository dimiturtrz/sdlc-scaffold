/* archmap interactive viewer — hydrates ./graph.json (emitted by `python -m devtools.archmap`).
 *
 * Manual collapse/aggregate engine: WE own the visible-representative logic, so a folded package pair is
 * exactly ONE counted arrow (the summed underlying imports), not a fan. Nodes come and go (add/remove) as
 * you fold/expand — a cytoscape compound with all children hidden renders zero-size, so a folded node must
 * be a genuinely childless leaf box. Layout = fcose (compound-aware) with a cose fallback.
 *
 * graph.json carries TWO tiers (bd 433.1): modules joined by imports, and beneath them classes joined by
 * the typed arrows an import decomposes into. The filter bar (bd 433.2/433.3) picks the subset to draw.
 * Line STYLE carries the meaning split — SOLID = what a class KNOWS (import/inherits/holds), DASHED = what
 * it DOES (calls/construct) — so the reading survives greyscale and colour-blindness rather than relying on
 * hue alone. Default state = modules + imports, i.e. exactly the view before the class tier existed.
 */
(async () => {
  cytoscape.use(window.cytoscapeFcose);
  const FCOSE = { name: 'fcose', quality: 'proof', animate: false, randomize: true, packComponents: true,
    nodeSeparation: 130, idealEdgeLength: 80, nestingFactor: 0.1, gravity: 0.25, numIter: 2500, tile: true };

  const KINDS = ['import', 'inherits', 'holds', 'references', 'calls', 'construct'];
  const RAW = await (await fetch('./graph.json')).json();
  const $ = (id) => document.getElementById(id);

  // ---- filter state -> the graph actually drawn -------------------------------------------------------
  function readFilters() {
    return {
      classes: $('tier-class').checked,
      hideSatellites: $('hide-satellites').checked,
      kinds: new Set(KINDS.filter((k) => $('kind-' + k).checked)),
    };
  }

  let GRAPH = { nodes: [], edges: [] }, PARENT = {}, KIDS = {}, DESC = {};

  function rebuild() {
    const f = readFilters();
    const nodes = RAW.nodes.filter((n) => {
      if ((n.level || 'module') === 'module') return true;
      return f.classes && !(f.hideSatellites && n.role === 'satellite');
    });
    const present = new Set(nodes.map((n) => n.id));
    // an edge is drawn only when BOTH endpoints survive the tier filter — otherwise a class-level arrow
    // would dangle off a hidden node
    const edges = RAW.edges.filter(
      (e) => f.kinds.has(e.kind || 'import') && present.has(e.source) && present.has(e.target));
    GRAPH = { nodes, edges };
    PARENT = {}; KIDS = {}; DESC = {};
    for (const n of nodes) {
      const parent = present.has(n.parent) ? n.parent : null;
      PARENT[n.id] = parent;
      (KIDS[parent] = KIDS[parent] || []).push(n.id);
    }
    // descendants recomputed from what is PRESENT, not from the file: with classes shown a module gains
    // children, and a stale count would mislabel the folded badge and break foldability
    for (const n of nodes) DESC[n.id] = nodes.filter((o) => o.id.startsWith(n.id + '.')).length;
    $('nodes').textContent = nodes.length;
    $('edges').textContent = edges.length;
  }

  const collapsed = new Set();
  function initCollapse() {
    collapsed.clear();
    GRAPH.nodes.filter((n) => !PARENT[n.id] && DESC[n.id] > 0).forEach((n) => collapsed.add(n.id));
  }

  function ancestors(id) { const a = []; let p = PARENT[id]; while (p) { a.push(p); p = PARENT[p]; } return a; }
  function hiddenBy(id) { return ancestors(id).some((a) => collapsed.has(a)); }
  function inV(id) { return !hiddenBy(id); }
  function rep(id) { let r = id; for (const a of [id, ...ancestors(id)]) if (collapsed.has(a)) r = a; return r; }

  const EDGE = (color, style, arrow) => ({
    'line-color': color, 'target-arrow-color': color, 'line-style': style, 'target-arrow-shape': arrow });

  const cy = cytoscape({
    container: $('cy'),
    wheelSensitivity: 0.2,
    elements: [],
    style: [
      { selector: 'node', style: {
        label: 'data(label)', 'font-size': 11, 'text-valign': 'center', color: '#e6e6e6',
        'background-color': '#3b5b7a', 'border-width': 1, 'border-color': '#6f9fd0', shape: 'round-rectangle',
        width: 'label', padding: 6, 'text-wrap': 'wrap' } },
      { selector: 'node:parent', style: {
        'background-color': '#1c2a3a', 'background-opacity': 0.5, 'border-color': '#4a6a8a',
        'text-valign': 'top', 'font-size': 13, color: '#9fc4ef', padding: 10 } },
      { selector: 'node.collapsed', style: {
        'background-color': '#2e4a66', 'background-opacity': 1, 'text-valign': 'center', 'font-size': 12,
        color: '#dce8f5', label: (e) => e.data('label') + '  (' + e.data('descendants') + ')' } },
      // a CLASS reads as an object (ellipse), a module as a box; a SATELLITE (its error / config / local
      // specialisation) is muted so the primaries carry the skeleton
      { selector: 'node[level="class"]', style: {
        shape: 'ellipse', 'background-color': '#25506b', 'border-color': '#5fae7f', 'font-size': 10 } },
      { selector: 'node[role="satellite"]', style: {
        'background-opacity': 0.45, 'border-style': 'dashed', color: '#9fb4c8', 'font-size': 9 } },
      { selector: 'edge', style: {
        width: (e) => Math.min(1 + Math.sqrt(e.data('weight') || 1) * 1.1, 8), 'curve-style': 'bezier',
        // only the import tier is a COUNT worth printing; a typed arrow is a fact, and labelling every one
        // "1" is noise
        label: (e) => (e.data('kind') === 'import' ? String(e.data('weight')) : ''),
        'font-size': 11, color: '#f0c674', 'text-background-color': '#05060a',
        'text-background-opacity': 0.9, 'text-background-padding': 2, 'arrow-scale': 1,
        ...EDGE('#5b6b7a', 'solid', 'triangle') } },
      // SOLID = structural (what the class knows) · DASHED = behavioural (what it does).
      // Arrowheads borrow UML: hollow triangle = generalization, diamond = composition, plain = dependency.
      { selector: 'edge[kind="inherits"]', style: EDGE('#6f9fd0', 'solid', 'triangle-tee') },
      { selector: 'edge[kind="holds"]', style: EDGE('#5fae7f', 'solid', 'diamond') },
      { selector: 'edge[kind="references"]', style: EDGE('#7d8590', 'dotted', 'triangle') },
      { selector: 'edge[kind="calls"]', style: EDGE('#c8873b', 'dashed', 'triangle') },
      { selector: 'edge[kind="construct"]', style: EDGE('#b06ec0', 'dashed', 'circle-triangle') },
      { selector: '.dim', style: { opacity: 0.16 } },                                  // focus spotlight: faded context
      { selector: '.lit', style: { opacity: 1 } },                                      // ...neighbourhood kept bright
      { selector: '.hl', style: { opacity: 1, 'border-width': 3, 'border-color': '#f0c674', 'line-color': '#f0c674', 'target-arrow-color': '#f0c674' } },
    ],
    layout: { name: 'grid' },
  });

  let focused = null;

  // Rebuild the whole view from `collapsed`. A node is present iff no ancestor is folded, so a folded node
  // is present but childless (a leaf box); its descendants are absent. Edges aggregate per visible pair AND
  // KIND — folding must not merge a `calls` into an `import`, or the colour would lie.
  function refresh() {
    focused = null;
    cy.elements().remove();
    const nodes = GRAPH.nodes.filter((n) => inV(n.id));  // sorted dotted order -> parents precede children
    cy.add(nodes.map((n) => ({ group: 'nodes', data: {
      id: n.id, label: n.label, descendants: DESC[n.id], level: n.level || 'module', role: n.role || null,
      parent: (PARENT[n.id] && inV(PARENT[n.id])) ? PARENT[n.id] : undefined } })));
    nodes.forEach((n) => { if (collapsed.has(n.id)) cy.getElementById(n.id).addClass('collapsed'); });
    const agg = {};
    for (const e of GRAPH.edges) {
      const s = rep(e.source), t = rep(e.target);
      if (s === t) continue;
      const key = s + '|' + t + '|' + (e.kind || 'import');
      agg[key] = (agg[key] || 0) + (e.weight || 1);
    }
    cy.add(Object.entries(agg).map(([key, w]) => {
      const [s, t, kind] = key.split('|');
      return { group: 'edges', data: { id: 'agg:' + key, source: s, target: t, weight: w, kind } };
    }));
    relayout();
  }

  function relayout() {
    try { cy.layout(FCOSE).run(); }
    catch (e) { console.warn('fcose failed -> cose', e); cy.layout({ name: 'cose', animate: false }).run(); }
    cy.fit(cy.elements(), 40);
  }

  function reload() { rebuild(); initCollapse(); refresh(); }

  // focus = SPOTLIGHT: the node + its dependency neighbours + connecting edges (+ ancestor boxes) stay lit;
  // everything else DIMS but remains on screen (context is kept, not hidden), and we zoom to the cluster.
  function focus(n) {
    const hood = n.closedNeighborhood().union(n.ancestors());
    cy.elements().removeClass('hl').addClass('dim');
    hood.removeClass('dim').addClass('lit');
    n.removeClass('dim').addClass('hl');
    cy.fit(hood, 60);
    focused = n;
  }
  function clearFocus() { cy.elements().removeClass('dim lit hl'); cy.fit(cy.elements(), 40); focused = null; }

  // LEFT-click = navigate the hierarchy: drill a folded box one level, or fold an open package. A leaf has
  // nowhere to drill, so it's a no-op. RIGHT-click (below) = focus, on ANY node.
  cy.on('tap', 'node', (evt) => {
    const id = evt.target.id();
    if (collapsed.has(id)) {                     // folded box -> drill ONE level (re-fold its child packages)
      collapsed.delete(id);
      (KIDS[id] || []).filter((c) => DESC[c] > 0).forEach((c) => collapsed.add(c));
      refresh();
    } else if (DESC[id] > 0) {                   // open package -> fold it
      collapsed.add(id);
      refresh();
    }
  });
  // RIGHT-click any node = focus/unfocus (isolate its aggregated dependency neighbourhood — packages too).
  cy.on('cxttap', 'node', (evt) => { const n = evt.target; if (focused === n) clearFocus(); else focus(n); });
  cy.on('tap', (evt) => { if (evt.target === cy && focused) clearFocus(); });
  // suppress the browser context menu so right-click is ours
  cy.container().addEventListener('contextmenu', (e) => e.preventDefault());

  $('expandAll').onclick = () => { collapsed.clear(); refresh(); };
  $('collapseAll').onclick = () => { initCollapse(); refresh(); };
  $('reset').onclick = () => { reload(); };

  // presets: the three questions people actually arrive with — "what depends on what" (the coarse import
  // backdrop), "how is it shaped" (structure), "what does it do" (behaviour).
  const PRESETS = {
    'preset-imports': { classes: false, kinds: ['import'] },
    'preset-structure': { classes: true, kinds: ['inherits', 'holds'] },
    'preset-behaviour': { classes: true, kinds: ['calls', 'construct'] },
  };
  for (const [id, preset] of Object.entries(PRESETS)) {
    $(id).onclick = () => {
      $('tier-class').checked = preset.classes;
      KINDS.forEach((k) => { $('kind-' + k).checked = preset.kinds.includes(k); });
      reload();
    };
  }
  for (const id of ['tier-class', 'hide-satellites', ...KINDS.map((k) => 'kind-' + k)]) {
    $(id).addEventListener('change', reload);
  }

  reload();
})();
