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
      V.fitCsvColumns(s, pre).forEach(function (c) { cols.push(c); });
      maxlen = Math.max(maxlen, s.y.length);
    });
    var lines = [cols.map(function (c) { return V.csvField(c[0]); }).join(',')];
    for (var i = 0; i < maxlen; i++) {
      lines.push(cols.map(function (c) {
        var v = c[1][i];
        return i < c[1].length && v !== null && v !== undefined && v === v ? String(v) : '';
      }).join(','));
    }
    return lines.join('\r\n') + '\r\n';
  };

  /* ------------------------------------------------------------ CasaXPS fits */
  /* A fit arrives as rows (one per fit region: RSF, area, limits, components)
     and, per row, curves from the region's first point on (`i0`): background,
     envelope and one curve per component, in the spectrum's own counts. The
     numbers were worked out by the desktop app; the page only draws them. */
  V.FIT_LAYERS = ['components', 'envelope', 'background', 'residual'];
  V.curveFull = function (cur, curve, n) {      /* a curve on every point, null outside */
    if (!cur || !curve) return null;
    var out = new Array(n);
    for (var i = 0; i < n; i++) out[i] = null;
    for (var k = 0; k < curve.length && cur.i0 + k < n; k++) out[cur.i0 + k] = curve[k];
    return out;
  };
  V.fitRows = function (reg) { return reg && reg.fit ? reg.fit.rows : []; };
  /* the chemical states of a spectrum's fit in first-appearance order, with a
     colour slot each (what the app's legend does) */
  V.fitStates = function (reg) {
    var out = [], seen = {};
    V.fitRows(reg).forEach(function (row) {
      row.components.forEach(function (c) {
        if (!(c.gk in seen)) { seen[c.gk] = out.length; out.push({ gk: c.gk, name: c.state, slot: out.length }); }
      });
    });
    return out;
  };
  V.residual = function (y, env) {              /* data - envelope, null where there is no envelope */
    return y.map(function (v, i) { return env && env[i] !== null && env[i] !== undefined ? v - env[i] : null; });
  };
  /* ------------------------------------------------------- quantification */
  /* Atomic percent from CasaXPS's own areas and RSFs; mirrors quant.py (the
     tests compare both on the same rows). Rows of one sample (and one depth
     level) are normalised together. */
  V.QUANT_HEADER = ['Sample', 'Level', 'Spectrum', 'Region', 'Background', 'RSF', 'Area (counts/s.eV)',
                    'Area / RSF', 'at %', 'State', 'State at %', 'Note'];
  /* the fit rows of these spectra grouped by sample and level, in order of appearance;
     an entry's key is stable, so a page can remember which rows are ticked */
  V.quantGroups = function (specs) {
    var groups = [], by = {};
    specs.forEach(function (s) {
      V.fitRows(s.reg).forEach(function (row, ri) {
        var lv = s.reg.level === undefined ? null : s.reg.level, k = s.sample.id + '|' + lv;
        if (!by[k]) { by[k] = { sample: s.sample.name || '', sid: s.sample.id, level: lv, etch: s.reg.etch, entries: [] }; groups.push(by[k]); }
        by[k].entries.push({ key: s.id + ':' + ri, spectrum: s.name, row: row, spec: s });
      });
    });
    return groups;
  };
  V.quantNormalise = function (rows, include, transmission) {
    var out = rows.map(function (row, i) {
      var area = transmission && row.area_t !== null && row.area_t !== undefined ? row.area_t : row.area;
      var res = { corrected: null, at: null, why: '' };
      if (include && include[i] === false) res.why = 'not included';
      else if (!row.rsf || row.rsf <= 0) res.why = 'no RSF';
      else if (area === null || area === undefined || !(area > 0)) res.why = 'no area';
      else res.corrected = area / row.rsf;
      return res;
    });
    var total = out.reduce(function (a, x) { return a + (x.corrected === null ? 0 : x.corrected); }, 0);
    out.forEach(function (x) { if (x.corrected !== null && total > 0) x.at = 100 * x.corrected / total; });
    return out;
  };
  /* the chemical states of one row: each one's share of the positive component area */
  V.quantStates = function (row, at) {
    var groups = [], by = {};
    (row.components || []).forEach(function (c) {
      var g = by[c.gk];
      if (!g) { g = by[c.gk] = { name: c.state, area: 0 }; groups.push(g); }
      g.area += Math.max(0, c.area || 0);
    });
    var tot = groups.reduce(function (a, g) { return a + g.area; }, 0);
    if (!(tot > 0)) return [];
    return groups.map(function (g) {
      return { name: g.name, frac: g.area / tot, at: at === null || at === undefined ? null : at * g.area / tot };
    });
  };
  function sig6(v) { return v === null || v === undefined || v !== v ? '' : String(+v.toPrecision(6)); }
  /* the table as rows of cells, one per region and one per chemical state under it;
     `inc` maps an entry's key to false when it is unticked */
  V.quantTable = function (groups, inc, transmission) {
    var rows = [V.QUANT_HEADER.slice()];
    groups.forEach(function (g) {
      var res = V.quantNormalise(g.entries.map(function (e) { return e.row; }),
        g.entries.map(function (e) { return !(inc && inc[e.key] === false); }), transmission);
      var lv = g.level === null || g.level === undefined ? '' : String(g.level);
      g.entries.forEach(function (e, i) {
        var row = e.row, x = res[i];
        var area = transmission && row.area_t !== null && row.area_t !== undefined ? row.area_t : row.area;
        rows.push([g.sample, lv, e.spectrum, row.region, row.background || '', sig6(row.rsf), sig6(area),
                   sig6(x.corrected), sig6(x.at), '', '', x.why]);
        if (x.at !== null) {
          V.quantStates(row, x.at).forEach(function (st) {
            rows.push([g.sample, lv, e.spectrum, row.region, '', '', '', '', '', st.name, sig6(st.at), '']);
          });
        }
      });
    });
    return rows;
  };
  V.quantCsv = function (groups, inc, transmission) {
    return V.quantTable(groups, inc, transmission).map(function (r) {
      return r.map(V.csvField).join(',');
    }).join('\r\n') + '\r\n';
  };

  /* ---------------------------------------------------------- depth profiles */
  /* mirrors quant.profile: one group per depth level of a sample (from quantGroups,
     in depth order); each level is normalised on its own. mode: 'element' (at % of
     each region), 'state' (at % of each chemical state) or 'share' (a state's % of its
     own region). Values are null where a region is missing, unticked or has no RSF. */
  V.profile = function (groups, mode, inc, transmission) {
    var series = {}, order = [];
    groups.forEach(function (g, gi) {
      var res = V.quantNormalise(g.entries.map(function (e) { return e.row; }),
        g.entries.map(function (e) { return !(inc && inc[e.key] === false); }), transmission), seen = {};
      g.entries.forEach(function (e, i) {
        var x = res[i];
        if (x.at === null) return;
        var items = mode === 'element' ? [[e.row.region, x.at]] :
          V.quantStates(e.row, x.at).map(function (st) { return [e.row.region + ': ' + st.name, mode === 'state' ? st.at : 100 * st.frac]; });
        items.forEach(function (it) {
          if (seen[it[0]]) return;
          seen[it[0]] = true;
          if (!series[it[0]]) { series[it[0]] = groups.map(function () { return null; }); order.push(it[0]); }
          series[it[0]][gi] = it[1];
        });
      });
    });
    return { levels: groups.map(function (g) { return g.level; }),
             series: order.map(function (n) { return { name: n, values: series[n] }; }) };
  };
  /* where a depth level sits: its number, etch time and, when the sputter settings are
     known, depth and ion fluence (the desktop app writes those into the metadata) */
  V.levelInfo = function (reg) {
    var num = function (k) {
      var v = reg.meta && reg.meta[k] !== undefined ? parseFloat(reg.meta[k]) : NaN;
      return isFinite(v) ? v : null;
    };
    return { level: reg.level, etch: reg.etch === undefined ? null : reg.etch,
             depth: num('Depth (nm)'), fluence: num('Fluence (ions/cm²)') };
  };
  /* the horizontal axes a set of levels can support, best first */
  V.profileAxes = function (infos) {
    var out = [], distinct = function (a) {
      return a.every(function (v) { return v !== null && v !== undefined; }) && a.some(function (v) { return v !== a[0]; });
    };
    [['depth', 'Depth (nm)'], ['etch', 'Etch time (s)'], ['fluence', 'Ion fluence (ions/cm²)'], ['level', 'Level']].forEach(function (a) {
      var vals = infos.map(function (i) { return i[a[0]]; });
      if (distinct(vals)) out.push({ id: a[0], label: a[1], values: vals });
    });
    return out;
  };
  /* the peak maximum of each spectrum at each level (needs no fit); `specs` are one
     sample's spectra with levels */
  V.peakMaxSeries = function (specs) {
    var levels = [], series = {}, order = [];
    specs.forEach(function (s) { if (levels.indexOf(s.reg.level) < 0) levels.push(s.reg.level); });
    levels.sort(function (a, b) { return a - b; });
    specs.forEach(function (s) {
      var k = s.name;
      if (!series[k]) { series[k] = levels.map(function () { return null; }); order.push(k); }
      var i = levels.indexOf(s.reg.level);
      if (series[k][i] === null) series[k][i] = Math.max.apply(null, s.y);
    });
    return { levels: levels, series: order.map(function (n) { return { name: n, values: series[n] }; }) };
  };
  /* the profile as rows of cells: level, whichever of etch time / depth / fluence the
     levels have, then a column per series */
  V.profileTable = function (prof, infos) {
    var cols = [['Level', 'level'], ['Etch time (s)', 'etch'], ['Depth (nm)', 'depth'], ['Ion fluence (ions/cm²)', 'fluence']]
      .filter(function (c) { return infos.some(function (i) { return i[c[1]] !== null && i[c[1]] !== undefined; }); });
    var rows = [cols.map(function (c) { return c[0]; }).concat(prof.series.map(function (s) { return s.name; }))];
    prof.levels.forEach(function (lv, i) {
      rows.push(cols.map(function (c) { return sig6(infos[i][c[1]]); }).concat(prof.series.map(function (s) { return sig6(s.values[i]); })));
    });
    return rows;
  };

  /* CSV columns of a spectrum's fit, named as the app's export names them */
  V.fitCsvColumns = function (s, pre) {
    var rows = V.fitRows(s.reg).filter(function (r) { return r.curve; }), cols = [], n = s.y.length;
    rows.forEach(function (row) {
      var tag = (pre || '') + s.name + ' fit' + (rows.length > 1 ? ' [' + row.region + ']' : '');
      var cur = row.curve;
      if (cur.bg) cols.push([tag + ': background', V.curveFull(cur, cur.bg, n)]);
      row.components.forEach(function (c, j) {
        if (cur.comps[j]) cols.push([tag + ': ' + c.name, V.curveFull(cur, cur.comps[j], n)]);
      });
      if (cur.env) cols.push([tag + ': envelope', V.curveFull(cur, cur.env, n)]);
    });
    return cols;
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

  /* ------------------------------------------------------------- SnapMaps */
  /* A map arrives as 16-bit steps of m.q counts, [row][column][channel],
     deflated. The functions below mirror snapmap.py so the page can redraw a
     map for any energy window and area; tests compare them with Python. */
  V.decodeMap = function (m) {
    if (typeof DecompressionStream === 'undefined') {
      return Promise.reject(new Error('This browser has no DecompressionStream'));
    }
    var stream = new Blob([V.b64ToBytes(m.z)]).stream()
      .pipeThrough(new DecompressionStream('deflate'));
    return new Response(stream).arrayBuffer().then(function (buf) {
      var data = new Uint16Array(buf);
      if (data.length !== m.nx * m.ny * m.n) throw new Error('the map data has the wrong size');
      return data;
    });
  };
  V.mapChannels = function (energy, lo, hi) {
    var a = Math.min(lo, hi), b = Math.max(lo, hi), idx = [];
    for (var i = 0; i < energy.length; i++) if (energy[i] >= a && energy[i] <= b) idx.push(i);
    return idx;
  };
  /* counts summed over an energy window, one value per pixel; `background`
     takes a straight line through the ends of the window off first */
  V.mapImage = function (m, data, energy, lo, hi, background) {
    var np = m.nx * m.ny, out = new Float64Array(np), idx = V.mapChannels(energy, lo, hi), n = idx.length;
    if (!n) return out;
    var k = Math.max(1, Math.floor(n / 8)), bg = !!background && n >= 4, p, j, base, s, a, b, t;
    for (p = 0; p < np; p++) {
      base = p * m.n; s = 0;
      if (bg) {
        a = 0; b = 0;
        for (j = 0; j < k; j++) { a += data[base + idx[j]]; b += data[base + idx[n - 1 - j]]; }
        a = a * m.q / k; b = b * m.q / k;
        for (j = 0; j < n; j++) s += data[base + idx[j]] * m.q - (a + (b - a) * (j / (n - 1)));
      } else {
        for (j = 0; j < n; j++) s += data[base + idx[j]];
        s *= m.q;
      }
      out[p] = s;
    }
    return out;
  };
  /* boolean mask (1 = in) of the pixels whose centres lie in a rectangle (µm) */
  V.rectMask = function (m, xa, ya, xb, yb) {
    var mask = new Uint8Array(m.nx * m.ny), n = 0, ix, iy, x, y;
    var x0 = Math.min(xa, xb), x1 = Math.max(xa, xb), y0 = Math.min(ya, yb), y1 = Math.max(ya, yb);
    for (iy = 0; iy < m.ny; iy++) {
      y = m.y0 + iy * m.dy;
      if (y < y0 || y > y1) continue;
      for (ix = 0; ix < m.nx; ix++) {
        x = m.x0 + ix * m.dx;
        if (x >= x0 && x <= x1) { mask[iy * m.nx + ix] = 1; n++; }
      }
    }
    return { mask: mask, count: n };
  };
  V.pixelAt = function (m, x, y) {
    var ix = m.dx ? Math.round((x - m.x0) / m.dx) : -1, iy = m.dy ? Math.round((y - m.y0) / m.dy) : -1;
    return ix >= 0 && ix < m.nx && iy >= 0 && iy < m.ny ? [ix, iy] : null;
  };
  /* counts per pixel at every channel, over a mask (or the whole map) */
  V.meanSpectrum = function (m, data, mask) {
    var out = new Float64Array(m.n), np = m.nx * m.ny, cnt = 0, p, c, base;
    for (p = 0; p < np; p++) {
      if (mask && !mask[p]) continue;
      cnt++; base = p * m.n;
      for (c = 0; c < m.n; c++) out[c] += data[base + c];
    }
    for (c = 0; c < m.n; c++) out[c] = cnt ? out[c] * m.q / cnt : 0;
    return out;
  };
  /* the window round the strongest peak (see snapmap.default_window) */
  V.defaultWindow = function (energy, y, fraction, minWidth) {
    fraction = fraction === undefined ? 0.3 : fraction;
    minWidth = minWidth === undefined ? 2.0 : minWidth;
    var n = y.length, i, lo = Infinity, hi = -Infinity;
    for (i = 0; i < n; i++) { if (energy[i] < lo) lo = energy[i]; if (energy[i] > hi) hi = energy[i]; }
    if (n < 10) return [lo, hi];
    var ys = new Array(n), res = new Array(n), score = new Array(n);
    for (i = 0; i < n; i++) ys[i] = (y[Math.max(0, i - 1)] + y[i] + y[Math.min(n - 1, i + 1)]) / 3;
    var k = Math.max(2, Math.floor(n / 20)), a0 = 0, b0 = 0;
    for (i = 0; i < k; i++) { a0 += ys[i]; b0 += ys[n - 1 - i]; }
    a0 /= k; b0 /= k;
    for (i = 0; i < n; i++) {
      var x = -1 + 2 * i / (n - 1);
      res[i] = ys[i] - (a0 + (b0 - a0) * (i / (n - 1)));
      score[i] = res[i] * Math.exp(-Math.pow(x / 0.6, 2));
    }
    var tenth = Math.floor(n / 10), best = -1;
    for (i = 0; i < n; i++) {
      if (i < tenth || i >= n - tenth) score[i] = -Infinity;
      if (best < 0 || score[i] > score[best]) best = i;
    }
    if (!(res[best] > 0)) return [lo, hi];
    var thr = fraction * res[best], a = best, b = best;
    while (a > 0 && res[a - 1] >= thr) a--;
    while (b < n - 1 && res[b + 1] >= thr) b++;
    a = Math.max(0, a - 1); b = Math.min(n - 1, b + 1);
    var step = Math.abs(energy[n - 1] - energy[0]) / (n - 1), want = step > 0 ? Math.round(minWidth / step) : 0;
    while (b - a < want && (a > 0 || b < n - 1)) { a = Math.max(0, a - 1); b = Math.min(n - 1, b + 1); }
    return [Math.min(energy[a], energy[b]), Math.max(energy[a], energy[b])];
  };
  /* colour range of an image: 1st and 99th percentile (linear, as numpy) */
  V.percentile = function (sorted, p) {
    var pos = (sorted.length - 1) * p / 100, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  };
  V.colourRange = function (img, low, high) {
    var a = [], i;
    for (i = 0; i < img.length; i++) if (isFinite(img[i])) a.push(img[i]);
    if (!a.length) return [0, 1];
    a.sort(function (x, y) { return x - y; });
    var lo = V.percentile(a, low === undefined ? 1 : low), hi = V.percentile(a, high === undefined ? 99 : high);
    if (hi <= lo) { lo = a[0]; hi = a[a.length - 1]; }
    if (hi <= lo) hi = lo + 1;
    return [lo, hi];
  };
  /* colour scales as anchor colours (close to matplotlib's, not identical) */
  V.SCALES = {
    Viridis: ['#440154', '#482878', '#3E4A89', '#31688E', '#26828E', '#1F9E89', '#35B779', '#6DCD59', '#B4DE2C', '#FDE725'],
    Magma: ['#000004', '#180F3E', '#451077', '#721F81', '#9F2F7F', '#CD4071', '#F1605D', '#FD9567', '#FEC98D', '#FCFDBF'],
    Cividis: ['#00204D', '#00336F', '#39486B', '#575C6C', '#707173', '#8A8779', '#A69D75', '#C4B56C', '#E4CF5B', '#FFEA46'],
    Greys: ['#0A0A0A', '#FFFFFF']
  };
  V.scaleColour = function (name, t) {      /* t in [0, 1] -> [r, g, b] */
    var st = V.SCALES[name] || V.SCALES.Viridis;
    t = Math.max(0, Math.min(1, t)) * (st.length - 1);
    var i = Math.min(st.length - 2, Math.floor(t)), f = t - i;
    var a = V.hexToRgb(st[i]), b = V.hexToRgb(st[i + 1]);
    return [0, 1, 2].map(function (k) { return a[k] + (b[k] - a[k]) * f; });
  };
  /* the map values as CSV: a header row of X (µm), then one row per Y (µm) */
  V.mapCsv = function (m, img) {
    var head = ['Y/X (um)'], rows, ix, iy;
    for (ix = 0; ix < m.nx; ix++) head.push(String(+(m.x0 + ix * m.dx).toPrecision(6)));
    rows = [head.join(',')];
    for (iy = 0; iy < m.ny; iy++) {
      var r = [String(+(m.y0 + iy * m.dy).toPrecision(6))];
      for (ix = 0; ix < m.nx; ix++) r.push(String(+img[iy * m.nx + ix].toPrecision(7)));
      rows.push(r.join(','));
    }
    return rows.join('\r\n') + '\r\n';
  };

  G.XPSViewer = V;
  if (typeof module !== 'undefined' && module.exports) module.exports = V;
  if (typeof document === 'undefined') return;

  /* ============================================================ the page */
  var S = { data: null, specs: [], byId: {}, ticked: new Set(), selected: null, mode: 'stack',
            norm: 'none', offset: 0.6, scale: 'Binding', levelOn: false, levelIdx: 0, levels: [],
            panels: new Map(), theme: 'auto', printing: false, nodes: [], holderIdx: 0,
            holderHot: null, tab: 'plot', filter: '', camIdx: 0, mapById: {}, camById: {},
            fit: { components: true, envelope: true, background: true, residual: false, hidden: {} },
            q: { include: {}, transmission: false, level: {} },
            d: { sample: null, mode: 'element', axis: null, last: null },
            M: { id: null, data: null, energy: null, total: null, win: null, mask: null, count: 0,
                 scale: 'Viridis', bg: false, overlay: false, alpha: 0.65, loading: false, drag: null } };
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
    redrawTab();
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
    var row = h('div', { class: 'row' }, h('button', { class: 'tw leaf', tabindex: '-1', 'aria-hidden': 'true', text: '▸' }), chk, sw, lbl);
    if (spec && spec.reg.map) {                 /* a SnapMap: offer its pixels */
      var mb = h('button', { type: 'button', class: 'mapbtn', text: 'map', title: 'Open the SnapMap (where the signal comes from)' });
      mb.addEventListener('click', function () { showTab('maps'); openMap(spec.reg.map); });
      row.appendChild(mb);
    }
    var li = h('li', null, row);
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
    redrawTab();
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
    followSelection(sel);
    refreshSelection();
    renderMeta();
    requestRender();
    redrawTab();
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
    var anyFit = false;
    S.panels.forEach(function (p) {
      var s = singleFit(p.group);
      if (s) {
        anyFit = true;
        (s.reg.fit.notes || []).forEach(function (t) { notes.push('fit: ' + t); });
      }
    });
    $('fitbar').hidden = !anyFit;
    $('notes').textContent = notes.join('; ');
    refreshSwatches();
    var cols = colours(), cmap = traceColourMap();
    S.panels.forEach(function (p) { drawPanel(p, cols, cmap); updateFitBox(p); });
  }

  /* ------------------------------------------------------------ plot: fits */
  /* a fit is drawn (and tabulated) on a panel that shows one spectrum */
  function singleFit(g) {
    return g && g.items.length === 1 && V.fitRows(g.items[0].reg).length ? g.items[0] : null;
  }
  function fitColours() {
    var c = cycle();
    return c.length > 1 ? c.slice(1) : c;
  }
  /* the fit's curves on every point of the spectrum, scaled like the data */
  function fitCurves(s, f) {
    var n = s.y.length, sc = function (a) { return a ? a.map(function (v) { return v === null ? null : v / f; }) : null; };
    return V.fitRows(s.reg).map(function (row, ri) {
      var cur = row.curve;
      if (!cur) return { row: row, ri: ri, bg: null, env: null, comps: [], res: null };
      var env = sc(V.curveFull(cur, cur.env, n));
      return { row: row, ri: ri, bg: sc(V.curveFull(cur, cur.bg, n)), env: env,
               comps: cur.comps.map(function (c) { return sc(V.curveFull(cur, c, n)); }),
               res: env ? V.residual(s.y.map(function (v) { return v / f; }), env) : null };
    });
  }
  function fmtN(v, d) { return v === null || v === undefined || v !== v ? '' : v.toFixed(d); }
  function updateFitBox(p) {
    var s = singleFit(p.group);
    if (!s) { if (p.fitbox) { p.wrap.removeChild(p.fitbox); p.fitbox = null; } return; }
    if (!p.fitbox) { p.fitbox = h('div', { class: 'fitbox' }); p.wrap.appendChild(p.fitbox); }
    var box = clear(p.fitbox), st = V.fitStates(s.reg), slot = {}, cols = fitColours(), kin = S.scale === 'Kinetic' && s.reg.hv;
    st.forEach(function (x) { slot[x.gk] = cols[x.slot % cols.length]; });
    var rows = s.reg.fit.rows, shown = 0;
    rows.forEach(function (row, ri) {
      if (shown >= 8) return;
      shown++;
      var head = [row.region, row.background + ' background'];
      if (row.rsf) head.push('RSF ' + +row.rsf.toPrecision(4));
      if (row.area !== null && row.area !== undefined) head.push('area ' + Math.round(row.area).toLocaleString('en-US') + ' counts/s·eV' + (row.basis === 'components' ? ' (sum of components)' : ''));
      if (row.rms !== null && row.rms !== undefined) head.push('fit rms ' + (row.rms * 100).toFixed(1) + ' % of the range');
      box.appendChild(h('div', { class: 'fit-head', text: head.join('  ·  ') }));
      if (!row.components.length) return;
      var tot = row.components.reduce(function (a, c) { return a + Math.max(0, c.area || 0); }, 0);
      var tb = h('tbody');
      row.components.forEach(function (c, j) {
        var key = ri + ':' + j, off = !!S.fit.hidden[key];
        var cb = h('input', { type: 'checkbox', 'aria-label': 'Show ' + c.name });
        cb.checked = !off;
        var tr = h('tr', { class: off ? 'off' : '' },
          h('td', null, cb),
          h('td', null, h('span', { class: 'sw', style: 'background:' + (slot[c.gk] || '#888') })),
          h('td', { text: c.name }),
          h('td', { class: 'num', text: fmtN(kin ? s.reg.hv - c.be : c.be, 2) }),
          h('td', { class: 'num', text: fmtN(c.fwhm, 2) }),
          h('td', { class: 'num', text: fmtN(c.area, 1) }),
          h('td', { class: 'num', text: tot > 0 ? fmtN(100 * Math.max(0, c.area || 0) / tot, 1) : '' }),
          h('td', { text: c.shape }),
          h('td', { text: c.state !== c.name ? c.state : '' }));
        cb.addEventListener('change', function () {
          S.fit.hidden[key] = !cb.checked;
          tr.className = cb.checked ? '' : 'off';
          redraw(p);
        });
        tb.appendChild(tr);
      });
      var th = h('tr', null, h('th'), h('th'), h('th', { text: 'Component' }),
        h('th', { class: 'num', text: (kin ? 'KE' : 'BE') + ' (eV)' }), h('th', { class: 'num', text: 'FWHM (eV)' }),
        h('th', { class: 'num', text: 'Area (counts/s·eV)' }), h('th', { class: 'num', text: 'Area %' }),
        h('th', { text: 'Shape' }), h('th', { text: 'State' }));
      box.appendChild(h('div', { class: 'scroll' }, h('table', { class: 'grid' }, h('thead', null, th), tb)));
    });
    if (rows.length > shown) box.appendChild(h('div', { class: 'fit-head', text: '… and ' + (rows.length - shown) + ' more fit regions' }));
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

    var fit = singleFit(g) ? fitCurves(items[0], V.normFactor(items[0].y, S.norm)) : null;
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
    /* the residual (data - envelope) gets a band of its own under the spectrum, at true scale */
    var resBase = null, rr = 0;
    if (fit && S.fit.residual) {
      fit.forEach(function (fr) {
        if (!fr.res) return;
        for (var k = 0; k < fr.res.length; k++) {
          if (fr.res[k] === null || axes[0].x[k] < lo || axes[0].x[k] > hi) continue;
          rr = Math.max(rr, Math.abs(fr.res[k]));
        }
      });
      if (rr > 0) { resBase = ylo - rr * 1.6; ylo = resBase - rr * 1.3; }
    }
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

    /* the fit: background, components on top of it, envelope, residual */
    if (fit) drawFit(ctx, C, lay, X, Y, axes[0].x, fit, items[0], resBase, rr, font);

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
    if (fit && S.fit.components) fitLegend(ctx, C, lay, items[0], font);

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

  /* a polyline through the points that have a value; a gap starts a new stroke */
  function strokeCurve(ctx, xs, ys, X, Y) {
    var pen = false;
    ctx.beginPath();
    for (var k = 0; k < xs.length; k++) {
      if (ys[k] === null || ys[k] === undefined) { pen = false; continue; }
      if (pen) ctx.lineTo(X(xs[k]), Y(ys[k])); else { ctx.moveTo(X(xs[k]), Y(ys[k])); pen = true; }
    }
    ctx.stroke();
  }
  /* the area between two curves over each run of points where both exist */
  function fillBetween(ctx, xs, top, lo, X, Y) {
    var k = 0, n = xs.length;
    while (k < n) {
      while (k < n && (top[k] === null || lo[k] === null)) k++;
      var a = k;
      while (k < n && top[k] !== null && lo[k] !== null) k++;
      if (k - a < 2) continue;
      ctx.beginPath();
      for (var i = a; i < k; i++) { if (i === a) ctx.moveTo(X(xs[i]), Y(top[i])); else ctx.lineTo(X(xs[i]), Y(top[i])); }
      for (i = k - 1; i >= a; i--) ctx.lineTo(X(xs[i]), Y(lo[i]));
      ctx.closePath(); ctx.fill();
    }
  }
  function drawFit(ctx, C, lay, X, Y, xs, fit, s, resBase, rr, font) {
    var cols = fitColours(), slot = {};
    V.fitStates(s.reg).forEach(function (x) { slot[x.gk] = cols[x.slot % cols.length]; });
    ctx.lineJoin = 'round';
    fit.forEach(function (fr) {
      var zero = xs.map(function () { return 0; });
      if (S.fit.background && fr.bg) {
        ctx.strokeStyle = C.muted; ctx.lineWidth = 1; ctx.setLineDash([5, 3]);
        strokeCurve(ctx, xs, fr.bg, X, Y); ctx.setLineDash([]);
      }
      if (S.fit.components) {
        fr.comps.forEach(function (cv, j) {
          if (!cv || S.fit.hidden[fr.ri + ':' + j]) return;
          var c = fr.row.components[j], col = slot[c.gk] || '#888888';
          var lo = fr.bg || zero, top = cv.map(function (v, k) { return v === null || lo[k] === null ? null : lo[k] + v; });
          ctx.fillStyle = col; ctx.globalAlpha = 0.35; fillBetween(ctx, xs, top, lo, X, Y); ctx.globalAlpha = 1;
          ctx.strokeStyle = col; ctx.lineWidth = 1; strokeCurve(ctx, xs, top, X, Y);
        });
      }
      if (S.fit.envelope && fr.env) {
        ctx.strokeStyle = C.fg; ctx.lineWidth = 1.4; strokeCurve(ctx, xs, fr.env, X, Y);
      }
      if (resBase !== null && fr.res) {
        var res = fr.res.map(function (v) { return v === null ? null : resBase + v; });
        ctx.strokeStyle = C.muted; ctx.lineWidth = 0.6; ctx.setLineDash([2, 3]);
        ctx.beginPath(); ctx.moveTo(lay.l, Y(resBase)); ctx.lineTo(lay.l + lay.w, Y(resBase)); ctx.stroke(); ctx.setLineDash([]);
        ctx.strokeStyle = C.muted; ctx.lineWidth = 1; strokeCurve(ctx, xs, res, X, Y);
        ctx.fillStyle = C.muted; ctx.font = font(10); ctx.textAlign = 'left'; ctx.textBaseline = 'alphabetic';
        ctx.fillText('Residual (data − envelope)', lay.l + 6, Y(resBase + rr) - 4);
      }
    });
    ctx.lineWidth = 1;
  }
  /* the states of the fit, top left of the plot; a long list is left to the table */
  function fitLegend(ctx, C, lay, s, font) {
    var st = V.fitStates(s.reg), cols = fitColours();
    if (!st.length || st.length > 6) return;
    ctx.font = font(11); ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    st.forEach(function (x, i) {
      var y = lay.t + 12 + i * 15;
      ctx.fillStyle = cols[x.slot % cols.length]; ctx.globalAlpha = 0.5; ctx.fillRect(lay.l + 8, y - 5, 10, 10); ctx.globalAlpha = 1;
      ctx.fillStyle = C.fg;
      ctx.fillText(x.name.length > 22 ? x.name.slice(0, 21) + '…' : x.name, lay.l + 24, y);
    });
    ctx.textBaseline = 'alphabetic';
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
  var TABS = [['plot', 'Spectra'], ['quant', 'Quantification'], ['depth', 'Depth profile'], ['figures', 'Figures'], ['meta', 'Metadata'],
              ['notes', 'Notes'], ['methods', 'Methods'], ['holder', 'Holder'],
              ['cameras', 'Camera images'], ['maps', 'SnapMaps']];
  function availableTabs() {
    var d = S.data;
    return TABS.filter(function (t) {
      if (t[0] === 'figures') return d.figures.length > 0;
      if (t[0] === 'quant') return V.quantGroups(S.specs).length > 0;
      if (t[0] === 'depth') return profileSamples().length > 0;
      if (t[0] === 'holder') return d.holders.length > 0;
      if (t[0] === 'cameras') return (d.cameras || []).length > 0;
      if (t[0] === 'maps') return (d.maps || []).length > 0;
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
    redrawTab();
    if (name === 'meta') renderMeta();
    if (name === 'depth') renderDepth();
    if (name === 'quant') renderQuant();
  }
  function redrawTab() {
    if (S.tab === 'depth') drawDepth();
    else if (S.tab === 'holder') drawHolder();
    else if (S.tab === 'cameras') drawCamera();
    else if (S.tab === 'maps') { if (S.M.id) drawMapView(); else if ((S.data.maps || []).length) openMap(S.data.maps[0].id); }
  }

  /* ------------------------------------------------------- quantification tab */
  function renderQuant() {
    var box = clear($('tab-quant')), all = V.quantGroups(S.specs);
    if (!all.length) return;
    var q = S.q, hasT = all.some(function (g) { return g.entries.some(function (e) { return e.row.area_t !== null && e.row.area_t !== undefined; }); });
    box.appendChild(h('p', { class: 'muted small', text: 'Atomic % = (region area ÷ RSF) as a share of the ticked regions of the same sample. Areas and RSFs are ' +
      'CasaXPS\'s own, read from the fitted VAMAS file; nothing here is refitted. A region without an RSF is left out and says so.' }));
    var tcb = h('input', { type: 'checkbox', id: 'q-trans' });
    tcb.checked = q.transmission && hasT; tcb.disabled = !hasT;
    tcb.addEventListener('change', function () { q.transmission = tcb.checked; renderQuant(); });
    var dl = h('button', { type: 'button', text: 'Download quantification.csv' });
    dl.addEventListener('click', function () { saveText('quantification.csv', V.quantCsv(all, q.include, q.transmission && hasT)); });
    box.appendChild(h('div', { class: 'controls' },
      h('label', { class: 'field', title: hasT ? 'Divide the spectrometer transmission function out of each region area' : 'These files carry no transmission function' }, tcb, ' Divide out the transmission function'), dl));
    var bySample = [], seen = {};
    all.forEach(function (g) { if (!seen[g.sid]) { seen[g.sid] = []; bySample.push(seen[g.sid]); } seen[g.sid].push(g); });
    bySample.forEach(function (gs) {
      var sid = gs[0].sid, cur = q.level[sid];
      var g = gs.filter(function (x) { return String(x.level) === String(cur); })[0] || gs[0];
      box.appendChild(h('h2', { text: g.sample || '(unnamed)' }));
      if (gs.length > 1) {
        var sel = h('select', { 'aria-label': 'Depth level' });
        gs.forEach(function (x) {
          var o = h('option', { value: String(x.level), text: 'Level ' + x.level + (x.etch !== null && x.etch !== undefined ? ' (' + +x.etch.toPrecision(6) + ' s)' : '') });
          if (x === g) o.selected = true;
          sel.appendChild(o);
        });
        sel.addEventListener('change', function () { q.level[sid] = sel.value; renderQuant(); });
        box.appendChild(h('div', { class: 'controls' }, h('label', { class: 'field' }, 'Depth level ', sel)));
      }
      var res = V.quantNormalise(g.entries.map(function (e) { return e.row; }),
        g.entries.map(function (e) { return q.include[e.key] !== false; }), q.transmission && hasT);
      var tb = h('tbody');
      g.entries.forEach(function (e, i) {
        var row = e.row, x = res[i], off = q.include[e.key] === false;
        var cb = h('input', { type: 'checkbox', 'aria-label': 'Include ' + row.region });
        cb.checked = !off;
        cb.addEventListener('change', function () { q.include[e.key] = cb.checked; renderQuant(); });
        var area = q.transmission && hasT && row.area_t !== null && row.area_t !== undefined ? row.area_t : row.area;
        var name = row.region + (e.spectrum !== row.region ? '  (' + e.spectrum + ')' : '');
        tb.appendChild(h('tr', { class: off ? 'off' : '' },
          h('td', null, cb), h('td', { text: name }), h('td', { text: row.background }),
          h('td', { class: 'num', text: row.rsf ? String(+row.rsf.toPrecision(4)) : '' }),
          h('td', { class: 'num', text: area === null || area === undefined ? '' : Math.round(area).toLocaleString('en-US') + (row.basis === 'components' ? ' *' : '') }),
          h('td', { class: 'num', text: x.corrected === null ? '' : Math.round(x.corrected).toLocaleString('en-US') }),
          h('td', { class: 'num', text: x.at === null ? (x.why && x.why !== 'not included' ? x.why : '') : x.at.toFixed(1) })));
        if (x.at !== null) {
          V.quantStates(row, x.at).forEach(function (st) {
            tb.appendChild(h('tr', { class: 'state' }, h('td'), h('td', { text: '↳ ' + st.name }), h('td'), h('td'),
              h('td', { class: 'num', text: (100 * st.frac).toFixed(0) + ' % of region' }), h('td'), h('td', { class: 'num', text: st.at.toFixed(1) })));
          });
        }
      });
      var head = h('tr', null, h('th'), h('th', { text: 'Region' }), h('th', { text: 'Background' }), h('th', { class: 'num', text: 'RSF' }),
        h('th', { class: 'num', text: 'Area (counts/s·eV)' }), h('th', { class: 'num', text: 'Area ÷ RSF' }), h('th', { class: 'num', text: 'at %' }));
      box.appendChild(h('div', { class: 'scroll' }, h('table', { class: 'grid quant' }, h('thead', null, head), tb)));
      if (g.entries.some(function (e) { return e.row.basis === 'components'; })) {
        box.appendChild(h('p', { class: 'muted small', text: '* the sum of the fitted components, because the background of that region is not reproduced here.' }));
      }
      var reg = g.entries.length > 1 && g.entries.some(function (e) { return e.row.region === g.entries[0].row.region && e !== g.entries[0]; });
      if (reg) box.appendChild(h('p', { class: 'muted small', text: 'The same region appears more than once (for example from a survey and from its own scan): untick one to avoid counting it twice.' }));
    });
  }

  /* ---------------------------------------------------- depth profile tab */
  var DEPTH_MODES = [['element', 'Composition (at %)'], ['state', 'Chemical states (at %)'],
                     ['share', 'State share of its element (%)'], ['peak', 'Peak maximum']];
  /* the samples that have a depth profile: at least two distinct levels */
  function profileSamples() {
    var out = [];
    S.data.samples.forEach(function (sm) {
      var lv = [];
      sm.regions.forEach(function (r) { if (r.level !== null && r.level !== undefined && lv.indexOf(r.level) < 0) lv.push(r.level); });
      if (lv.length > 1) out.push(sm);
    });
    return out;
  }
  function profileOf(sm, mode) {
    var specs = S.specs.filter(function (s) { return s.sample === sm && s.reg.level !== null && s.reg.level !== undefined; });
    var infoAt = {};
    specs.forEach(function (s) { if (!infoAt[s.reg.level]) infoAt[s.reg.level] = V.levelInfo(s.reg); });
    var prof;
    if (mode === 'peak') prof = V.peakMaxSeries(specs);
    else {
      var gs = V.quantGroups(specs).filter(function (g) { return g.level !== null; }).sort(function (a, b) { return a.level - b.level; });
      prof = V.profile(gs, mode, S.q.include, S.q.transmission);
    }
    return { prof: prof, infos: prof.levels.map(function (l) { return infoAt[l]; }), specs: specs };
  }
  function renderDepth() {
    var box = clear($('tab-depth')), sms = profileSamples();
    if (!sms.length) return;
    var d = S.d;
    if (sms.indexOf(d.sample) < 0) d.sample = sms[0];
    var hasFit = V.quantGroups(S.specs.filter(function (s) { return s.sample === d.sample; })).length > 0;
    if (!hasFit && d.mode !== 'peak') d.mode = 'peak';
    var res = profileOf(d.sample, d.mode), axes = V.profileAxes(res.infos);
    if (!axes.length) axes = [{ id: 'level', label: 'Level', values: res.prof.levels }];
    if (!axes.some(function (a) { return a.id === d.axis; })) d.axis = axes[0].id;
    var axis = axes.filter(function (a) { return a.id === d.axis; })[0];

    var ctl = h('div', { class: 'controls' });
    if (sms.length > 1) {
      var ssel = h('select', { 'aria-label': 'Sample' });
      sms.forEach(function (sm) { var o = h('option', { value: sm.id, text: sm.name || '(unnamed)' }); if (sm === d.sample) o.selected = true; ssel.appendChild(o); });
      ssel.addEventListener('change', function () { d.sample = sms.filter(function (s) { return s.id === ssel.value; })[0]; renderDepth(); });
      ctl.appendChild(h('label', { class: 'field' }, 'Sample ', ssel));
    }
    var msel = h('select', { 'aria-label': 'Show' });
    DEPTH_MODES.forEach(function (m) {
      var o = h('option', { value: m[0], text: m[1] }); if (m[0] === d.mode) o.selected = true;
      if (m[0] !== 'peak' && !hasFit) o.disabled = true;
      msel.appendChild(o);
    });
    msel.addEventListener('change', function () { d.mode = msel.value; renderDepth(); });
    ctl.appendChild(h('label', { class: 'field' }, 'Show ', msel));
    var xsel = h('select', { 'aria-label': 'Horizontal axis' });
    axes.forEach(function (a) { var o = h('option', { value: a.id, text: a.label }); if (a === axis) o.selected = true; xsel.appendChild(o); });
    xsel.addEventListener('change', function () { d.axis = xsel.value; renderDepth(); });
    ctl.appendChild(h('label', { class: 'field' }, 'Against ', xsel));
    var dl = h('button', { type: 'button', text: 'Download depth_profile.csv' });
    dl.addEventListener('click', function () {
      saveText('depth_profile.csv', V.profileTable(res.prof, res.infos).map(function (r) { return r.map(V.csvField).join(','); }).join('\r\n') + '\r\n');
    });
    ctl.appendChild(dl);
    box.appendChild(ctl);
    var why = [];
    if (d.mode !== 'peak') why.push('Uses the regions ticked in the Quantification tab' + (S.q.transmission ? ', with the transmission function divided out' : '') + '.');
    if (axes.length && axes[0].id === 'level' && res.infos.some(function (i) { return i.etch !== null && i.etch !== undefined; })) {
      why.push('Etch times are all the same or not recorded, so the levels are shown by number.');
    } else if (!axes.some(function (a) { return a.id === 'depth'; })) {
      why.push('Enter the etch rate in the app (Sputter settings) to plot against depth.');
    }
    box.appendChild(h('p', { class: 'muted small', text: why.join(' ') }));
    if (!res.prof.series.length) {
      box.appendChild(h('p', { class: 'empty', text: 'Nothing to plot here: none of the ticked regions has an RSF and an area.' }));
      d.last = null;
      return;
    }
    var cv = h('canvas', { 'aria-label': 'Depth profile', role: 'img', id: 'depthCanvas' });
    var read = h('div', { class: 'readout', id: 'depthRead' });
    box.appendChild(h('div', { class: 'panel depth-panel' }, cv, read));
    d.last = { canvas: cv, read: read, res: res, axis: axis, hover: null };
    cv.addEventListener('mousemove', function (e) { d.last.hover = nearestLevel(d.last, e); depthReadout(d.last); drawDepth(); });
    cv.addEventListener('mouseleave', function () { d.last.hover = null; read.textContent = ''; drawDepth(); });
    cv.addEventListener('click', function (e) {
      var i = nearestLevel(d.last, e);
      if (i !== null) gotoLevel(d.sample, res.prof.levels[i]);
    });
    var rows = V.profileTable(res.prof, res.infos), tb = h('table', { class: 'grid quant' });
    rows.forEach(function (r, i) {
      var tr = h('tr');
      r.forEach(function (c) { tr.appendChild(h(i ? 'td' : 'th', { class: 'num', text: c })); });
      tb.appendChild(tr);
    });
    box.appendChild(h('div', { class: 'scroll' }, tb));
    drawDepth();
  }
  function nearestLevel(L, e) {
    if (!L || !L.pts) return null;
    var x = e.clientX - L.canvas.getBoundingClientRect().left, best = null, bd = Infinity;
    L.pts.forEach(function (px_, i) { var dd = Math.abs(px_ - x); if (dd < bd) { bd = dd; best = i; } });
    return bd < 40 ? best : null;
  }
  function depthReadout(L) {
    if (L.hover === null) { L.read.textContent = ''; return; }
    var i = L.hover, info = L.res.infos[i], ax = L.axis;
    var parts = ['Level ' + info.level + (ax.id !== 'level' ? ' · ' + ax.label + ' ' + sig6(ax.values[i]) : '')];
    L.res.prof.series.forEach(function (s) { if (s.values[i] !== null) parts.push(s.name + ' ' + V.fmtY(s.values[i])); });
    L.read.textContent = parts.join('   ·   ') + '   (click to open this level)';
  }
  function gotoLevel(sm, level) {
    var ids = sm.regions.map(function (r) { return r.id; });
    var lv = [];
    sm.regions.forEach(function (r) { if (r.level !== null && r.level !== undefined && lv.indexOf(r.level) < 0) lv.push(r.level); });
    lv.sort(function (a, b) { return a - b; });
    S.levelOn = true; S.levelIdx = Math.max(0, lv.indexOf(level));
    $('levelOn').checked = true;
    tickOnly(ids);
    showTab('plot');
  }
  function drawDepth() {
    var L = S.d.last;
    if (!L || S.tab !== 'depth') return;
    var cv = L.canvas, W = cv.clientWidth, H = cv.clientHeight, C = colours();
    if (!W || !H) return;
    var dpr = G.devicePixelRatio || 1;
    if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) { cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr); }
    var ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    var font = function (n, w) { return (w || '') + ' ' + n + 'px system-ui, "Segoe UI", Helvetica, Arial, sans-serif'; };
    var xs = L.axis.values.map(Number), cyc = cycle(), series = L.res.prof.series;
    var xlo = Math.min.apply(null, xs), xhi = Math.max.apply(null, xs);
    if (!(xhi > xlo)) { xlo -= 1; xhi += 1; }
    var xp = (xhi - xlo) * 0.04; xlo -= xp; xhi += xp;
    var yhi = 0;
    series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null && v > yhi) yhi = v; }); });
    yhi = yhi > 0 ? yhi * 1.08 : 1;
    var gutter = 190, lay = { l: 64, t: 16, w: Math.max(60, W - 64 - gutter), h: Math.max(60, H - 16 - 46) };
    var X = function (v) { return lay.l + (v - xlo) / (xhi - xlo) * lay.w; }, Y = function (v) { return lay.t + (1 - v / yhi) * lay.h; };
    L.pts = xs.map(X);
    ctx.strokeStyle = C.muted; ctx.fillStyle = C.muted; ctx.lineWidth = 1; ctx.font = font(11);
    ctx.beginPath(); ctx.moveTo(lay.l + 0.5, lay.t); ctx.lineTo(lay.l + 0.5, lay.t + lay.h); ctx.lineTo(lay.l + lay.w, lay.t + lay.h + 0.5); ctx.stroke();
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    V.niceTicks(0, yhi, Math.max(3, Math.round(lay.h / 50))).forEach(function (t) {
      var y = Math.round(Y(t)) + 0.5;
      ctx.strokeStyle = C.grid; ctx.beginPath(); ctx.moveTo(lay.l, y); ctx.lineTo(lay.l + lay.w, y); ctx.stroke();
      ctx.fillStyle = C.muted; ctx.fillText(V.fmtY(t), lay.l - 6, y);
    });
    ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
    var ticks = V.niceTicks(xlo, xhi, Math.max(3, Math.round(lay.w / 90)));
    ticks.forEach(function (t) { ctx.fillStyle = C.muted; ctx.fillText(V.fmtY(t), X(t), lay.t + lay.h + 16); });
    ctx.fillStyle = C.fg; ctx.font = font(12);
    ctx.fillText(L.axis.label, lay.l + lay.w / 2, lay.t + lay.h + 36);
    var mode = S.d.mode, r0 = L.res.specs[0] ? L.res.specs[0].reg : {};
    var ylab = mode === 'peak' ? 'Peak maximum' + (r0.yunits ? ' (' + r0.yunits + ')' : '') : mode === 'share' ? 'Percent of the element' : 'Atomic %';
    ctx.save(); ctx.translate(14, lay.t + lay.h / 2); ctx.rotate(-Math.PI / 2); ctx.fillText(ylab, 0, 0); ctx.restore();
    series.forEach(function (s, k) {
      var col = cyc[k % cyc.length], pen = false;
      ctx.strokeStyle = col; ctx.fillStyle = col; ctx.lineWidth = 1.6; ctx.lineJoin = 'round';
      ctx.beginPath();
      s.values.forEach(function (v, i) {
        if (v === null) { pen = false; return; }
        if (pen) ctx.lineTo(X(xs[i]), Y(v)); else { ctx.moveTo(X(xs[i]), Y(v)); pen = true; }
      });
      ctx.stroke();
      s.values.forEach(function (v, i) {
        if (v === null) return;
        ctx.beginPath(); ctx.arc(X(xs[i]), Y(v), L.hover === i ? 4.5 : (xs.length > 30 ? 1.8 : 3), 0, 6.2832); ctx.fill();
      });
    });
    if (L.hover !== null) {
      ctx.strokeStyle = C.accent; ctx.setLineDash([4, 3]); ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(X(xs[L.hover]) + 0.5, lay.t); ctx.lineTo(X(xs[L.hover]) + 0.5, lay.t + lay.h); ctx.stroke(); ctx.setLineDash([]);
    }
    ctx.font = font(11); ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
    series.slice(0, 16).forEach(function (s, k) {
      var y = lay.t + 8 + k * 16, x = lay.l + lay.w + 14;
      ctx.fillStyle = cyc[k % cyc.length]; ctx.fillRect(x, y - 1.5, 14, 3);
      ctx.fillStyle = C.fg; ctx.fillText(s.name.length > 24 ? s.name.slice(0, 23) + '…' : s.name, x + 20, y);
    });
    ctx.textBaseline = 'alphabetic';
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
  /* analysis-point markers with their names, halo'd so they read on any
     picture; `points` is {name: [x, y]} in picture pixels, `k` the display
     scale, `hot` the names to highlight. Returns the names drawn. */
  function paintMarkers(ctx, points, k, hot) {
    ctx.font = '12px system-ui, "Segoe UI", Helvetica, Arial, sans-serif'; ctx.textBaseline = 'middle';
    var names = Object.keys(points), placed = [];
    names.sort(function (a, b) { return (hot[b] ? 1 : 0) - (hot[a] ? 1 : 0); });
    names.forEach(function (name) {
      var p = points[name], x = p[0] * k, y = p[1] * k, on = !!hot[name];
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
    return names;
  }
  /* the picture at its display size on a canvas, drawn once decoded */
  function withPicture(key, src, then) {
    var cached = photoCache[key];
    if (cached && cached.complete) { then(cached); return; }
    var img = new Image();
    img.onload = function () { photoCache[key] = img; then(img); };
    img.src = src;
  }
  function sizeCanvas(cv, w, h) {
    var dpr = G.devicePixelRatio || 1, ctx = cv.getContext('2d');
    cv.style.width = Math.round(w) + 'px'; cv.style.height = Math.round(h) + 'px';
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return ctx;
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
      var names = paintMarkers(ctx, hd.points, k, hotSamples());
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

  /* ------------------------------------------------------ camera pictures */
  function sampleByName(name) { return S.data.samples.filter(function (s) { return s.name === name; })[0]; }
  function currentCam() { return S.data.cameras[S.camIdx] || null; }
  function renderCameras() {
    var box = clear($('tab-cameras')), cs = S.data.cameras || [];
    if (!cs.length) return;
    var sel = h('select', { id: 'camSel', 'aria-label': 'Camera picture' });
    cs.forEach(function (c, i) { sel.appendChild(h('option', { value: String(i), text: c.name })); });
    sel.addEventListener('change', function () { S.camIdx = +sel.value; drawCamera(); });
    box.appendChild(h('p', null, sel));
    box.appendChild(h('div', { class: 'cam-wrap' }, h('canvas', { id: 'camCanvas', 'aria-label': 'Camera picture with analysis positions', role: 'img' })));
    box.appendChild(h('div', { class: 'holder-info', id: 'camInfo' }));
    var cv = $('camCanvas');
    cv.addEventListener('click', function (e) {
      var c = currentCam(), lay = cv._lay;
      if (!c || !lay) return;
      var rect = cv.getBoundingClientRect(), x = e.clientX - rect.left, y = e.clientY - rect.top, best = null, bd = 18;
      Object.keys(c.points).forEach(function (name) {
        var p = c.points[name], d = Math.hypot(p[0] * lay.k - x, p[1] * lay.k - y);
        if (d <= bd) { bd = d; best = name; }
      });
      var sm = best ? sampleByName(best) : null;
      if (sm) select({ kind: 'sample', id: sm.id });
    });
  }
  function drawCamera() {
    var c = currentCam(), cv = $('camCanvas');
    if (!c || !cv) return;
    if ($('camSel')) $('camSel').value = String(S.camIdx);
    withPicture('cam' + c.id, c.img, function (img) {
      var box = cv.parentNode.clientWidth || 700, k = Math.min(1, box / c.w);
      var ctx = sizeCanvas(cv, c.w * k, c.h * k);
      ctx.drawImage(img, 0, 0, c.w * k, c.h * k);
      cv._lay = { k: k };
      ctx.setLineDash([6, 4]); ctx.lineWidth = 1.6; ctx.strokeStyle = '#FFD23F';
      c.maps.forEach(function (m) { ctx.strokeRect(m.rect[0] * k, m.rect[1] * k, m.rect[2] * k, m.rect[3] * k); });
      ctx.setLineDash([]);
      var hot = hotSamples();
      if (c.sample) hot[c.sample] = true;
      paintMarkers(ctx, c.points, k, hot);
      var mm = c.fov[0] >= 4 ? 1 : 0.5, bp = c.bar_px * mm * k, by = c.h * k - 26;
      ctx.lineCap = 'butt'; ctx.strokeStyle = '#0B1116'; ctx.lineWidth = 7;
      ctx.beginPath(); ctx.moveTo(20, by); ctx.lineTo(20 + bp, by); ctx.stroke();
      ctx.strokeStyle = '#FFFFFF'; ctx.lineWidth = 3;
      ctx.beginPath(); ctx.moveTo(20, by); ctx.lineTo(20 + bp, by); ctx.stroke();
      ctx.font = '12px system-ui, "Segoe UI", Helvetica, Arial, sans-serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
      ctx.lineWidth = 3; ctx.strokeStyle = '#0B1116'; ctx.fillStyle = '#FFFFFF';
      ctx.strokeText(mm + ' mm', 20 + bp / 2, by - 6); ctx.fillText(mm + ' mm', 20 + bp / 2, by - 6);
      var info = clear($('camInfo'));
      info.appendChild(h('span', { text: c.name + '  ·  ' + c.fov[0] + ' × ' + c.fov[1] + ' mm   ' }));
      var seen = {};
      c.maps.forEach(function (m) {
        var maps = S.data.maps.filter(function (x) { return x.sample === m.sample; });
        if (!maps.length || seen[m.sample]) return;
        seen[m.sample] = true;
        var b = h('button', { type: 'button', text: 'Open the SnapMap of ' + m.sample });
        b.addEventListener('click', function () { showTab('maps'); openMap(maps[0].id); });
        info.appendChild(b);
      });
      if (!Object.keys(c.points).length) info.appendChild(h('span', { class: 'muted', text: 'No analysis positions fall inside this picture.' }));
      else if (!c.maps.length) info.appendChild(h('span', { class: 'muted', text: 'Click a marker to select that sample.' }));
    });
  }

  /* ------------------------------------------------------------- SnapMaps */
  function currentMap() { return S.mapById[S.M.id] || null; }
  function saveText(name, text, type) {
    var blob = new Blob(['﻿' + text], { type: type || 'text/csv;charset=utf-8' });
    var a = h('a', { href: URL.createObjectURL(blob), download: name });
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }
  function renderMaps() {
    var box = clear($('tab-maps')), M = S.M, maps = S.data.maps || [];
    if (!maps.length) return;
    var mapSel = h('select', { id: 'mapSel', 'aria-label': 'SnapMap' });
    maps.forEach(function (m) { mapSel.appendChild(h('option', { value: m.id, text: m.sample + ' · ' + m.name })); });
    var scaleSel = h('select', { id: 'mapScale', 'aria-label': 'Colour scale' });
    Object.keys(V.SCALES).forEach(function (n) { scaleSel.appendChild(h('option', { value: n, text: n })); });
    var bg = h('input', { type: 'checkbox', id: 'mapBg' }), ov = h('input', { type: 'checkbox', id: 'mapOv' });
    var al = h('input', { type: 'range', id: 'mapAlpha', min: '0.15', max: '1', step: '0.05', value: String(M.alpha), 'aria-label': 'Map opacity' });
    var whole = h('button', { type: 'button', text: 'Whole map', title: 'Clear the chosen area' });
    var csvMap = h('button', { type: 'button', text: 'Map CSV' }), csvSpec = h('button', { type: 'button', text: 'Spectra CSV' });
    box.appendChild(h('div', { class: 'controls' },
      h('label', { class: 'field' }, 'Map', mapSel), h('label', { class: 'field' }, 'Colours', scaleSel),
      h('label', { class: 'field' }, bg, 'Remove background'), h('label', { class: 'field', id: 'mapOvField' }, ov, 'On camera image', al),
      whole, csvMap, csvSpec));
    box.appendChild(h('div', { class: 'maps-view' },
      h('canvas', { id: 'mapCanvas', 'aria-label': 'SnapMap image', role: 'img' }),
      h('canvas', { id: 'specCanvas', 'aria-label': 'Spectrum of the map', role: 'img' })));
    box.appendChild(h('p', { class: 'map-read muted', id: 'mapRead' }));
    box.appendChild(h('p', { class: 'muted small', text: 'Drag across the spectrum to choose the energy window; drag a box (or click a pixel) on the map to see that area\'s spectrum next to the whole map\'s.' }));
    mapSel.addEventListener('change', function () { openMap(mapSel.value); });
    scaleSel.addEventListener('change', function () { M.scale = scaleSel.value; drawMapView(); });
    bg.addEventListener('change', function () { M.bg = bg.checked; drawMapView(); });
    ov.addEventListener('change', function () { M.overlay = ov.checked; drawMapView(); });
    al.addEventListener('input', function () { M.alpha = +al.value; drawMapView(); });
    whole.addEventListener('click', function () { M.mask = null; M.roi = null; drawMapView(); });
    csvMap.addEventListener('click', function () {
      var m = currentMap();
      if (m && M.data) saveText((m.sample + ' ' + m.name + ' map').replace(/[^\w.\- ]+/g, '_') + '.csv', V.mapCsv(m, mapImage(m)));
    });
    csvSpec.addEventListener('click', function () {
      var m = currentMap();
      if (!m || !M.data) return;
      var e = M.energy, whole2 = M.total, roi = M.mask ? V.meanSpectrum(m, M.data, M.mask) : null, rows = ['Energy (eV),Whole map (counts per pixel)' + (roi ? ',Area ' + M.count + ' px (counts per pixel)' : '')];
      for (var i = 0; i < e.length; i++) rows.push(e[i] + ',' + +whole2[i].toPrecision(7) + (roi ? ',' + +roi[i].toPrecision(7) : ''));
      saveText((m.sample + ' ' + m.name + ' spectra').replace(/[^\w.\- ]+/g, '_') + '.csv', rows.join('\r\n') + '\r\n');
    });
    var mc = $('mapCanvas'), sc = $('specCanvas');
    mc.addEventListener('mousedown', function (e) { var p = mapPoint(e); if (p) { M.drag = { kind: 'roi', a: p, b: p }; } });
    sc.addEventListener('mousedown', function (e) { var x = specEnergy(e); if (x !== null) M.drag = { kind: 'win', a: x, b: x }; });
    mc.addEventListener('mousemove', function (e) { mapHover(e); });
    sc.addEventListener('mousemove', function (e) {
      var x = specEnergy(e);
      if (x !== null && !M.drag) $('mapRead').textContent = x.toFixed(2) + ' eV';
    });
    G.addEventListener('mousemove', function (e) {
      if (!M.drag) return;
      if (M.drag.kind === 'roi') { var p = mapPoint(e, true); if (p) M.drag.b = p; }
      else { var x = specEnergy(e, true); if (x !== null) { M.drag.b = x; M.win = [Math.min(M.drag.a, x), Math.max(M.drag.a, x)]; } }
      drawMapLater();
    });
    G.addEventListener('mouseup', function () {
      var d = M.drag, m = currentMap();
      if (!d) return;
      M.drag = null;
      if (d.kind === 'roi' && m && M.data) {
        var one = Math.abs(d.b[0] - d.a[0]) < Math.abs(m.dx) / 2 && Math.abs(d.b[1] - d.a[1]) < Math.abs(m.dy) / 2, r;
        if (one) {
          var px = V.pixelAt(m, d.a[0], d.a[1]);
          if (!px) { drawMapView(); return; }
          r = V.rectMask(m, m.x0 + px[0] * m.dx, m.y0 + px[1] * m.dy, m.x0 + px[0] * m.dx, m.y0 + px[1] * m.dy);
          M.roi = [m.x0 + px[0] * m.dx - m.dx / 2, m.y0 + px[1] * m.dy - m.dy / 2, m.x0 + px[0] * m.dx + m.dx / 2, m.y0 + px[1] * m.dy + m.dy / 2];
        } else {
          r = V.rectMask(m, d.a[0], d.a[1], d.b[0], d.b[1]);
          M.roi = [Math.min(d.a[0], d.b[0]), Math.min(d.a[1], d.b[1]), Math.max(d.a[0], d.b[0]), Math.max(d.a[1], d.b[1])];
        }
        if (r.count) { M.mask = r.mask; M.count = r.count; } else M.roi = M.mask ? M.roi : null;
      }
      drawMapView();
    });
  }
  var mapJob = 0;
  function drawMapLater() {
    if (mapJob) return;
    mapJob = G.requestAnimationFrame(function () { mapJob = 0; drawMapView(); });
  }
  function openMap(id) {
    var m = S.mapById[id], M = S.M;
    if (!m) return;
    M.id = id; M.data = null; M.loading = true; M.cache = null;
    if (M.mask && M.mask.length !== m.nx * m.ny) { M.mask = null; M.roi = null; }
    drawMapView();
    V.decodeMap(m).then(function (data) {
      if (M.id !== id) return;
      M.data = data; M.energy = V.axisValues(m.e); M.total = V.meanSpectrum(m, data, null);
      M.win = V.defaultWindow(M.energy, M.total);
      M.loading = false;
      drawMapView();
    }).catch(function (err) {
      if (M.id !== id) return;
      M.loading = false;
      $('mapRead').textContent = 'This map could not be decoded (' + (err && err.message ? err.message : err) + ').';
    });
  }
  function mapImage(m) {
    var M = S.M, key = [M.id, M.win[0], M.win[1], M.bg].join('|');
    if (!M.cache || M.cache.key !== key) {
      var img = V.mapImage(m, M.data, M.energy, M.win[0], M.win[1], M.bg);
      M.cache = { key: key, img: img, range: V.colourRange(img) };
    }
    return M.cache.img;
  }
  function mapPoint(e, clampIt) {
    var cv = $('mapCanvas'), lay = cv._lay;
    if (!lay || !S.M.data) return null;
    var r = cv.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    var inside = x >= lay.L && x <= lay.L + lay.pw && y >= lay.T && y <= lay.T + lay.ph;
    if (!inside && !clampIt) return null;
    x = Math.max(lay.L, Math.min(lay.L + lay.pw, x)); y = Math.max(lay.T, Math.min(lay.T + lay.ph, y));
    return [lay.vx0 + (x - lay.L) / lay.pw * (lay.vx1 - lay.vx0), lay.vy0 + (y - lay.T) / lay.ph * (lay.vy1 - lay.vy0)];
  }
  function specEnergy(e, clampIt) {
    var cv = $('specCanvas'), lay = cv._lay;
    if (!lay || !S.M.data) return null;
    var r = cv.getBoundingClientRect(), x = e.clientX - r.left;
    var inside = x >= lay.L && x <= lay.L + lay.pw;
    if (!inside && !clampIt) return null;
    x = Math.max(lay.L, Math.min(lay.L + lay.pw, x));
    return lay.e0 + (x - lay.L) / lay.pw * (lay.e1 - lay.e0);
  }
  function mapHover(e) {
    var m = currentMap(), p = mapPoint(e);
    if (!m || !p || S.M.drag) return;
    var px = V.pixelAt(m, p[0], p[1]);
    if (px) $('mapRead').textContent = 'x ' + Math.round(p[0]) + ' µm   y ' + Math.round(p[1]) + ' µm    pixel (' + px[0] + ', ' + px[1] + ')    value ' + V.fmtY(mapImage(m)[px[1] * m.nx + px[0]]);
  }
  function drawMapView() {
    var m = currentMap(), mc = $('mapCanvas'), sc = $('specCanvas'), M = S.M;
    if (!m || !mc) return;
    $('mapSel').value = m.id; $('mapScale').value = M.scale; $('mapBg').checked = M.bg; $('mapOv').checked = M.overlay && !!m.cam;
    $('mapOvField').style.display = m.cam ? '' : 'none';
    var C = colours(), W = mc.parentNode.clientWidth || 900, half = Math.max(280, (W - 12) / 2);
    if (G.matchMedia && G.matchMedia('(max-width: 820px)').matches) half = Math.max(280, W);   /* stacked */
    var reg = S.byId[m.region] || {};
    if (!M.data) {
      [mc, sc].forEach(function (cv) {
        var ctx = sizeCanvas(cv, half, 200);
        ctx.fillStyle = C.bg; ctx.fillRect(0, 0, half, 200);
        ctx.fillStyle = C.muted; ctx.font = '13px system-ui, sans-serif'; ctx.textAlign = 'center';
        ctx.fillText(M.loading ? 'Decoding the map…' : '', half / 2, 100);
      });
      return;
    }
    var img = mapImage(m), lo = M.cache.range[0], hi = M.cache.range[1];
    var ext = [m.x0 - m.dx / 2, m.x0 + (m.nx - 0.5) * m.dx, m.y0 - m.dy / 2, m.y0 + (m.ny - 0.5) * m.dy];   /* l, r, t, b */
    var cam = M.overlay && m.cam ? S.camById[m.cam.id] : null;
    var vx0 = ext[0], vx1 = ext[1], vy0 = ext[2], vy1 = ext[3];
    if (cam) { var px = (ext[1] - ext[0]) * 0.3, py = (ext[3] - ext[2]) * 0.3; vx0 -= px; vx1 += px; vy0 -= py; vy1 += py; }
    var L = 52, T = 26, B = 32, R = 64, pw = half - L - R, ph = pw * (vy1 - vy0) / (vx1 - vx0), H = ph + T + B;
    var ctx = sizeCanvas(mc, half, H), sx = pw / (vx1 - vx0), sy = ph / (vy1 - vy0);
    var X = function (x) { return L + (x - vx0) * sx; }, Y = function (y) { return T + (y - vy0) * sy; };
    mc._lay = { L: L, T: T, pw: pw, ph: ph, vx0: vx0, vx1: vx1, vy0: vy0, vy1: vy1 };
    var off = document.createElement('canvas');
    off.width = m.nx; off.height = m.ny;
    var octx = off.getContext('2d'), id = octx.createImageData(m.nx, m.ny), i;
    for (i = 0; i < img.length; i++) {
      var c3 = V.scaleColour(M.scale, (img[i] - lo) / (hi - lo));
      id.data[4 * i] = c3[0]; id.data[4 * i + 1] = c3[1]; id.data[4 * i + 2] = c3[2]; id.data[4 * i + 3] = 255;
    }
    octx.putImageData(id, 0, 0);
    var paint = function (photo) {
      ctx.fillStyle = C.bg; ctx.fillRect(0, 0, half, H);
      ctx.save(); ctx.beginPath(); ctx.rect(L, T, pw, ph); ctx.clip();
      if (photo) ctx.drawImage(photo, X(m.cam.ext[0]), Y(m.cam.ext[3]), (m.cam.ext[1] - m.cam.ext[0]) * sx, (m.cam.ext[2] - m.cam.ext[3]) * sy);
      ctx.globalAlpha = photo ? M.alpha : 1; ctx.imageSmoothingEnabled = false;
      ctx.drawImage(off, X(ext[0]), Y(ext[2]), (ext[1] - ext[0]) * sx, (ext[3] - ext[2]) * sy);
      ctx.globalAlpha = 1;
      var roi = M.drag && M.drag.kind === 'roi' ? [Math.min(M.drag.a[0], M.drag.b[0]), Math.min(M.drag.a[1], M.drag.b[1]), Math.max(M.drag.a[0], M.drag.b[0]), Math.max(M.drag.a[1], M.drag.b[1])] : M.roi;
      if (roi) { ctx.setLineDash([5, 3]); ctx.lineWidth = 1.6; ctx.strokeStyle = C.accent; ctx.strokeRect(X(roi[0]), Y(roi[1]), (roi[2] - roi[0]) * sx, (roi[3] - roi[1]) * sy); ctx.setLineDash([]); }
      ctx.restore();
      ctx.strokeStyle = C.muted; ctx.lineWidth = 1; ctx.strokeRect(L, T, pw, ph);
      ctx.fillStyle = C.muted; ctx.font = '11px system-ui, sans-serif'; ctx.textBaseline = 'top'; ctx.textAlign = 'center';
      V.niceTicks(vx0, vx1, 5).forEach(function (t) { ctx.fillText(String(t), X(t), T + ph + 4); });
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      V.niceTicks(vy0, vy1, 5).forEach(function (t) { ctx.fillText(String(t), L - 5, Y(t)); });
      ctx.textAlign = 'center'; ctx.textBaseline = 'bottom'; ctx.fillStyle = C.fg;
      ctx.fillText('X (µm)', L + pw / 2, H - 1);
      ctx.textAlign = 'left'; ctx.textBaseline = 'top';
      ctx.fillText(m.name + '   ' + M.win[0].toFixed(1) + '–' + M.win[1].toFixed(1) + ' eV', L, 4);
      for (var s = 0; s < 64; s++) {                                   /* colour bar */
        var cc = V.scaleColour(M.scale, 1 - s / 63);
        ctx.fillStyle = V.rgbToHex(cc); ctx.fillRect(L + pw + 12, T + ph * s / 64, 12, ph / 64 + 1);
      }
      ctx.fillStyle = C.muted; ctx.textAlign = 'left'; ctx.textBaseline = 'top'; ctx.fillText(V.fmtY(hi), L + pw + 28, T);
      ctx.textBaseline = 'bottom'; ctx.fillText(V.fmtY(lo), L + pw + 28, T + ph);
    };
    if (cam) withPicture('cam' + cam.id, cam.img, paint); else paint(null);
    drawSpectrum(m, reg, sc, half, H, C);
  }
  function drawSpectrum(m, reg, cv, W, H, C) {
    var M = S.M, e = M.energy, ctx = sizeCanvas(cv, W, H), L = 58, R = 12, T = 26, B = 32, pw = W - L - R, ph = H - T - B;
    var roi = M.mask ? V.meanSpectrum(m, M.data, M.mask) : null, i, lo = Infinity, hi = -Infinity;
    [M.total, roi].forEach(function (s) { if (s) for (i = 0; i < s.length; i++) { if (s[i] < lo) lo = s[i]; if (s[i] > hi) hi = s[i]; } });
    lo = Math.min(0, lo); hi = hi * 1.08 || 1;
    var e0 = e[0], e1 = e[e.length - 1], inv = !!reg.binding, a = inv ? Math.max(e0, e1) : Math.min(e0, e1), b = inv ? Math.min(e0, e1) : Math.max(e0, e1);
    var X = function (v) { return L + (v - a) / (b - a) * pw; }, Y = function (v) { return T + ph - (v - lo) / (hi - lo) * ph; };
    cv._lay = { L: L, pw: pw, e0: a, e1: b };
    ctx.fillStyle = C.bg; ctx.fillRect(0, 0, W, H);
    var wx0 = X(M.win[0]), wx1 = X(M.win[1]);
    ctx.fillStyle = C.accent; ctx.globalAlpha = 0.18; ctx.fillRect(Math.min(wx0, wx1), T, Math.abs(wx1 - wx0), ph); ctx.globalAlpha = 1;
    var line = function (s, col) {
      ctx.strokeStyle = col; ctx.lineWidth = 1.6; ctx.beginPath();
      for (var k = 0; k < s.length; k++) { if (k) ctx.lineTo(X(e[k]), Y(s[k])); else ctx.moveTo(X(e[k]), Y(s[k])); }
      ctx.stroke();
    };
    line(M.total, roi ? C.muted : C.accent);
    if (roi) line(roi, C.accent);
    ctx.strokeStyle = C.muted; ctx.lineWidth = 1; ctx.strokeRect(L, T, pw, ph);
    ctx.fillStyle = C.muted; ctx.font = '11px system-ui, sans-serif'; ctx.textBaseline = 'top'; ctx.textAlign = 'center';
    V.niceTicks(Math.min(a, b), Math.max(a, b), 6).forEach(function (t) { ctx.fillText(String(t), X(t), T + ph + 4); });
    ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
    V.niceTicks(lo, hi, 5).forEach(function (t) { ctx.fillText(V.fmtY(t), L - 5, Y(t)); });
    ctx.fillStyle = C.fg; ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText((reg.elabel || 'Binding Energy') + ' (' + (reg.eunits || 'eV') + ')', L + pw / 2, H - 1);
    ctx.textAlign = 'left'; ctx.textBaseline = 'top';
    ctx.fillText(roi ? 'grey: whole map · blue: area (' + M.count + ' px)' : 'whole map', L, 4);
    ctx.save(); ctx.translate(12, T + ph / 2); ctx.rotate(-Math.PI / 2); ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText('counts per pixel', 0, 0); ctx.restore();
  }
  /* selecting a sample (or a map's own spectrum) brings up its picture / map */
  function followSelection(sel) {
    if (!sel) return;
    var name = '', spec = null;
    if (sel.kind === 'region') { spec = S.byId[sel.id]; name = spec ? spec.sample.name : ''; }
    else { var sm = S.data.samples.filter(function (s) { return s.id === sel.id; })[0]; name = sm ? sm.name : ''; }
    var cs = S.data.cameras || [], cur = currentCam();
    if (cs.length && !(cur && cur.sample === name)) {
      for (var i = 0; i < cs.length; i++) if (cs[i].sample === name) { S.camIdx = i; break; }
    }
    var maps = S.data.maps || [], cm = currentMap();
    if (maps.length && S.tab === 'maps') {
      if (spec && spec.reg.map) openMap(spec.reg.map);
      else if (!(cm && cm.sample === name)) { var hit = maps.filter(function (x) { return x.sample === name; })[0]; if (hit) openMap(hit.id); }
    }
  }

  /* ------------------------------------------------------------ download */
  function downloadCsv() {
    var specs = S.specs.filter(function (s) { return S.ticked.has(s.id); });
    if (!specs.length) { $('notes').textContent = 'Tick some spectra first.'; return; }
    saveText('spectra.csv', V.buildCsv(specs));
  }

  /* ---------------------------------------------------------------- setup */
  function init(data) {
    S.data = data;
    S.specs = V.prepare(data);
    S.specs.forEach(function (s) { S.byId[s.id] = s; });
    (data.maps || []).forEach(function (m) { S.mapById[m.id] = m; });
    (data.cameras || []).forEach(function (c) { S.camById[c.id] = c; });
    data.cameras = data.cameras || []; data.maps = data.maps || [];
    var d = data.details;
    $('title').textContent = d.title || 'Experiment data browser';
    document.title = $('title').textContent;
    $('subtitle').textContent = [d.customer, d.reference, d.operator, d.date].filter(Boolean).join('  ·  ');
    $('foot').textContent = 'Made with ' + data.tool + ' on ' + data.generated.replace('T', ' ') +
      '. Self-contained: it needs no network and opens in any modern browser.';
    buildTree();
    buildTabs();
    renderQuant(); renderFigures(); renderNotes(); renderMethods(); renderHolder(); renderMeta(); renderCameras(); renderMaps();
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
    V.FIT_LAYERS.forEach(function (k) {
      $('fit-' + k).addEventListener('change', function (e) { S.fit[k] = e.target.checked; requestRender(); });
    });
    $('levelOn').addEventListener('change', function (e) { S.levelOn = e.target.checked; requestRender(); });
    $('level').addEventListener('input', function (e) { S.levelIdx = +e.target.value; requestRender(); });
    $('theme').addEventListener('change', function (e) { S.theme = e.target.value; applyTheme(); });
    $('print').addEventListener('click', function () { G.print(); });
    G.addEventListener('beforeprint', function () { S.printing = true; applyTheme(); render(); redrawTab(); });
    G.addEventListener('afterprint', function () { S.printing = false; applyTheme(); });
    if (G.matchMedia) {
      var mq = G.matchMedia('(prefers-color-scheme: dark)');
      if (mq.addEventListener) mq.addEventListener('change', function () { if (S.theme === 'auto') applyTheme(); });
    }
    if (G.ResizeObserver) {
      new G.ResizeObserver(function () { requestRender(); redrawTab(); }).observe($('panels'));
    } else G.addEventListener('resize', requestRender);
    G.addEventListener('resize', function () { if (S.tab === 'cameras' || S.tab === 'maps') redrawTab(); });
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
