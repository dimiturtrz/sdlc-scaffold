/* archmap interactive viewer — hydrates ./graph.json (emitted by `python -m devtools.archmap`).
 *
 * Manual collapse/aggregate engine: WE own the visible-representative logic, so a folded package pair is
 * exactly ONE counted arrow (the summed underlying imports), not a fan. Nodes come and go (add/remove) as
 * you fold/expand — a cytoscape compound with all children hidden renders zero-size, so a folded node must
 * be a genuinely childless leaf box. Layout = fcose (compound-aware) with a cose fallback.
 *
 * graph.json carries THREE tiers: modules joined by imports, beneath them classes joined by the STRUCTURAL
 * arrows an import decomposes into (bd 433.1), and beneath those the methods, where the BEHAVIOURAL arrows
 * terminate (bd 433.4 / f1u.2 — a call lands on the method it invokes).
 *
 * Every arrow is emitted ONCE, at its finest depth, and rolls UP to whichever ancestor is on screen. So the
 * class view is a projection of the method view rather than a second copy of it, exactly as the import tier
 * is a projection of both.
 *
 * The controls are the MODEL, not one boolean per implementation detail. Both axes are ordinal:
 *   DEPTH   walks the containment tree      module > class > public > all   (each stop needs the one above)
 *   ARROWS  walks the decomposition         imports > structure > behaviour
 * Line STYLE carries the same knows/does split as ARROWS — SOLID = what a class KNOWS (import/inherits/
 * holds/references), DASHED = what it DOES (calls/construct) — so the reading survives greyscale and
 * colour-blindness rather than relying on hue alone. The exact kind set stays reachable behind `per-kind`:
 * it reads the RESOLVER, which is an author's question, not the reviewer's.
 */
(async () => {
  cytoscape.use(window.cytoscapeFcose);
  const FCOSE = { name: 'fcose', quality: 'proof', animate: false, randomize: true, packComponents: true,
    nodeSeparation: 130, idealEdgeLength: 80, nestingFactor: 0.1, gravity: 0.25, numIter: 2500, tile: true };

  // ONE table owns every per-kind fact: how the arrow is drawn, and which band it belongs to. The cytoscape
  // stylesheet, the legend swatches and the band membership are all derived from it, so a colour cannot
  // drift between the graph and its key, and a kind cannot exist outside a band.
  // Edge direction is always DEPENDS-ON: source needs target. `tail` is the mark at the SOURCE end, which
  // is where UML puts an ownership diamond — the whole, not the part. Without it `holds` would draw the
  // diamond on the field's type and read backwards to anyone who knows the notation.
  const STYLE = {
    import:     { color: '#5b6b7a', line: 'solid',  head: 'triangle',        band: 'imports' },
    inherits:   { color: '#6f9fd0', line: 'solid',  head: 'triangle-tee',    band: 'structure' },
    holds:      { color: '#5fae7f', line: 'solid',  head: 'triangle', tail: 'diamond', band: 'structure' },
    references: { color: '#7d8590', line: 'dotted', head: 'triangle',        band: 'structure' },
    calls:      { color: '#c8873b', line: 'dashed', head: 'triangle',        band: 'behaviour' },
    construct:  { color: '#b06ec0', line: 'dashed', head: 'circle-triangle', band: 'behaviour' },
  };
  const KINDS = Object.keys(STYLE);
  const BANDS = {};
  for (const [kind, s] of Object.entries(STYLE)) (BANDS[s.band] = BANDS[s.band] || []).push(kind);

  // A band label is a word the reviewer has to be taught once; the caption is where it gets taught.
  const CAPTION = {
    imports: 'what needs what — the file-level roll-up every finer arrow decomposes from',
    structure: 'what a class KNOWS — the shape it is built from, drawn solid',
    behaviour: 'what a class DOES — the traffic it generates at runtime, drawn dashed',
  };

  // DEPTH stops are ORDINAL, and `public` / `all` are two stops on the same METHOD tier rather than a new
  // axis: public methods are a strict subset of all methods, so walking one stop further only ever adds
  // nodes. That is what keeps this a single scale instead of a tier control plus a private-methods
  // checkbox — `public` shows a class's SURFACE, `all` opens its internals (where a public method calling
  // its own private helper is the structure worth seeing).
  const DEPTHS = ['module', 'class', 'public', 'all'];
  const LEVELS = ['module', 'class', 'method'];   // the node tiers graph.json actually carries
  const PLURAL = { module: 'modules', class: 'classes', method: 'methods' };
  const isPrivate = (n) => n.label.startsWith('_');
  const RAW = await (await fetch('./graph.json')).json();
  const $ = (id) => document.getElementById(id);

  // The swatch IS the edge: same colour, same dash, same arrowhead, so the key reads as a sample of the
  // picture rather than a second thing to memorise.
  // Every coordinate below is DERIVED from the box and the arrowhead size — the swatch stays correct at any
  // scale, and the dash patterns are expressed in stroke widths (which is what makes a dash read as dashed)
  // rather than as pixel counts that only happen to look right at this one size.
  // The box is a UNITLESS grid, not pixels: CSS sizes the swatch in `em` so it tracks the type, and every
  // coordinate here is a FRACTION of the grid, so the drawing is resolution- and zoom-independent.
  const BOX = { w: 100, h: 40 };
  const STROKE = 0.05 * BOX.h;
  const PAD = 0.02 * BOX.w;
  const HEAD_LEN = 0.26 * BOX.w;             // the wedge takes about a quarter of the run
  const HEAD_HALF = 0.28 * BOX.h;            // ...and is a little over half as tall as it is long (UML)
  const MID = BOX.h / 2;
  const TIP = BOX.w - PAD;
  const BACK = TIP - HEAD_LEN;               // where the head starts, i.e. where the line must stop
  const DASH = {
    solid: '',
    dashed: `${STROKE * 2},${STROKE * 1.5}`,
    dotted: `${STROKE / 2},${STROKE * 1.5}`,
  };

  const wedge = (x) => `<path d="M${x},${MID - HEAD_HALF} L${x + HEAD_LEN},${MID} L${x},${MID + HEAD_HALF} Z"/>`;
  const HEAD = {
    'triangle': () => wedge(BACK),
    // UML generalization: the bar that closes off the wedge
    'triangle-tee': () => wedge(BACK)
      + `<rect x="${BACK - STROKE * 2}" y="${MID - HEAD_HALF - STROKE / 2}"`
      + ` width="${STROKE}" height="${HEAD_HALF * 2 + STROKE}"/>`,
    // UML composition: the whole owns the part
    'diamond': () => `<path d="M${BACK},${MID} L${BACK + HEAD_LEN / 2},${MID - HEAD_HALF}`
      + ` L${TIP},${MID} L${BACK + HEAD_LEN / 2},${MID + HEAD_HALF} Z"/>`,
    // construct = a call that also instantiates, so it is the call wedge plus the object it makes
    'circle-triangle': () => wedge(BACK)
      + `<circle cx="${BACK - HEAD_HALF}" cy="${MID}" r="${HEAD_HALF / 2}"/>`,
  };

  // the mark at the SOURCE end — an ownership diamond sits on the holder, mirroring the head geometry
  const TAIL = {
    'diamond': () => `<path d="M${PAD},${MID} L${PAD + HEAD_LEN / 2},${MID - HEAD_HALF}`
      + ` L${PAD + HEAD_LEN},${MID} L${PAD + HEAD_LEN / 2},${MID + HEAD_HALF} Z"/>`,
  };

  // no width/height attributes: CSS owns the size, the viewBox owns the proportions
  function swatch(kind) {
    const s = STYLE[kind];
    const start = s.tail ? PAD + HEAD_LEN : PAD;
    return `<svg class="sw" viewBox="0 0 ${BOX.w} ${BOX.h}" preserveAspectRatio="xMidYMid meet"
      fill="${s.color}" stroke="${s.color}" aria-hidden="true"><line x1="${start}" y1="${MID}"
      x2="${BACK}" y2="${MID}" stroke-width="${STROKE}" stroke-dasharray="${DASH[s.line]}"/>${
      s.tail ? TAIL[s.tail]() : ''}${HEAD[s.head]()}</svg>`;
  }

  // ---- control state ----------------------------------------------------------------------------------
  // `band` is null exactly when the per-kind panel owns the kind set (an arbitrary set has no band).
  let depth = 'module', band = 'imports';

  function kinds() {
    return new Set(band ? BANDS[band] : KINDS.filter((k) => $('kind-' + k).checked));
  }
  function readFilters() {
    const d = DEPTHS.indexOf(depth);
    return { classes: d >= 1, methods: d >= 2, privates: d >= 3,
      hideSatellites: $('hide-satellites').checked, kinds: kinds() };
  }
  function paintSeg(id, value) {
    for (const b of $(id).children) b.classList.toggle('on', b.dataset.v === value);
  }

  let GRAPH = { nodes: [], edges: [] }, PARENT = {}, KIDS = {}, DESC = {};

  function rebuild() {
    const f = readFilters();
    const nodes = RAW.nodes.filter((n) => {
      const level = n.level || 'module';
      if (level === 'module') return true;
      // a METHOD hangs off a class, so it needs that class present — showing methods with the class tier
      // off would orphan them. Depth being ordinal makes that structural instead of a checkbox pairing.
      if (level === 'method') return f.classes && f.methods && (f.privates || !isPrivate(n));
      return f.classes && !(f.hideSatellites && n.role === 'satellite');
    });
    const present = new Set(nodes.map((n) => n.id));
    // An arrow ROLLS UP to whichever ancestor is on screen rather than vanishing with its endpoint. A
    // `calls` edge is emitted once, at its finest depth (method -> method), so dropping it whenever a
    // method is filtered out would make the behaviour bands empty at class depth — and emitting a second,
    // coarser copy would draw the same fact twice once methods are shown. Climbing is the same fold the
    // import tier already rests on: project an arrow's endpoints upward and you land on the coarser edge.
    const climb = (id) => {
      let at = id;
      while (at && !present.has(at)) at = at.includes('.') ? at.slice(0, at.lastIndexOf('.')) : null;
      return at;
    };
    // an id CONTAINS another when it is a dotted prefix of it — `pkg.mod.A` contains `pkg.mod.A.go`
    const contains = (outer, inner) => inner.startsWith(outer + '.');
    const edges = RAW.edges
      .filter((e) => f.kinds.has(e.kind || 'import'))
      .map((e) => ({ ...e, source: climb(e.source), target: climb(e.target),
        // a GENUINE self-arrow (a class holding its own type) is a real shape and stays drawable; a pair
        // that merely climbed onto the same ancestor is internal detail at this depth and must not
        loop: e.source === e.target }))
      .filter((e) => e.source && e.target)
      // ...and neither may an arrow that climbed onto its own ANCESTOR. At `public` depth a call to a
      // private helper loses its target, which would otherwise climb to the calling class and draw a
      // method pointing at the box it already sits inside. Containment is not a dependency.
      .filter((e) => !contains(e.source, e.target) && !contains(e.target, e.source));
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
    paintLegend(nodes, edges);
  }

  // The legend IS the count: every kind currently selected, drawn exactly as it appears in the graph and
  // carrying how many of it are on screen. A kind at ZERO stays listed but dims — "structure shows nothing"
  // and "structure found no inheritance" are different answers, and only the second one is useful.
  function paintLegend(nodes, edges) {
    const tiers = LEVELS
      .map((k) => [k, nodes.filter((n) => (n.level || 'module') === k).length])
      .filter(([, n]) => n > 0)
      .map(([k, n]) => `${n} ${n === 1 ? k : PLURAL[k]}`);
    $('counts').textContent = tiers.join(' · ');
    const active = KINDS.filter((k) => kinds().has(k));
    $('legend').innerHTML = active.map((k) => {
      const n = edges.filter((e) => (e.kind || 'import') === k).length;
      return `<span class="key${n ? '' : ' zero'}">${swatch(k)}${k}<b>${n}</b></span>`;
    }).join('');
    $('caption').textContent = band ? CAPTION[band] : 'a hand-picked set of arrow kinds';
  }

  // ---- fold state -------------------------------------------------------------------------------------
  // `collapsed` OUTLIVES filter changes: folding is a reading position the user built by hand, and losing
  // it on every toggle makes the two axes unusable together. Only a node never seen before takes the
  // default (a root package starts folded); `reset view` is the one control that clears the lot.
  const collapsed = new Set(), seen = new Set();
  function applyDefaultFold() {
    for (const n of GRAPH.nodes) {
      if (seen.has(n.id)) continue;
      seen.add(n.id);
      if (!PARENT[n.id] && DESC[n.id] > 0) collapsed.add(n.id);
    }
  }

  function ancestors(id) { const a = []; let p = PARENT[id]; while (p) { a.push(p); p = PARENT[p]; } return a; }
  function hiddenBy(id) { return ancestors(id).some((a) => collapsed.has(a)); }
  function inV(id) { return !hiddenBy(id); }
  function rep(id) { let r = id; for (const a of [id, ...ancestors(id)]) if (collapsed.has(a)) r = a; return r; }

  const EDGE = ({ color, line, head, tail }) => ({
    'line-color': color, 'line-style': line,
    'target-arrow-color': color, 'target-arrow-shape': head,
    ...(tail ? { 'source-arrow-color': color, 'source-arrow-shape': tail } : {}) });

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
      { selector: 'node[level="method"]', style: {
        shape: 'round-rectangle', 'background-color': '#1e3a4d', 'border-color': '#7d8590',
        'font-size': 9, color: '#b8c7d6', padding: 3 } },
      { selector: 'node[role="satellite"]', style: {
        'background-opacity': 0.45, 'border-style': 'dashed', color: '#9fb4c8', 'font-size': 9 } },
      { selector: 'edge', style: {
        width: (e) => Math.min(1 + Math.sqrt(e.data('weight') || 1) * 1.1, 8), 'curve-style': 'bezier',
        // only the import tier is a COUNT worth printing; a typed arrow is a fact, and labelling every one
        // "1" is noise
        label: (e) => (e.data('kind') === 'import' ? String(e.data('weight')) : ''),
        'font-size': 11, color: '#f0c674', 'text-background-color': '#05060a',
        'text-background-opacity': 0.9, 'text-background-padding': 2, 'arrow-scale': 1,
        ...EDGE(STYLE.import) } },
      // SOLID = structural (what the class knows) · DASHED = behavioural (what it does).
      // Arrowheads borrow UML: hollow triangle = generalization, diamond = composition, plain = dependency.
      // Derived from STYLE, which the legend swatches read too — one table, so the key cannot lie.
      ...KINDS.map((k) => ({
        selector: `edge[kind="${k}"]`, style: EDGE(STYLE[k]) })),
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
      // A self-arrow survives only where it is genuinely one AND the box is open. Folded, it would claim a
      // package owns itself when what it really holds is one recursive class inside.
      if (s === t && (!e.loop || collapsed.has(s))) continue;
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

  // the ONLY redraw path that preserves fold state — every control except `reset view` goes through here
  function apply() { rebuild(); applyDefaultFold(); refresh(); }

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

  // ---- wiring -----------------------------------------------------------------------------------------
  // the per-kind panel gets its swatches from the same table as the legend and the graph
  for (const k of KINDS) $('sw-' + k).outerHTML = swatch(k);

  $('depth').onclick = (e) => {
    if (!e.target.dataset.v) return;
    depth = e.target.dataset.v;
    paintSeg('depth', depth);
    apply();
  };
  $('arrows').onclick = (e) => {
    if (!e.target.dataset.v) return;
    band = e.target.dataset.v;
    paintSeg('arrows', band);
    KINDS.forEach((k) => { $('kind-' + k).checked = BANDS[band].includes(k); });
    // structural and behavioural arrows do not exist at module level, so picking one there would draw an
    // empty graph. Advance the depth instead of refusing the click.
    if (band !== 'imports' && depth === 'module') { depth = 'class'; paintSeg('depth', depth); }
    apply();
  };
  // touching an individual kind means the set is no longer a band — the segmented control stops claiming one
  KINDS.forEach((k) => $('kind-' + k).addEventListener('change', () => {
    band = null;
    paintSeg('arrows', null);
    apply();
  }));
  $('hide-satellites').addEventListener('change', apply);
  $('kindsBtn').onclick = () => $('kinds').classList.toggle('open');
  $('helpBtn').onclick = () => $('help').classList.toggle('open');
  $('fold').onclick = () => {
    collapsed.clear();
    GRAPH.nodes.filter((n) => !PARENT[n.id] && DESC[n.id] > 0).forEach((n) => collapsed.add(n.id));
    refresh();
  };
  $('reset').onclick = () => {
    depth = 'module'; band = 'imports';
    paintSeg('depth', depth); paintSeg('arrows', band);
    KINDS.forEach((k) => { $('kind-' + k).checked = BANDS.imports.includes(k); });
    $('hide-satellites').checked = false;
    collapsed.clear(); seen.clear();
    apply();
  };

  $('reset').onclick();
})();
