/* archmap interactive viewer — hydrates ./graph.json (emitted by `python -m devtools.archmap --json`).
 *
 * Manual collapse/aggregate engine: WE own the visible-representative logic, so a folded package pair is
 * exactly ONE counted arrow (the summed underlying imports), not a fan. Nodes come and go (add/remove) as
 * you fold/expand — a cytoscape compound with all children hidden renders zero-size, so a folded node must
 * be a genuinely childless leaf box. Layout = fcose (compound-aware) with a cose fallback.
 */
(async () => {
  cytoscape.use(window.cytoscapeFcose);
  const FCOSE = { name: 'fcose', quality: 'proof', animate: false, randomize: true, packComponents: true,
    nodeSeparation: 130, idealEdgeLength: 80, nestingFactor: 0.1, gravity: 0.25, numIter: 2500, tile: true };

  // graph.json carries TWO tiers now (bd 433.1): modules joined by imports, and beneath them classes joined
  // by the typed arrows an import decomposes into. This view renders the module/import tier it was built
  // for; the kind + role filters that surface the finer tier land with bd 433.3. Defaults keep an older
  // graph.json (no `level`/`kind`) working unchanged.
  const RAW = await (await fetch('./graph.json')).json();
  const GRAPH = {
    nodes: RAW.nodes.filter((n) => (n.level || 'module') === 'module'),
    edges: RAW.edges.filter((e) => (e.kind || 'import') === 'import'),
  };
  const PARENT = {}, KIDS = {}, DESC = {};
  for (const n of GRAPH.nodes) { PARENT[n.id] = n.parent; (KIDS[n.parent] = KIDS[n.parent] || []).push(n.id); DESC[n.id] = n.descendants; }

  // collapsed = package nodes whose descendants are folded away. Start at the top packages so the opening
  // view is the tier-1 overview: N boxes + one counted arrow per pair.
  const collapsed = new Set();
  function initCollapse() { collapsed.clear(); GRAPH.nodes.filter((n) => !n.parent && n.descendants > 0).forEach((n) => collapsed.add(n.id)); }
  initCollapse();

  function ancestors(id) { const a = []; let p = PARENT[id]; while (p) { a.push(p); p = PARENT[p]; } return a; }
  function hiddenBy(id) { return ancestors(id).some((a) => collapsed.has(a)); }
  function inV(id) { return !hiddenBy(id); }
  function rep(id) { let r = id; for (const a of [id, ...ancestors(id)]) if (collapsed.has(a)) r = a; return r; }

  const cy = cytoscape({
    container: document.getElementById('cy'),
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
      { selector: 'edge', style: {
        width: (e) => Math.min(1 + Math.sqrt(e.data('weight') || 1) * 1.1, 8), 'line-color': '#c8873b',
        'target-arrow-color': '#c8873b', 'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
        label: (e) => String(e.data('weight')), 'font-size': 11, color: '#f0c674',
        'text-background-color': '#05060a', 'text-background-opacity': 0.9, 'text-background-padding': 2, 'arrow-scale': 1 } },
      { selector: '.dim', style: { opacity: 0.16 } },                                  // focus spotlight: faded context
      { selector: '.lit', style: { opacity: 1 } },                                      // ...neighbourhood kept bright
      { selector: '.hl', style: { opacity: 1, 'border-width': 3, 'border-color': '#f0c674', 'line-color': '#f0c674', 'target-arrow-color': '#f0c674' } },
    ],
    layout: { name: 'grid' },
  });

  let focused = null;

  // Rebuild the whole view from `collapsed`. A node is present iff no ancestor is folded, so a folded node
  // is present but childless (a leaf box); its descendants are absent. Edges become ONE aggregated arrow per
  // visible pair (weight = summed imports; intra-box dropped). Rebuild from scratch each time — simple + exact.
  function refresh() {
    focused = null;
    cy.elements().remove();
    const nodes = GRAPH.nodes.filter((n) => inV(n.id));  // sorted dotted order -> parents precede children
    cy.add(nodes.map((n) => ({ group: 'nodes', data: {
      id: n.id, label: n.label, descendants: n.descendants,
      parent: (n.parent && inV(n.parent)) ? n.parent : undefined } })));
    nodes.forEach((n) => { if (collapsed.has(n.id)) cy.getElementById(n.id).addClass('collapsed'); });
    const agg = {};
    for (const e of GRAPH.edges) {
      const s = rep(e.source), t = rep(e.target);
      if (s === t) continue;
      const k = s + '|' + t;
      agg[k] = (agg[k] || 0) + (e.weight || 1);
    }
    cy.add(Object.entries(agg).map(([k, w]) => {
      const [s, t] = k.split('|');
      return { group: 'edges', data: { id: 'agg:' + k, source: s, target: t, weight: w } };
    }));
    relayout();
  }

  function relayout() {
    try { cy.layout(FCOSE).run(); }
    catch (e) { console.warn('fcose failed -> cose', e); cy.layout({ name: 'cose', animate: false }).run(); }
    cy.fit(cy.elements(), 40);
  }

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

  document.getElementById('expandAll').onclick = () => { collapsed.clear(); refresh(); };
  document.getElementById('collapseAll').onclick = () => { initCollapse(); refresh(); };
  document.getElementById('reset').onclick = () => { initCollapse(); refresh(); };
  document.getElementById('nodes').textContent = GRAPH.nodes.length;
  document.getElementById('edges').textContent = GRAPH.edges.length;

  refresh();
})();
