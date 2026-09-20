'use strict';
/* eXPoSe SpectraDeck - offline data browser.
   No libraries, no network. The first half is pure logic (decoding, axes,
   ticks, normalising, grouping, CSV) and is unit-tested under Node; the
   second half builds the page and only runs where there is a document. */
(function (G) {
  var V = {};

  /* ------------------------------------------------------------ decoding */
  V.b64ToBytes = function (b64) {
    var s = atob(b64.replace(/\s+/g, '')), a = new Uint8Array(s.length);
    for (var i = 0; i < s.length; i++) a[i] = s.charCodeAt(i);
    return a;
  };
  V.decode = function (b64) {
    if (typeof DecompressionStream === 'undefined') {
      return Promise.reject(new Error('This browser has no DecompressionStream'));
    }
    var stream = new Blob([V.b64ToBytes(b64)]).stream()
      .pipeThrough(new DecompressionStream('gzip'));
    return new Response(stream).text().then(JSON.parse);
  };
  /* an energy axis is stored as {x0, dx, n} when regular, else as a list */
  V.axisValues = function (e) {
    if (Array.isArray(e)) return e;
    var out = new Array(e.n);
    for (var i = 0; i < e.n; i++) out[i] = e.x0 + e.dx * i;
    return out;
  };

  /* --------------------------------------------------------------- maths */
  V.niceFloor = function (x) {              /* down to 1, 2 or 5 x 10^n */
    if (!(x > 0) || !isFinite(x)) return 1;
    var e = Math.floor(Math.log10(x)), m = x / Math.pow(10, e);
    return (m >= 5 ? 5 : m >= 2 ? 2 : 1) * Math.pow(10, e);
  };
  V.niceStep = function (range, target) {   /* a round step, ~target ticks */
    var raw = range / Math.max(1, target), mag = Math.pow(10, Math.floor(Math.log10(raw)));
    var m = raw / mag;
    return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * mag;
  };
  V.niceTicks = function (lo, hi, target) {
    if (!(hi > lo) || !isFinite(lo) || !isFinite(hi)) return [];
    var step = V.niceStep(hi - lo, target || 6), out = [];
    for (var k = Math.ceil(lo / step - 1e-9); k * step <= hi + step * 1e-9; k++) {
      out.push(+(k * step).toPrecision(12));
    }
    return out;
  };
  V.decimals = function (step) {
    if (!(step > 0)) return 0;
    return Math.max(0, Math.min(6, -Math.floor(Math.log10(step) + 1e-9)));
  };
  V.fmtY = function (v) {
    var a = Math.abs(v);
    if (a === 0) return '0';
    if (a >= 1e5 || a < 1e-2) return v.toExponential(1).replace('e+', 'e');
    if (a >= 100) return String(Math.round(v));
    return String(+v.toPrecision(3));
  };
  V.normFactor = function (y, mode) {
    var i, m, s;
    if (mode === 'max') {
      m = -Infinity;
      for (i = 0; i < y.length; i++) if (y[i] > m) m = y[i];
      return m ? m : 1;
    }
    if (mode === 'area') {
      s = 0;
      for (i = 0; i < y.length; i++) s += Math.abs(y[i]);
      s /= y.length;
      return s ? s : 1;
    }
    return 1;
  };
  /* nudge label positions apart (order kept); positions are pixels, y down */
  V.dodge = function (ys, gap) {
    var order = ys.map(function (_v, i) { return i; })
      .sort(function (a, b) { return ys[a] - ys[b]; });
    var out = ys.slice();
    for (var k = 1; k < order.length; k++) {
      var a = order[k - 1], b = order[k];
      if (out[b] - out[a] < gap) out[b] = out[a] + gap;
    }
    return out;
  };
  V.interp = function (xs, ys, x) {        /* linear, either direction */
    var n = xs.length;
    if (!n) return null;
    var asc = xs[n - 1] >= xs[0], lo = 0, hi = n - 1;
    if ((asc && (x < xs[0] || x > xs[n - 1])) || (!asc && (x > xs[0] || x < xs[n - 1]))) return null;
    while (hi - lo > 1) {
      var mid = (lo + hi) >> 1;
      if ((xs[mid] <= x) === asc) lo = mid; else hi = mid;
    }
    var d = xs[hi] - xs[lo];
    return d === 0 ? ys[lo] : ys[lo] + (ys[hi] - ys[lo]) * (x - xs[lo]) / d;
  };

  /* -------------------------------------------------------------- colour */
  V.hexToRgb = function (h) {
    h = h.replace('#', '');
    return [0, 2, 4].map(function (i) { return parseInt(h.substr(i, 2), 16); });
  };
  V.rgbToHex = function (c) {
    return '#' + c.map(function (v) {
      v = Math.max(0, Math.min(255, Math.round(v)));
      return (v < 16 ? '0' : '') + v.toString(16);
    }).join('').toUpperCase();
  };
  V.mix = function (a, b, t) {
    var ra = V.hexToRgb(a), rb = V.hexToRgb(b);
    return V.rgbToHex(ra.map(function (x, i) { return x + (rb[i] - x) * t; }));
  };
  V.ramp = function (colour, n, background) {   /* one hue fading out */
    if (n <= 1) return [colour];
    var top = Math.min(0.62, 0.10 * (n - 1)), out = [];
    for (var i = 0; i < n; i++) out.push(V.mix(colour, background, top * i / (n - 1)));
    return out;
  };
  /* colours of one panel from each trace's slot: categorical, or a ramp of
     one hue when every trace shares a slot (the levels of a depth profile) */
  V.stackColours = function (slots, cycle, background) {
    var same = slots.length > 1 && slots.every(function (s) { return s === slots[0]; });
    if (same) return V.ramp(cycle[slots[0] % cycle.length], slots.length, background);
    return slots.map(function (s) { return cycle[s % cycle.length]; });
  };

  /* --------------------------------------------------------------- axes */
  V.energyAxis = function (reg, x, scale) {
    var label = reg.elabel || 'Binding Energy', low = label.toLowerCase();
    var native = { x: x, invert: !!reg.binding, ok: true, units: reg.eunits || 'eV',
                   label: low.charAt(0).toUpperCase() + low.slice(1) };
    if (scale !== 'Kinetic') return native;
    if (reg.binding && reg.hv) {
      return { x: x.map(function (v) { return reg.hv - v; }), invert: false, ok: true,
               units: 'eV', label: 'Kinetic energy' };
    }
    if (!reg.binding) { native.invert = false; return native; }   /* native KE */
    native.ok = false;                                            /* no photon energy */
    return native;
  };
  V.normName = function (n) { return String(n || '').replace(/\s+/g, ' ').trim().toLowerCase(); };
  /* spectra with the same element name share a panel; first appearance order */
  V.groupSpectra = function (specs) {
    var groups = [], by = {};
    specs.forEach(function (s) {
      var k = V.normName(s.name);
      if (!by[k]) { by[k] = { key: k, name: s.name, items: [] }; groups.push(by[k]); }
      by[k].items.push(s);
    });
    return groups;
  };
  V.traceLabel = function (s, multiFile) {
    var base;
    if (s.reg.level !== null && s.reg.level !== undefined) {
      base = 'L' + s.reg.level + (s.reg.etch !== null && s.reg.etch !== undefined ? ' (' + +s.reg.etch.toPrecision(6) + ' s)' : '');
    } else {
      base = s.sample.name || (multiFile ? s.fileName.replace(/\.[^.]*$/, '') : s.name);
    }
    return base.length <= 24 ? base : base.slice(0, 22) + '…';
  };

  /* ------------------------------------------------------------------ CSV */
  V.csvField = function (v) {
    var t = String(v);
    return /[",\r\n]/.test(t) ? '"' + t.replace(/"/g, '""') + '"' : t;
  };
  /* wide format: an energy and an intensity column per spectrum, as the
     desktop app's own CSV export */
  V.buildCsv = function (specs) {
    var cols = [], maxlen = 0;
    specs.forEach(function (s) {
      var pre = s.sample.name ? s.sample.name + ' ' : '';
      var tag = s.reg.level !== null && s.reg.level !== undefined ? ' L' + s.reg.level : '';
      cols.push([pre + s.name + tag + ' ' + (s.reg.elabel || 'Binding Energy') + ' (' + (s.reg.eunits || 'eV') + ')', s.x]);
      cols.push([pre + s.name + tag + ' ' + s.reg.ylabel + ' (' + s.reg.yunits + ')', s.y]);
      maxlen = Math.max(maxlen, s.y.length);
    });
    var lines = [cols.map(function (c) { return V.csvField(c[0]); }).join(',')];
    for (var i = 0; i < maxlen; i++) {
      lines.push(cols.map(function (c) { return i < c[1].length ? String(c[1][i]) : ''; }).join(','));
    }
    return lines.join('\r\n') + '\r\n';
  };

  /* ------------------------------------------------------------- metadata */
  /* what is the same for every row, and the columns that differ */
  V.summariseMeta = function (rows, skip) {
    skip = skip || [];
    var keys = [];
    rows.forEach(function (r) {
      Object.keys(r).forEach(function (k) { if (keys.indexOf(k) < 0 && skip.indexOf(k) < 0) keys.push(k); });
    });
    var common = [], varying = [];
    keys.forEach(function (k) {
      var vals = rows.map(function (r) { return r[k] === undefined ? '' : r[k]; });
      var first = vals[0], same = vals.every(function (v) { return v === first; });
      if (same && first !== '') common.push([k, first]); else if (!same) varying.push(k);
    });
    return { common: common, varying: varying };
  };
  V.paragraphs = function (text) {
    return String(text || '').replace(/\r\n/g, '\n').split(/\n\s*\n/)
      .map(function (p) { return p.replace(/^\n+|\n+$/g, ''); })
      .filter(function (p) { return p.trim() !== ''; });
  };

  /* --------------------------------------------------------- data prepare */
  V.prepare = function (data) {
    var specs = [], samples = data.samples;
    samples.forEach(function (s, si) {
      s.index = si;
      s.regions.forEach(function (r) {
        specs.push({ id: r.id, sample: s, reg: r, name: r.name, x: V.axisValues(r.e), y: r.y,
                     fileName: (data.files[s.file] || {}).name || '' });
      });
    });
    return specs;
  };

  G.XPSViewer = V;
  if (typeof module !== 'undefined' && module.exports) module.exports = V;
  if (typeof document === 'undefined') return;

  /* ============================================================ the page */
  var S = { data: null, specs: [], byId: {}, ticked: new Set(), selected: null, mode: 'stack',
            norm: 'none', offset: 0.6, scale: 'Binding', levelOn: false, levelIdx: 0, levels: [],
            panels: new Map(), theme: 'auto', printing: false, nodes: [], holderIdx: 0,
            holderHot: null, tab: 'plot', filter: '' };
  var $ = function (id) { return document.getElementById(id); };

  function h(tag, attrs) {
    var e = document.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) {
      if (k === 'text') e.textContent = attrs[k];
      else if (k === 'class') e.className = attrs[k];
      else if (k.slice(0, 2) === 'on') e.addEventListener(k.slice(2), attrs[k]);
      else e.setAttribute(k, attrs[k]);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c === null || c === undefined) continue;
      e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return e;
  }
  function clear(e) { while (e.firstChild) e.removeChild(e.firstChild); return e; }

  /* ---------------------------------------------------------------- theme */
  function isDark() {
    if (S.printing) return false;
    if (S.theme === 'dark') return true;
    if (S.theme === 'light') return false;
    return !!(G.matchMedia && G.matchMedia('(prefers-color-scheme: dark)').matches);
  }
  function applyTheme() {
    document.documentElement.setAttribute('data-eff', isDark() ? 'dark' : 'light');
    requestRender();
    if (S.tab === 'holder') drawHolder();
  }
  function colours() {
    var cs = G.getComputedStyle(document.documentElement);
    var g = function (n) { return cs.getPropertyValue(n).trim(); };
    return { bg: g('--plot-bg'), fg: g('--plot-fg'), muted: g('--plot-muted'), grid: g('--plot-grid'),
             accent: g('--accent') };
  }
  function cycle() { return S.data.palette[isDark() ? 'dark' : 'light']; }

  /* ----------------------------------------------------------------- tree */
  function slotOf(spec) {
    return S.data.files.length > 1 ? spec.sample.file : spec.sample.index;
  }
  function buildTree() {
    var root = clear($('tree')), ul = h('ul', { role: 'group' });
    root.appendChild(ul);
    S.nodes = [];
    var many = S.data.samples.length > 3;
    S.data.samples.forEach(function (s) {
      var byName = {}, order = [];
      s.regions.forEach(function (r) {
        var k = V.normName(r.name);
        if (!byName[k]) { byName[k] = []; order.push(k); }
        byName[k].push(r);
      });
      var kids = [];
      order.forEach(function (k) {
        var rs = byName[k], profile = rs.length > 1 && rs.every(function (r) { return r.level !== null && r.level !== undefined; });
        if (profile) {
          var leaves = rs.map(function (r) {
            return leafNode(r.id, 'Level ' + r.level + (r.etch !== null && r.etch !== undefined ? ' (' + +r.etch.toPrecision(6) + ' s)' : ''), s.name + ' ' + rs[0].name);
          });
          kids.push(groupNode(rs[0].name + ' · ' + rs.length + ' levels', leaves, false));
        } else {
          rs.forEach(function (r) { kids.push(leafNode(r.id, r.name, s.name)); });
        }
      });
      var node = groupNode(s.name || '(unnamed)', kids, many, s);
      ul.appendChild(node.li);
    });
    refreshChecks();
  }
  function leafIds(node) {
    return node.leaf ? [node.leaf] : node.kids.reduce(function (a, k) { return a.concat(leafIds(k)); }, []);
  }
  function leafNode(id, label, group) {
    var chk = h('input', { type: 'checkbox', 'aria-label': 'Plot ' + label });
    var spec = S.byId[id];
    var lbl = h('span', { class: 'lbl', tabindex: '0', role: 'treeitem', text: label,
                          title: (group ? group + ' – ' : '') + label });
    var sw = h('span', { class: 'swatch' });
    var li = h('li', null, h('div', { class: 'row' }, h('button', { class: 'tw leaf', tabindex: '-1', 'aria-hidden': 'true', text: '▸' }), chk, sw, lbl));
    var node = { li: li, chk: chk, lbl: lbl, sw: sw, leaf: id, kids: [], label: label, spec: spec, group: group };
    chk.addEventListener('change', function () { setTicked([id], chk.checked); });
    var pick = function () { select({ kind: 'region', id: id }); };
    lbl.addEventListener('click', pick);
    lbl.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
    S.nodes.push(node);
    return node;
  }
  function groupNode(label, kids, collapsed, sample) {
    var chk = h('input', { type: 'checkbox', 'aria-label': 'Plot every spectrum of ' + label });
    var tw = h('button', { class: 'tw', type: 'button', 'aria-label': 'Expand or collapse ' + label, text: '▾' });
    var lbl = h('span', { class: 'lbl', tabindex: '0', role: 'treeitem', text: label, title: label });
    var cnt = h('span', { class: 'cnt' });
    var ul = h('ul', { role: 'group' });
    kids.forEach(function (k) { ul.appendChild(k.li); });
    var li = h('li', null, h('div', { class: 'row' }, tw, chk, lbl, cnt), ul);
    var node = { li: li, chk: chk, lbl: lbl, cnt: cnt, tw: tw, kids: kids, label: label, sample: sample };
    var setOpen = function (open) {
      li.classList.toggle('collapsed', !open);
      tw.textContent = open ? '▾' : '▸';
    };
    node.setOpen = setOpen;
    setOpen(!collapsed);
    tw.addEventListener('click', function () { setOpen(li.classList.contains('collapsed')); });
    chk.addEventListener('change', function () { setTicked(leafIds(node), chk.checked); });
    var pick = function () {
      if (sample) select({ kind: 'sample', id: sample.id });
      else setOpen(li.classList.contains('collapsed'));
    };
    lbl.addEventListener('click', pick);
    lbl.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick(); } });
    S.nodes.push(node);
    return node;
  }
  function refreshChecks() {
    S.nodes.forEach(function (n) {
      if (n.leaf) { n.chk.checked = S.ticked.has(n.leaf); return; }
      var ids = leafIds(n), k = ids.filter(function (i) { return S.ticked.has(i); }).length;
      n.chk.checked = k === ids.length && k > 0;
      n.chk.indeterminate = k > 0 && k < ids.length;
      n.cnt.textContent = k ? k + '/' + ids.length : String(ids.length);
    });
    $('tickcount').textContent = S.ticked.size + ' of ' + S.specs.length + ' spectra ticked';
  }
  function refreshSwatches() {
    var cols = traceColourMap();
    S.nodes.forEach(function (n) {
      if (!n.leaf) return;
      var c = S.ticked.has(n.leaf) ? cols[n.leaf] : null;
      n.sw.style.background = c || 'transparent';
      n.sw.style.border = c ? 'none' : '1px solid var(--border)';
    });
  }
  function refreshSelection() {
    S.nodes.forEach(function (n) {
      var on = false;
      if (S.selected) {
        if (S.selected.kind === 'region') on = n.leaf === S.selected.id;
        else on = !!(n.sample && n.sample.id === S.selected.id);
      }
      n.lbl.parentNode.classList.toggle('selected', on);
    });
  }
  function setTicked(ids, on) {
    ids.forEach(function (i) { if (on) S.ticked.add(i); else S.ticked.delete(i); });
    refreshChecks();
    requestRender();
    if (S.tab === 'holder') drawHolder();
  }
  function tickOnly(ids) {
    S.ticked = new Set(ids);
    refreshChecks();
    requestRender();
  }
  function applyFilter() {
    var q = S.filter.trim().toLowerCase();
    function vis(node, forced) {
      var self = !q || (node.label + ' ' + (node.group || '')).toLowerCase().indexOf(q) >= 0;
      var any = false;
      node.kids.forEach(function (k) { if (vis(k, forced || (self && !!q))) any = true; });
      var show = !q || self || any || forced;
      node.li.classList.toggle('hidden', !show);
      if (q && node.setOpen && any) node.setOpen(true);
      return show && (self || any || forced);
    }
    S.nodes.filter(function (n) { return n.sample; }).forEach(function (n) { vis(n, false); });
  }

  function select(sel) {
    S.selected = sel;
    refreshSelection();
    renderMeta();
    requestRender();
    if (S.tab === 'holder') drawHolder();
  }

  /* -------------------------------------------------------- plot: models */
  function visibleSpecs() {
    var list = S.specs.filter(function (s) { return S.ticked.has(s.id); });
    var lv = [];
    list.forEach(function (s) {
      var l = s.reg.level;
      if (l !== null && l !== undefined && lv.indexOf(l) < 0) lv.push(l);
    });
    lv.sort(function (a, b) { return a - b; });
    S.levels = lv;
    if (S.levelIdx > lv.length - 1) S.levelIdx = Math.max(0, lv.length - 1);
    if (S.levelOn && lv.length > 1) {
      var want = lv[S.levelIdx];
      list = list.filter(function (s) { var l = s.reg.level; return l === null || l === undefined || l === want; });
    }
    return list;
  }
  function traceColourMap() {
    var out = {}, cyc = cycle(), bg = S.data.palette.bg[isDark() ? 'dark' : 'light'];
    V.groupSpectra(S.specs.filter(function (s) { return S.ticked.has(s.id); })).forEach(function (g) {
      var cols = V.stackColours(g.items.map(slotOf), cyc, bg);
      g.items.forEach(function (s, i) { out[s.id] = cols[i]; });
    });
    return out;
  }
  function isSelected(spec) {
    if (!S.selected) return false;
    return S.selected.kind === 'region' ? S.selected.id === spec.id : S.selected.id === spec.sample.id;
  }

  /* ----------------------------------------------------------- plot: draw */
  var reqJob = 0;
  function requestRender() {
    if (reqJob) return;
    reqJob = G.requestAnimationFrame(function () { reqJob = 0; render(); });
  }
  function render() {
    if (S.tab !== 'plot' && !S.printing) return;
    var specs = visibleSpecs(), groups = V.groupSpectra(specs);
    var host = $('panels'), keep = {};
    groups.forEach(function (g) { keep[g.key] = true; });
    S.panels.forEach(function (p, k) { if (!keep[k]) { host.removeChild(p.wrap); S.panels.delete(k); } });
    groups.forEach(function (g, i) {
      var p = S.panels.get(g.key);
      if (!p) p = makePanel(g.key);
      p.group = g;
      if (host.children[i] !== p.wrap) host.insertBefore(p.wrap, host.children[i] || null);
    });
    host.classList.toggle('one', groups.length === 1);
    $('empty').hidden = groups.length > 0;
    $('offsetField').style.display = S.mode === 'stack' ? '' : 'none';
    var bar = $('levelbar'), many = S.levels.length > 1;
    bar.hidden = !many;
    if (many) {
      $('level').max = String(S.levels.length - 1);
      $('level').value = String(S.levelIdx);
      $('level').disabled = !S.levelOn;
      var l = S.levels[S.levelIdx], any = specs.filter(function (s) { return s.reg.level === l; })[0];
      var depth = any && any.reg.meta && any.reg.meta['Depth (nm)'] ? ', ' + any.reg.meta['Depth (nm)'] + ' nm' : '';
      $('levelText').textContent = S.levelOn ? 'Level ' + l + (any && any.reg.etch !== null && any.reg.etch !== undefined ? ' (' + +any.reg.etch.toPrecision(6) + ' s' + depth + ')' : '') + '  ·  ' + (S.levelIdx + 1) + ' of ' + S.levels.length : S.levels.length + ' levels shown';
    }
    var notes = [];
    if (S.scale === 'Kinetic' && specs.some(function (s) { return s.reg.binding && !s.reg.hv; })) {
      notes.push('no photon energy for some spectra: shown as binding energy');
    }
    $('notes').textContent = notes.join('; ');
    refreshSwatches();
    var cols = colours(), cmap = traceColourMap();
    S.panels.forEach(function (p) { drawPanel(p, cols, cmap); });
  }
  function makePanel(key) {
    var canvas = h('canvas', { 'aria-label': 'Spectrum plot', role: 'img' });
    var readout = h('div', { class: 'readout', 'aria-live': 'off' });
    var wrap = h('div', { class: 'panel' }, canvas, readout);
    var p = { key: key, wrap: wrap, canvas: canvas, readout: readout, zoom: null, hover: null,
              drag: null, lay: null, group: null, job: 0 };
    S.panels.set(key, p);
    canvas.addEventListener('mousemove', function (e) { onMove(p, e); });
    canvas.addEventListener('mouseleave', function () { p.hover = null; p.readout.textContent = ''; redraw(p); });
    canvas.addEventListener('mousedown', function (e) {
      if (e.button !== 0 || !p.lay) return;
      var x = px(p, e);
      if (x >= p.lay.l && x <= p.lay.l + p.lay.w) p.drag = { a: x, b: x };
    });
    G.addEventListener('mouseup', function () {
      if (!p.drag) return;
      var d = p.drag; p.drag = null;
      if (Math.abs(d.b - d.a) > 6 && p.lay) {
        var v1 = p.lay.toX(d.a), v2 = p.lay.toX(d.b);
        p.zoom = [Math.min(v1, v2), Math.max(v1, v2)];
      }
      redraw(p);
    });
    canvas.addEventListener('dblclick', function () { p.zoom = null; redraw(p); });
    canvas.addEventListener('wheel', function (e) {
      if (!p.lay) return;
      e.preventDefault();
      var x = px(p, e), c = p.lay.toX(x), f = e.deltaY < 0 ? 0.8 : 1.25;
      var lo = p.lay.lo, hi = p.lay.hi;
      p.zoom = [c - (c - lo) * f, c + (hi - c) * f];
      redraw(p);
    }, { passive: false });
    return p;
  }
  function px(p, e) { return e.clientX - p.canvas.getBoundingClientRect().left; }
  function py(p, e) { return e.clientY - p.canvas.getBoundingClientRect().top; }
  function redraw(p) {
    if (p.job) return;
    p.job = G.requestAnimationFrame(function () {
      p.job = 0;
      drawPanel(p, colours(), traceColourMap());
    });
  }

  function drawPanel(P, C, cmap) {
    var g = P.group, cv = P.canvas;
    if (!g) return;
    var W = cv.clientWidth, H = cv.clientHeight;
    if (!W || !H) return;
    var dpr = G.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
      cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    }
    var ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    var font = function (px_, w) { return (w || '') + ' ' + px_ + 'px system-ui, "Segoe UI", Helvetica, Arial, sans-serif'; };

    var items = g.items, n = items.length;
    var axes = items.map(function (s) { return V.energyAxis(s.reg, s.x, S.scale); });
    var ax0 = axes[0];
    var ys = items.map(function (s) {
      var f = V.normFactor(s.y, S.norm);
      return s.y.map(function (v) { return v / f; });
    });
    var stacked = S.mode === 'stack' && n > 1;
    var spans = ys.map(function (v) { return Math.max.apply(null, v) - Math.min.apply(null, v); });
    var step = stacked ? S.offset * (Math.max.apply(null, spans) || 1) : 0;
    var yoff = ys.map(function (v, i) { return v.map(function (y) { return y + i * step; }); });

    var xlo = Infinity, xhi = -Infinity;
    axes.forEach(function (a) { a.x.forEach(function (v) { if (v < xlo) xlo = v; if (v > xhi) xhi = v; }); });
    var pad = (xhi - xlo) * 0.02 || 1;
    var dlo = xlo - pad, dhi = xhi + pad;
    var lo = P.zoom ? P.zoom[0] : dlo, hi = P.zoom ? P.zoom[1] : dhi;
    if (!(hi > lo)) { lo = dlo; hi = dhi; }

    var ylo = Infinity, yhi = -Infinity;
    yoff.forEach(function (v, i) {
      var xs = axes[i].x;
      for (var k = 0; k < v.length; k++) {
        if (xs[k] < lo || xs[k] > hi) continue;
        if (v[k] < ylo) ylo = v[k]; if (v[k] > yhi) yhi = v[k];
      }
    });
    if (!isFinite(ylo)) { ylo = 0; yhi = 1; }
    var yp = (yhi - ylo) * 0.06 || 1;
    ylo -= yp; yhi += yp;

    /* end labels sit in a gutter to the right of a stack */
    var labels = items.map(function (s) { return V.traceLabel(s, S.data.files.length > 1); });
    var gutter = 14;
    if (stacked) {
      ctx.font = font(11);
      gutter = Math.min(150, Math.max.apply(null, labels.map(function (t) { return ctx.measureText(t).width; })) + 16);
    }
    var lay = { l: stacked ? 46 : 62, t: 30, w: 0, h: 0, lo: lo, hi: hi };
    lay.w = Math.max(50, W - lay.l - gutter);
    lay.h = Math.max(50, H - lay.t - 44);
    var invert = ax0.invert;
    var X = function (v) { return lay.l + (invert ? (hi - v) : (v - lo)) / (hi - lo) * lay.w; };
    var Y = function (v) { return lay.t + (1 - (v - ylo) / (yhi - ylo)) * lay.h; };
    lay.toX = function (pxv) { var f = (pxv - lay.l) / lay.w; return invert ? hi - f * (hi - lo) : lo + f * (hi - lo); };
    lay.X = X; lay.Y = Y; lay.ax = ax0;
    P.lay = lay; P.axes = axes; P.yoff = yoff; P.ys = ys; P.items = items; P.stacked = stacked;

    /* titles */
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle = C.fg; ctx.font = font(14, 'bold'); ctx.textAlign = 'left';
    ctx.fillText(g.name, lay.l, 20);
    var sub = n === 1 ? items[0].sample.name : n + ' spectra';
    ctx.fillStyle = C.muted; ctx.font = font(11); ctx.textAlign = 'right';
    ctx.fillText(sub, lay.l + lay.w, 20);

    /* x axis: line, ticks, labels */
    ctx.strokeStyle = C.muted; ctx.fillStyle = C.muted; ctx.lineWidth = 1;
    var by = lay.t + lay.h;
    ctx.beginPath(); ctx.moveTo(lay.l, by + 0.5); ctx.lineTo(lay.l + lay.w, by + 0.5); ctx.stroke();
    var xt = V.niceTicks(lo, hi, Math.max(3, Math.round(lay.w / 80))), xstep = xt.length > 1 ? xt[1] - xt[0] : 1;
    ctx.font = font(11); ctx.textAlign = 'center';
    xt.forEach(function (t) {
      var x = Math.round(X(t)) + 0.5;
      ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(x, lay.t); ctx.lineTo(x, by); ctx.stroke();
      ctx.strokeStyle = C.muted; ctx.beginPath(); ctx.moveTo(x, by); ctx.lineTo(x, by + 4); ctx.stroke();
      ctx.fillText(t.toFixed(V.decimals(xstep)), x, by + 17);
    });
    ctx.fillStyle = C.fg; ctx.font = font(12); ctx.textAlign = 'center';
    ctx.fillText(ax0.label + ' (' + ax0.units + ')', lay.l + lay.w / 2, by + 36);

    /* y axis: ticks for one spectrum or an overlay, a scale bar for a stack */
    ctx.strokeStyle = C.muted; ctx.fillStyle = C.muted;
    if (!stacked) {
      ctx.beginPath(); ctx.moveTo(lay.l + 0.5, lay.t); ctx.lineTo(lay.l + 0.5, by); ctx.stroke();
      ctx.font = font(11); ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      V.niceTicks(ylo, yhi, Math.max(3, Math.round(lay.h / 50))).forEach(function (t) {
        var y = Math.round(Y(t)) + 0.5;
        ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(lay.l, y); ctx.lineTo(lay.l + lay.w, y); ctx.stroke();
        ctx.strokeStyle = C.muted; ctx.beginPath(); ctx.moveTo(lay.l - 4, y); ctx.lineTo(lay.l, y); ctx.stroke();
        ctx.fillText(V.fmtY(t), lay.l - 7, y);
      });
      ctx.save(); ctx.translate(13, lay.t + lay.h / 2); ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = C.fg; ctx.font = font(12); ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
      var r0 = items[0].reg;
      ctx.fillText(S.norm === 'none' ? r0.ylabel + (r0.yunits ? ' (' + r0.yunits + ')' : '') : r0.ylabel + ' (normalised)', 0, 0);
      ctx.restore();
    } else {
      var bar = V.niceFloor((yhi - ylo) * 0.22), y0 = ylo + (yhi - ylo) * 0.06;
      ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(lay.l - 8, Y(y0)); ctx.lineTo(lay.l - 8, Y(y0 + bar)); ctx.stroke();
      ctx.lineWidth = 1;
      ctx.save(); ctx.translate(lay.l - 14, (Y(y0) + Y(y0 + bar)) / 2); ctx.rotate(-Math.PI / 2);
      ctx.font = font(11); ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
      var u = S.norm === 'none' ? ' ' + (items[0].reg.yunits || '') : '';
      ctx.fillText((bar >= 1 ? Math.round(bar).toLocaleString('en-US') : String(bar)) + u, 0, 0);
      ctx.restore();
    }
    ctx.textBaseline = 'alphabetic';

    /* peak markers (first spectrum of the panel) */
    var marks = items[0].reg.markers || [];
    ctx.save();
    ctx.beginPath(); ctx.rect(lay.l, lay.t, lay.w, lay.h); ctx.clip();
    marks.forEach(function (m) {
      var hvv = items[0].reg.hv, fromHv = hvv ? hvv - m.be : null;
      var v = m.kin ? (ax0.invert ? fromHv : m.be) : (ax0.invert ? m.be : fromHv);
      if (v === null || v < lo || v > hi) return;
      var x = X(v);
      ctx.strokeStyle = C.muted; ctx.setLineDash([2, 3]); ctx.beginPath();
      ctx.moveTo(x, lay.t); ctx.lineTo(x, by); ctx.stroke(); ctx.setLineDash([]);
      ctx.save(); ctx.translate(x, lay.t + 4); ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = C.muted; ctx.font = font(10); ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      ctx.fillText(m.label, 0, 0); ctx.restore();
    });

    /* traces */
    var endpts = [];
    items.forEach(function (s, i) {
      var xs = axes[i].x, v = yoff[i], sel = isSelected(s);
      ctx.strokeStyle = cmap[s.id] || C.fg;
      ctx.lineWidth = sel ? 2.3 : (n > 12 ? 1 : 1.4);
      ctx.lineJoin = 'round';
      ctx.beginPath();
      for (var k = 0; k < xs.length; k++) {
        var x = X(xs[k]), y = Y(v[k]);
        if (k === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
      /* the right-hand end of the trace, for its label */
      var j = 0;
      for (var q = 1; q < xs.length; q++) if ((invert ? xs[q] < xs[j] : xs[q] > xs[j])) j = q;
      var a = Math.max(0, j - 2), b = Math.min(v.length, j + 3), sum = 0;
      for (q = a; q < b; q++) sum += v[q];
      endpts.push(Y(sum / (b - a)));
    });
    ctx.restore();

    /* trace labels: at the end of each trace of a stack, a legend otherwise */
    ctx.font = font(11); ctx.textBaseline = 'middle';
    if (stacked) {
      var every = Math.max(1, Math.ceil(n / 12)), sel = [], ids = [];
      items.forEach(function (s, i) { if (i % every === 0) { sel.push(endpts[i]); ids.push(i); } });
      var pos = V.dodge(sel, 14);
      ctx.textAlign = 'left';
      ids.forEach(function (i, k) {
        ctx.fillStyle = cmap[items[i].id] || C.fg;
        ctx.fillText(labels[i], lay.l + lay.w + 6, Math.min(by - 4, Math.max(lay.t + 4, pos[k])));
      });
    } else if (n > 1) {
      var lx = lay.l + lay.w - 8, ly = lay.t + 10;
      ctx.textAlign = 'right';
      items.slice(0, 12).forEach(function (s, i) {
        ctx.fillStyle = cmap[s.id] || C.fg;
        ctx.fillText(labels[i], lx - 16, ly + i * 15);
        ctx.fillRect(lx - 12, ly + i * 15 - 1, 12, 2.5);
      });
    }
    ctx.textBaseline = 'alphabetic';

    /* crosshair and zoom rectangle */
    if (P.hover !== null && P.hover >= lay.l && P.hover <= lay.l + lay.w) {
      ctx.strokeStyle = C.accent; ctx.setLineDash([4, 3]); ctx.beginPath();
      ctx.moveTo(P.hover + 0.5, lay.t); ctx.lineTo(P.hover + 0.5, by); ctx.stroke(); ctx.setLineDash([]);
    }
    if (P.drag) {
      ctx.fillStyle = C.accent; ctx.globalAlpha = 0.15;
      ctx.fillRect(Math.min(P.drag.a, P.drag.b), lay.t, Math.abs(P.drag.b - P.drag.a), lay.h);
      ctx.globalAlpha = 1;
    }
  }

  function onMove(P, e) {
    var lay = P.lay;
    if (!lay) return;
    var x = px(P, e), y = py(P, e);
    if (P.drag) P.drag.b = Math.max(lay.l, Math.min(lay.l + lay.w, x));
    if (x < lay.l || x > lay.l + lay.w || y < lay.t || y > lay.t + lay.h) {
      P.hover = null; P.readout.textContent = ''; redraw(P); return;
    }
    P.hover = x;
    var v = lay.toX(x), r0 = P.items[0].reg, a0 = lay.ax;
    var be = null, ke = null;
    if (a0.label === 'Kinetic energy') { ke = v; be = r0.hv ? r0.hv - v : null; }
    else { be = v; ke = r0.hv && r0.binding ? r0.hv - v : null; }
    var parts = [];
    if (be !== null && r0.binding) parts.push('BE ' + be.toFixed(2) + ' eV');
    else if (a0.label !== 'Kinetic energy') parts.push(a0.label + ' ' + v.toFixed(2) + ' eV');
    if (ke !== null) parts.push('KE ' + ke.toFixed(2) + ' eV');
    var best = null, bd = Infinity;
    P.items.forEach(function (s, i) {
      var yv = V.interp(P.axes[i].x, P.yoff[i], v);
      if (yv === null) return;
      var d = Math.abs(lay.Y(yv) - y);
      if (d < bd) { bd = d; best = { s: s, i: i, raw: V.interp(P.axes[i].x, s.y, v) }; }
    });
    if (best) {
      parts.push((P.items.length > 1 ? V.traceLabel(best.s, S.data.files.length > 1) + ': ' : '') +
        V.fmtY(best.raw) + (best.s.reg.yunits ? ' ' + best.s.reg.yunits : ''));
    }
    P.readout.textContent = parts.join('   ·   ');
    redraw(P);
  }

  /* ---------------------------------------------------------------- tabs */
  var TABS = [['plot', 'Spectra'], ['figures', 'Figures'], ['meta', 'Metadata'],
              ['notes', 'Notes'], ['methods', 'Methods'], ['holder', 'Holder']];
  function availableTabs() {
    var d = S.data;
    return TABS.filter(function (t) {
      if (t[0] === 'figures') return d.figures.length > 0;
      if (t[0] === 'holder') return d.holders.length > 0;
      if (t[0] === 'methods') return !!d.methods.trim();
      return true;
    });
  }
  function buildTabs() {
    var nav = clear($('tabs'));
    availableTabs().forEach(function (t) {
      var b = h('button', { type: 'button', class: 'tab-btn', role: 'tab', id: 'tabbtn-' + t[0], text: t[1] });
      b.addEventListener('click', function () { showTab(t[0]); });
      nav.appendChild(b);
    });
  }
  function showTab(name) {
    S.tab = name;
    TABS.forEach(function (t) {
      var sec = $('tab-' + t[0]), btn = $('tabbtn-' + t[0]);
      if (sec) sec.hidden = t[0] !== name;
      if (btn) btn.setAttribute('aria-selected', t[0] === name ? 'true' : 'false');
    });
    if (name === 'plot') requestRender();
    if (name === 'holder') drawHolder();
    if (name === 'meta') renderMeta();
  }

  function renderFigures() {
    var box = clear($('tab-figures'));
    S.data.figures.forEach(function (f, i) {
      var fig = h('figure');
      f.pages.forEach(function (src, k) {
        var img = h('img', { src: src, alt: 'Figure ' + (i + 1) + ': ' + f.name });
        fig.appendChild(img);
        fig.appendChild(h('div', null, h('a', { href: src, download: 'figure_' + (i + 1) + (f.pages.length > 1 ? '_p' + (k + 1) : '') + '.png', text: 'Download PNG' })));
      });
      fig.appendChild(h('figcaption', null, h('strong', { text: 'Figure ' + (i + 1) + ' – ' + f.name }), f.caption ? '\n' + f.caption : ''));
      box.appendChild(fig);
    });
  }

  function kvTable(pairs) {
    var t = h('table', { class: 'kv' });
    pairs.forEach(function (p) { t.appendChild(h('tr', null, h('th', { text: p[0] }), h('td', { text: p[1] }))); });
    return t;
  }
  function renderMeta() {
    var box = clear($('tab-meta')), sel = S.selected;
    if (!sel) {
      box.appendChild(h('p', { class: 'muted', text: 'Select a sample or a spectrum in the list to see its acquisition metadata.' }));
      return;
    }
    if (sel.kind === 'region') {
      var s = S.byId[sel.id];
      box.appendChild(h('h2', { text: (s.sample.name ? s.sample.name + ' – ' : '') + s.name }));
      box.appendChild(kvTable(Object.keys(s.reg.meta).map(function (k) { return [k, s.reg.meta[k]]; })));
      if (s.reg.note) box.appendChild(h('p', { class: 'note', text: 'Note: ' + s.reg.note }));
      return;
    }
    var sm = S.data.samples[+sel.id.slice(1)];
    box.appendChild(h('h2', { text: sm.name || '(unnamed)' }));
    var rows = sm.regions.map(function (r) { return r.meta; });
    var sum = V.summariseMeta(rows, ['Sample', 'Region', 'Source file', 'Notes']);
    if (sum.common.length) {
      box.appendChild(h('h3', { text: 'Common to every spectrum of this sample' }));
      box.appendChild(kvTable(sum.common));
    }
    if (sum.varying.length) {
      box.appendChild(h('h3', { text: 'What differs' }));
      var tb = h('table', { class: 'grid' }), hd = h('tr', null, h('th', { text: 'Spectrum' }));
      sum.varying.forEach(function (k) { hd.appendChild(h('th', { text: k })); });
      tb.appendChild(hd);
      sm.regions.forEach(function (r) {
        var tr = h('tr', null, h('td', { text: r.level !== null && r.level !== undefined ? r.name + ' · L' + r.level : r.name }));
        sum.varying.forEach(function (k) { tr.appendChild(h('td', { text: r.meta[k] === undefined ? '' : r.meta[k] })); });
        tb.appendChild(tr);
      });
      box.appendChild(h('div', { class: 'scroll' }, tb));
    }
    if (sm.note) box.appendChild(h('p', { class: 'note', text: 'Note: ' + sm.note }));
  }

  function renderNotes() {
    var box = clear($('tab-notes')), d = S.data, any = false;
    if (d.details.summary.trim()) {
      any = true;
      box.appendChild(h('h2', { text: 'Summary' }));
      V.paragraphs(d.details.summary).forEach(function (p) { box.appendChild(h('p', { class: 'note', text: p })); });
    }
    if (d.calibration.trim()) {
      any = true;
      box.appendChild(h('h2', { text: 'Energy calibration' }));
      box.appendChild(h('p', { class: 'note', text: d.calibration }));
    }
    var notes = [];
    d.samples.forEach(function (s) {
      if (s.note) notes.push([s.name || '(unnamed)', s.note]);
      s.regions.forEach(function (r) { if (r.note) notes.push([(s.name ? s.name + ' – ' : '') + r.name, r.note]); });
    });
    if (notes.length) {
      any = true;
      box.appendChild(h('h2', { text: 'Notes on samples and spectra' }));
      box.appendChild(kvTable(notes));
    }
    box.appendChild(h('h2', { text: 'Source files' }));
    box.appendChild(kvTable(d.files.map(function (f) { return [f.name, f.format]; })));
    if (!any) box.insertBefore(h('p', { class: 'muted', text: 'No notes were written for this experiment.' }), box.firstChild);
  }

  function renderMethods() {
    var box = clear($('tab-methods'));
    var pre = h('div', { class: 'prose', id: 'methodsText', text: S.data.methods });
    var btn = h('button', { type: 'button', text: 'Copy text' });
    btn.addEventListener('click', function () {
      var done = function () { btn.textContent = 'Copied'; };
      var fail = function () {
        var r = document.createRange(); r.selectNodeContents(pre);
        var sel = G.getSelection(); sel.removeAllRanges(); sel.addRange(r);
        btn.textContent = 'Selected: press Ctrl+C';
      };
      if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(S.data.methods).then(done, fail);
      else fail();
    });
    box.appendChild(pre); box.appendChild(btn);
  }

  /* --------------------------------------------------------- holder photo */
  var photoCache = {};
  function currentHolder() { return S.data.holders[S.holderIdx] || null; }
  function hotSamples() {
    var hot = {};
    S.specs.forEach(function (s) { if (S.ticked.has(s.id) || isSelected(s)) hot[s.sample.name] = true; });
    return hot;
  }
  function renderHolder() {
    var box = clear($('tab-holder')), hs = S.data.holders;
    if (hs.length > 1) {
      var sel = h('select', { 'aria-label': 'Holder photo' });
      hs.forEach(function (x, i) { sel.appendChild(h('option', { value: String(i), text: x.file })); });
      sel.addEventListener('change', function () { S.holderIdx = +sel.value; drawHolder(); });
      box.appendChild(h('p', null, sel));
    }
    box.appendChild(h('div', { class: 'holder-wrap' }, h('canvas', { id: 'holderCanvas', 'aria-label': 'Holder photo with analysis positions', role: 'img' })));
    box.appendChild(h('div', { class: 'holder-info', id: 'holderInfo' }));
    var cv = $('holderCanvas');
    cv.addEventListener('click', function (e) {
      var hd = currentHolder(), lay = cv._lay;
      if (!hd || !lay) return;
      var rect = cv.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top;
      var best = null, bd = 18;
      Object.keys(hd.points).forEach(function (name) {
        var p = hd.points[name], d = Math.hypot(p[0] * lay.k - x, p[1] * lay.k - y);
        if (d <= bd) { bd = d; best = name; }
      });
      S.holderHot = best;
      var sm = S.data.samples.filter(function (s) { return s.name === best; })[0];
      if (sm) select({ kind: 'sample', id: sm.id }); else drawHolder();
    });
  }
  function drawHolder() {
    var hd = currentHolder(), cv = $('holderCanvas');
    if (!hd || !cv) return;
    var draw = function (img) {
      var box = cv.parentNode.clientWidth || 700, k = Math.min(1, box / hd.w) ;
      var dpr = G.devicePixelRatio || 1;
      cv.style.width = Math.round(hd.w * k) + 'px'; cv.style.height = Math.round(hd.h * k) + 'px';
      cv.width = Math.round(hd.w * k * dpr); cv.height = Math.round(hd.h * k * dpr);
      var ctx = cv.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.drawImage(img, 0, 0, hd.w * k, hd.h * k);
      cv._lay = { k: k };
      var hot = hotSamples();
      ctx.font = '12px system-ui, "Segoe UI", Helvetica, Arial, sans-serif'; ctx.textBaseline = 'middle';
      var names = Object.keys(hd.points), placed = [];
      names.sort(function (a, b) { return (hot[b] ? 1 : 0) - (hot[a] ? 1 : 0); });
      names.forEach(function (name) {
        var p = hd.points[name], x = p[0] * k, y = p[1] * k, on = !!hot[name];
        var col = on ? '#FF4D4D' : '#19E0FF', r = on ? 9 : 7;
        ctx.lineWidth = (on ? 2.4 : 1.8) + 2.6; ctx.strokeStyle = '#0B1116';
        ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.stroke();
        ctx.lineWidth = on ? 2.4 : 1.8; ctx.strokeStyle = col;
        ctx.beginPath(); ctx.arc(x, y, r, 0, 6.2832); ctx.stroke();
        var text = name || '(unnamed)', w = ctx.measureText(text).width;
        var spots = [[r + 4, 10, 'left'], [r + 4, -10, 'left'], [-r - 4, 10, 'right'], [-r - 4, -10, 'right']], at = spots[0];
        for (var s = 0; s < spots.length; s++) {
          var lx = x + spots[s][0], ly = y + spots[s][1], x0 = spots[s][2] === 'left' ? lx : lx - w;
          var box2 = [x0 - 2, ly - 8, w + 4, 16];
          var hit = placed.some(function (b) { return box2[0] < b[0] + b[2] && box2[0] + box2[2] > b[0] && box2[1] < b[1] + b[3] && box2[1] + box2[3] > b[1]; });
          if (!hit) { at = spots[s]; placed.push(box2); break; }
          if (s === spots.length - 1) placed.push(box2);
        }
        ctx.textAlign = at[2]; ctx.font = (on ? 'bold ' : '') + '12px system-ui, "Segoe UI", Helvetica, Arial, sans-serif';
        ctx.lineWidth = 3.2; ctx.strokeStyle = '#0B1116'; ctx.lineJoin = 'round';
        ctx.strokeText(text, x + at[0], y + at[1]);
        ctx.fillStyle = col; ctx.fillText(text, x + at[0], y + at[1]);
      });
      var info = clear($('holderInfo'));
      if (!names.length) {
        info.appendChild(h('span', { class: 'muted', text: 'This file has no calibrated analysis positions for the photo.' }));
      } else if (S.holderHot) {
        var sm = S.data.samples.filter(function (s) { return s.name === S.holderHot; })[0];
        if (sm) {
          var b = h('button', { type: 'button', text: 'Show the spectra of ' + (sm.name || '(unnamed)') });
          b.addEventListener('click', function () {
            tickOnly(sm.regions.map(function (r) { return r.id; }));
            showTab('plot');
          });
          info.appendChild(h('span', { text: (sm.name || '(unnamed)') + ' · ' + sm.regions.length + ' spectra   ' }));
          info.appendChild(b);
        }
      } else {
        info.appendChild(h('span', { class: 'muted', text: 'Click a marker to select that sample.' }));
      }
    };
    var cached = photoCache[hd.file];
    if (cached && cached.complete) { draw(cached); return; }
    var img = new Image();
    img.onload = function () { photoCache[hd.file] = img; draw(img); };
    img.src = hd.photo;
  }

  /* ------------------------------------------------------------ download */
  function downloadCsv() {
    var specs = S.specs.filter(function (s) { return S.ticked.has(s.id); });
    if (!specs.length) { $('notes').textContent = 'Tick some spectra first.'; return; }
    var blob = new Blob(['﻿' + V.buildCsv(specs)], { type: 'text/csv;charset=utf-8' });
    var a = h('a', { href: URL.createObjectURL(blob), download: 'spectra.csv' });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  /* ---------------------------------------------------------------- setup */
  function init(data) {
    S.data = data;
    S.specs = V.prepare(data);
    S.specs.forEach(function (s) { S.byId[s.id] = s; });
    var d = data.details;
    $('title').textContent = d.title || 'Experiment data browser';
    document.title = $('title').textContent;
    $('subtitle').textContent = [d.customer, d.reference, d.operator, d.date].filter(Boolean).join('  ·  ');
    $('foot').textContent = 'Made with ' + data.tool + ' on ' + data.generated.replace('T', ' ') +
      '. Self-contained: it needs no network and opens in any modern browser.';
    buildTree();
    buildTabs();
    renderFigures(); renderNotes(); renderMethods(); renderHolder(); renderMeta();
    $('boot').hidden = true; $('app').hidden = false;
    showTab('plot');
    applyTheme();

    $('filter').addEventListener('input', function (e) { S.filter = e.target.value; applyFilter(); });
    $('untick').addEventListener('click', function () { tickOnly([]); });
    $('mode').addEventListener('change', function (e) { S.mode = e.target.value; requestRender(); });
    $('norm').addEventListener('change', function (e) { S.norm = e.target.value; requestRender(); });
    $('offset').addEventListener('input', function (e) { S.offset = +e.target.value; requestRender(); });
    $('scale').addEventListener('change', function (e) {
      S.scale = e.target.value;
      S.panels.forEach(function (p) { p.zoom = null; });
      requestRender();
    });
    $('resetzoom').addEventListener('click', function () { S.panels.forEach(function (p) { p.zoom = null; }); requestRender(); });
    $('csv').addEventListener('click', downloadCsv);
    $('levelOn').addEventListener('change', function (e) { S.levelOn = e.target.checked; requestRender(); });
    $('level').addEventListener('input', function (e) { S.levelIdx = +e.target.value; requestRender(); });
    $('theme').addEventListener('change', function (e) { S.theme = e.target.value; applyTheme(); });
    $('print').addEventListener('click', function () { G.print(); });
    G.addEventListener('beforeprint', function () { S.printing = true; applyTheme(); render(); if (S.tab === 'holder') drawHolder(); });
    G.addEventListener('afterprint', function () { S.printing = false; applyTheme(); });
    if (G.matchMedia) {
      var mq = G.matchMedia('(prefers-color-scheme: dark)');
      if (mq.addEventListener) mq.addEventListener('change', function () { if (S.theme === 'auto') applyTheme(); });
    }
    if (G.ResizeObserver) {
      new G.ResizeObserver(function () { requestRender(); if (S.tab === 'holder') drawHolder(); }).observe($('panels'));
    } else G.addEventListener('resize', requestRender);
    /* start with something on screen: the first sample, all of its spectra */
    if (data.samples.length) {
      var first = data.samples[0];
      setTicked(first.regions.map(function (r) { return r.id; }), true);
    }
  }
  G.XPSViewerState = S;

  var el = $('xps-data');
  if (!el) return;
  V.decode(el.textContent.trim()).then(init).catch(function (err) {
    var b = $('boot'), old = typeof DecompressionStream === 'undefined';
    b.className = 'boot error';
    b.textContent = old
      ? 'This browser is too old to open this page. Use Chrome or Edge 80+, Firefox 113+ or Safari 16.4+.'
      : 'The data in this file could not be read (' + (err && err.message ? err.message : err) +
        '). The file may have been damaged in transit: ask for a fresh copy.';
  });
})(typeof globalThis !== 'undefined' ? globalThis : window);
