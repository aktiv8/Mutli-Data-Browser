'use strict';
// Unit tests of the pure half of viewer/viewer.js, run by test_htmlbrowser.py:
//   node tests/viewer_test.js <fixture.json>
// The fixture is written by Python and holds expected values computed there,
// so the JavaScript is checked against the desktop app's own results.
const fs = require('fs');
const path = require('path');
const V = require(path.join(__dirname, '..', 'viewer', 'viewer.js'));
const fx = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));

let failed = 0, ran = 0;
function check(cond, msg) {
  ran++;
  if (!cond) { failed++; console.log('FAIL ' + msg); }
}
function eq(a, b, msg) {
  check(JSON.stringify(a) === JSON.stringify(b), msg + ': ' + JSON.stringify(a) + ' != ' + JSON.stringify(b));
}
function near(a, b, msg, tol) {
  check(Math.abs(a - b) <= (tol || 1e-9), msg + ': ' + a + ' vs ' + b);
}

(async () => {
  // ---- the data Python wrote decodes to the same structure ----
  const data = await V.decode(fx.payload_b64);
  eq(data.v, 1, 'payload version');
  eq(data.samples.length, fx.n_samples, 'sample count');
  const specs = V.prepare(data);
  eq(specs.length, fx.n_spectra, 'spectrum count');
  const s0 = specs[0];
  eq(s0.x.length, fx.first_len, 'axis length');
  near(s0.x[0], fx.first_x0, 'first energy', 1e-6);
  near(s0.x[s0.x.length - 1], fx.first_x_last, 'last energy', 1e-5);
  near(s0.y[3], fx.first_y3, 'a count value', Math.abs(fx.first_y3) * 1e-6 + 1e-12);
  eq(s0.fileName, fx.first_file, 'file name attached');

  // ---- bad input is rejected, not swallowed ----
  let threw = false;
  try { await V.decode('AAAA'); } catch (e) { threw = true; }
  check(threw, 'garbage payload is an error');

  // ---- axes ----
  eq(V.axisValues({ x0: 10, dx: 0.5, n: 4 }), [10, 10.5, 11, 11.5], 'regular axis');
  eq(V.axisValues([1, 2, 4]), [1, 2, 4], 'irregular axis');
  const reg = { binding: true, hv: 1486.6, elabel: 'Binding Energy', eunits: 'eV' };
  let a = V.energyAxis(reg, [285, 290], 'Binding');
  check(a.invert && a.label === 'Binding energy', 'binding axis is inverted');
  a = V.energyAxis(reg, [285, 290], 'Kinetic');
  near(a.x[0], 1201.6, 'KE = hv - BE', 1e-9);
  check(!a.invert && a.label === 'Kinetic energy', 'kinetic axis not inverted');
  a = V.energyAxis({ binding: true, hv: null, elabel: 'Binding Energy' }, [1, 2], 'Kinetic');
  check(!a.ok && a.invert, 'no photon energy: falls back to binding');
  a = V.energyAxis({ binding: false, hv: null, elabel: 'Kinetic Energy' }, [1, 2], 'Kinetic');
  check(a.ok && !a.invert, 'native kinetic axis kept');

  // ---- ticks ----
  eq(V.niceTicks(280, 296, 8), [280, 282, 284, 286, 288, 290, 292, 294, 296], 'ticks 280-296');
  eq(V.niceTicks(0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1], 'ticks 0-1');
  eq(V.niceTicks(1, 1, 5), [], 'no ticks for an empty range');
  eq(V.niceTicks(NaN, 1, 5), [], 'no ticks for NaN');
  eq(V.decimals(2), 0, 'decimals of 2');
  eq(V.decimals(0.5), 1, 'decimals of 0.5');
  eq(V.decimals(0.05), 2, 'decimals of 0.05');
  eq(V.niceFloor(1234), 1000, 'niceFloor 1234');
  eq(V.niceFloor(0.37), 0.2, 'niceFloor 0.37');
  eq(V.niceFloor(0), 1, 'niceFloor 0');
  eq(V.fmtY(0), '0', 'fmtY 0');
  eq(V.fmtY(123456), '1.2e5', 'fmtY big');
  eq(V.fmtY(1234.5), '1235', 'fmtY 1234.5');

  // ---- normalising agrees with the desktop app ----
  fx.norm.forEach((c) => {
    near(V.normFactor(c.y, 'max'), c.max, 'max factor ' + JSON.stringify(c.y));
    near(V.normFactor(c.y, 'area'), c.area, 'area factor ' + JSON.stringify(c.y));
    eq(V.normFactor(c.y, 'none'), 1, 'no normalisation');
  });

  // ---- colours agree with themes.ramp ----
  fx.ramps.forEach((c) => {
    eq(V.ramp(c.colour, c.n, c.bg), c.expect, 'ramp ' + c.n);
  });
  const cyc = ['#111111', '#222222', '#333333'];
  eq(V.stackColours([0, 0, 0], cyc, '#FFFFFF').length, 3, 'shared slot -> ramp');
  check(V.stackColours([0, 0, 0], cyc, '#FFFFFF')[2] !== '#111111', 'ramp fades');
  eq(V.stackColours([0, 1, 4], cyc, '#FFFFFF'), ['#111111', '#222222', '#222222'], 'categorical wraps');
  eq(V.stackColours([2], cyc, '#FFFFFF'), ['#333333'], 'single trace keeps its colour');

  // ---- labels ----
  const ys = [100, 104, 102, 300];
  const d = V.dodge(ys, 10);
  check(d[0] === 100 && d[2] === 110 && d[1] === 120, 'dodge separates and keeps order: ' + d);
  eq(d[3], 300, 'dodge leaves far labels');
  eq(V.traceLabel({ reg: { level: 3, etch: 90 }, sample: { name: 'S' }, name: 'C 1s', fileName: '' }), 'L3 (90 s)', 'level label');
  eq(V.traceLabel({ reg: { level: null }, sample: { name: 'Sample A' }, name: 'C 1s', fileName: '' }), 'Sample A', 'sample label');
  eq(V.traceLabel({ reg: { level: null }, sample: { name: '' }, name: 'C 1s', fileName: 'run1.vms' }, true), 'run1', 'file label');
  eq(V.traceLabel({ reg: { level: null }, sample: { name: 'x'.repeat(40) }, name: 'C 1s', fileName: '' }).length, 23, 'long label cut');

  // ---- grouping ----
  const g = V.groupSpectra([{ name: 'C 1s' }, { name: 'O 1s' }, { name: 'c  1s' }]);
  eq(g.map((x) => x.items.length), [2, 1], 'grouped by normalised name');
  eq(g.map((x) => x.name), ['C 1s', 'O 1s'], 'first appearance order');

  // ---- interpolation, either direction ----
  near(V.interp([1, 2, 3], [10, 20, 30], 2.5), 25, 'interp ascending');
  near(V.interp([3, 2, 1], [30, 20, 10], 2.5), 25, 'interp descending');
  eq(V.interp([1, 2, 3], [10, 20, 30], 5), null, 'outside the range');
  eq(V.interp([], [], 1), null, 'empty');

  // ---- CSV equals the app's own export ----
  const sel = specs.filter((s) => fx.csv_ids.indexOf(s.id) >= 0);
  const csv = V.buildCsv(sel).replace(/\r\n/g, '\n');
  const want = fx.csv.replace(/\r\n/g, '\n');
  const cl = csv.trim().split('\n'), wl = want.trim().split('\n');
  eq(cl[0], wl[0], 'CSV header equals the app export');
  eq(cl.length, wl.length, 'CSV row count');
  let worst = 0;
  for (let i = 1; i < wl.length; i++) {
    const c = cl[i].split(','), w = wl[i].split(',');
    eq(c.length, w.length, 'CSV columns row ' + i);
    for (let k = 0; k < w.length; k++) {
      if (w[k] === '' || c[k] === '') { eq(c[k], w[k], 'CSV blank cell'); continue; }
      const dv = Math.abs(parseFloat(c[k]) - parseFloat(w[k])) / (Math.abs(parseFloat(w[k])) + 1e-9);
      if (dv > worst) worst = dv;
    }
  }
  check(worst < 1e-6, 'CSV values agree (worst relative error ' + worst + ')');
  eq(V.csvField('a,b'), '"a,b"', 'csv comma quoting');
  eq(V.csvField('say "hi"'), '"say ""hi"""', 'csv quote escaping');
  eq(V.csvField('plain'), 'plain', 'csv plain');
  const lv = V.buildCsv([{ sample: { name: 'S' }, name: 'C 1s', reg: { level: 2, elabel: 'Binding Energy', eunits: 'eV', ylabel: 'Intensity', yunits: 'counts' }, x: [1], y: [2] }]);
  check(lv.split('\r\n')[0].indexOf('S C 1s L2 ') === 0, 'depth levels are told apart in CSV headers');

  // ---- CasaXPS fits: the CSV (with its fit columns) equals the app's export ----
  if (fx.fit) {
    const fdata = await V.decode(fx.fit.payload_b64);
    const fspecs = V.prepare(fdata);
    const fcsv = V.buildCsv(fspecs).replace(/\r\n/g, '\n').trim().split('\n');
    const fwant = fx.fit.csv.replace(/\r\n/g, '\n').trim().split('\n');
    eq(fcsv[0], fwant[0], 'fit CSV header equals the app export (fit columns named the same)');
    eq(fcsv.length, fwant.length, 'fit CSV row count');
    let fworst = 0, blanks = true;
    for (let i = 1; i < fwant.length; i++) {
      const c = fcsv[i].split(','), w = fwant[i].split(',');
      eq(c.length, w.length, 'fit CSV columns row ' + i);
      for (let k = 0; k < w.length; k++) {
        if (w[k] === '' || c[k] === '') { if (c[k] !== w[k]) blanks = false; continue; }
        const dv = Math.abs(parseFloat(c[k]) - parseFloat(w[k])) / (Math.abs(parseFloat(w[k])) + 1e-9);
        if (dv > fworst) fworst = dv;
      }
    }
    check(blanks, 'fit CSV: cells outside the region are blank in both');
    check(fworst < 1e-5, 'fit CSV values agree (worst relative error ' + fworst + ')');
    // curves on every point, null outside the region
    const cur = { i0: 2 }, full = V.curveFull(cur, [5, 6], 6);
    eq(full, [null, null, 5, 6, null, null], 'curveFull places a curve at its first point');
    eq(V.curveFull(null, [1], 3), null, 'no curves, no curve');
    eq(V.residual([10, 20, 30], [9, null, 33]), [1, null, -3], 'residual is data - envelope');
    eq(V.fitStates(fspecs[0].reg).map((x) => x.gk + '|' + x.name + '|' + x.slot),
       fx.fit.states.filter((x, i, a) => a.findIndex((y) => y.gk === x.gk) === i)
         .map((x, i) => x.gk + '|' + x.name + '|' + i), 'chemical states in order of appearance');
    eq(V.fitRows({}).length, 0, 'a spectrum without a fit has no rows');
  }

  // ---- quantification: the same table as quant.csv_rows ----
  if (fx.fit && fx.fit.quant) {
    const qx = fx.fit.quant;
    const cmp = (got, want, label) => {
      eq(got.length, want.length, label + ' row count');
      got.forEach((row, i) => {
        eq(row.length, want[i].length, label + ' columns row ' + i);
        row.forEach((cell, k) => {
          const w = want[i][k], numeric = i > 0 && k >= 5 && k <= 8 || i > 0 && k === 10;
          if (numeric && cell !== '' && w !== '') near(parseFloat(cell), parseFloat(w), label + ' cell ' + i + ',' + k, Math.abs(parseFloat(w)) * 1e-5 + 1e-9);
          else eq(cell, w, label + ' cell ' + i + ',' + k);
        });
      });
    };
    cmp(V.quantTable(qx.groups, null, false), qx.plain, 'quant table');
    cmp(V.quantTable(qx.groups, qx.excluded_keys, false), qx.excluded, 'quant table with a region left out');
    cmp(V.quantTable(qx.groups, null, true), qx.trans, 'quant table with the transmission function');
    const csv = V.quantCsv(qx.groups, null, false).split('\r\n');
    eq(csv[0], V.QUANT_HEADER.map(V.csvField).join(','), 'quant CSV header');
    check(csv[1].indexOf('"S, 1",1,C 1s,C 1s,Shirley,0.278') === 0, 'quant CSV quotes a comma in the sample name: ' + csv[1]);
    const n = V.quantNormalise([{ area: 1, rsf: 1 }, { area: 3, rsf: 1 }], null, false);
    near(n[0].at, 25, 'atomic percent'); near(n[1].at, 75, 'atomic percent');
    eq(V.quantNormalise([{ area: 5, rsf: 0 }], null, false)[0].why, 'no RSF', 'no RSF is said');
    eq(V.quantStates({ components: [{ gk: 'i1', state: 'A', area: 3 }, { gk: 'i1', state: 'A', area: 1 }, { gk: 'nB', state: 'B', area: -2 }] }, 40)
      .map((s) => s.name + ':' + s.at), ['A:40', 'B:0'], 'states share the row, negative areas count as zero');
  }

  // ---- depth profiles: the same series as quant.profile ----
  if (fx.fit && fx.fit.quant && fx.fit.quant.profile) {
    const px = fx.fit.quant.profile;
    const same = (got, want, label) => {
      eq(got.levels, want.levels, label + ' levels');
      eq(got.series.map((s) => s.name), want.series.map((s) => s.name), label + ' series names');
      got.series.forEach((s, k) => s.values.forEach((v, i) => {
        const w = want.series[k].values[i];
        if (v === null || w === null) eq(v, w, label + ' gap ' + s.name + ' ' + i);
        else near(v, w, label + ' ' + s.name + ' ' + i, Math.abs(w) * 1e-9 + 1e-9);
      }));
    };
    ['element', 'state', 'share'].forEach((m) => same(V.profile(px.groups, m, null, false), px[m], 'profile ' + m));
    same(V.profile(px.groups, 'element', px.exclude, false), px.element_excl, 'profile with a region left out');
  }
  {
    // where the levels sit, and which axes they support
    const info = V.levelInfo({ level: 2, etch: 60, meta: { 'Depth (nm)': '3.5', 'Fluence (ions/cm²)': '1.2e+16' } });
    eq([info.level, info.etch, info.depth, info.fluence], [2, 60, 3.5, 1.2e16], 'levelInfo reads the metadata');
    eq(V.levelInfo({ level: 1, meta: {} }).depth, null, 'no depth without sputter settings');
    const lv = (etch, depth) => ({ level: 0, etch: etch, depth: depth, fluence: null });
    eq(V.profileAxes([lv(0, 0), lv(30, 1.5), lv(60, 3)].map((x, i) => Object.assign(x, { level: i }))).map((a) => a.id),
       ['depth', 'etch', 'level'], 'axes with depth, etch time and level');
    eq(V.profileAxes([lv(0, null), lv(0, null), lv(0, null)].map((x, i) => Object.assign(x, { level: i }))).map((a) => a.id),
       ['level'], 'all-zero etch times are not an axis');
    const specs = [
      { name: 'C 1s', reg: { level: 1 }, y: [1, 9, 4] }, { name: 'C 1s', reg: { level: 0 }, y: [2, 3] },
      { name: 'O 1s', reg: { level: 0 }, y: [7] } ];
    const pm = V.peakMaxSeries(specs);
    eq(pm.levels, [0, 1], 'peak maximum levels sorted');
    eq(pm.series, [{ name: 'C 1s', values: [3, 9] }, { name: 'O 1s', values: [7, null] }], 'peak maxima per level');
    const tb = V.profileTable({ levels: [0, 1], series: [{ name: 'A', values: [12.3456789, null] }] },
      [{ level: 0, etch: 0, depth: null, fluence: null }, { level: 1, etch: 30, depth: null, fluence: null }]);
    eq(tb, [['Level', 'Etch time (s)', 'A'], ['0', '0', '12.3457'], ['1', '30', '']], 'profile table');
  }

  // ---- element identification: the same candidates, in the same order, as xpslines.py ----
  if (fx.elements) {
    const ex = fx.elements;
    ex.cases.forEach((c, i) => {
      const got = V.candidates(c.be, c.win, ex.table, c.hv);
      eq(got.map((x) => x.label), c.labels, 'candidates ' + i + ' (' + c.be + ' eV)');
      got.forEach((x, k) => near(x.d, c.deltas[k], 'candidate delta ' + i + '.' + k, 1e-9));
    });
    check(ex.cases.some((c) => c.labels.length > 1), 'the fixture has an ambiguous peak, so the order is tested');
    check(ex.table.lines.some((l) => l[2] === null), 'the fixture has Auger lines');
    near(V.lineBe(['O', 'KLL', null, 510, 1], 1486.6, 1486.6), 976.6, 'Auger binding energy follows hv', 1e-9);
    near(V.lineBe(['O', 'KLL', null, 510, 1], null, 1253.6), 743.6, 'default hv when none is given', 1e-9);
    eq(V.candidates(700, 1, ex.table, 1486.6), [], 'nothing near 700 eV within 1 eV');
    eq(V.lineLabel(['C', '1s', 285, null, 1]), 'C 1s', 'line label');
    (ex.nearby || []).forEach((c, i) => {
      const got = V.nearbyLines(c.be, c.win, ex.table, c.hv, c.exclude, c.secondary, c.auger);
      eq(got.map((x) => x.label), c.labels, 'nearby ' + i + ' labels');
      eq(got.map((x) => x.tier), c.tiers, 'nearby ' + i + ' tiers');
      got.forEach((x, k) => near(x.be, c.candidate_be[k], 'nearby ' + i + '.' + k + ' be', 1e-9));
    });
  }

  // ---- the ZIP the page hands over: read back by Python's zipfile ----
  check(V.crc32(V.utf8('123456789')) === 0xCBF43926, 'crc32 of the standard check string');
  eq(V.safeName('a/b:c'), 'a_b_c', 'safeName replaces separators');
  eq(V.safeName('..'), 'unnamed', 'safeName never gives a dot name');
  eq(V.safeName('Pt #001a (1)'), 'Pt _001a (1)', 'safeName keeps letters, digits, spaces and brackets');
  const bundle = V.bundleFiles(data, specs);
  eq(bundle.map((f) => f.name), ['README.txt', 'csv/A/C 1s.csv', 'csv/A/O 1s.csv', 'csv/B/C 1s.csv'], 'bundle contents');
  check(bundle[0].data.indexOf('3 spectra from 2 samples') >= 0, 'README counts the spectra');
  check(bundle[1].data.charAt(0) === '﻿', 'CSV files start with a byte-order mark for Excel');
  if (fx.zip_out) {
    fs.writeFileSync(fx.zip_out, Buffer.from(V.zip(bundle.concat([{ name: 'ünï/tëst.txt', data: 'héllo' }]), new Date(2026, 0, 2, 3, 4, 6))));
  }

  // ---- metadata summary ----
  const sm = V.summariseMeta([{ A: '1', B: 'x', C: '' }, { A: '1', B: 'y', C: '' }, { A: '1', B: 'x', D: '5' }], []);
  eq(sm.common, [['A', '1']], 'common metadata');
  eq(sm.varying, ['B', 'D'], 'varying metadata');
  eq(V.summariseMeta([{ Sample: 'a', Q: '1' }, { Sample: 'b', Q: '1' }], ['Sample']).common, [['Q', '1']], 'skipped keys');

  // ---- paragraphs ----
  eq(V.paragraphs('a\nb\n\n\nc\r\n\r\nd\n'), ['a\nb', 'c', 'd'], 'paragraphs');
  eq(V.paragraphs(''), [], 'no paragraphs');

  // ---- SnapMaps: the page's maths against snapmap.py on the same map ----
  if (fx.map) {
    const m = fx.map.entry, e = fx.map.energy;
    const data = await V.decodeMap(m);
    eq(data.length, m.nx * m.ny * m.n, 'map data length');
    eq(V.axisValues(m.e).length, m.n, 'map energy axis length');
    const win = fx.map.win;
    const close = (a, b, msg, tol) => {
      let worst = 0;
      eq(a.length, b.length, msg + ' length');
      for (let i = 0; i < b.length; i++) worst = Math.max(worst, Math.abs(a[i] - b[i]));
      check(worst <= (tol || 1e-6), msg + ' (worst difference ' + worst + ')');
    };
    eq(V.mapChannels(e, fx.map.channels[0][0], fx.map.channels[0][1]), fx.map.channels[1], 'channels in a window');
    eq(V.mapChannels(e, fx.map.channels[0][1], fx.map.channels[0][0]), fx.map.channels[1], 'window given either way round');
    close(V.mapImage(m, data, e, win[0], win[1], false), fx.map.image, 'map image');
    close(V.mapImage(m, data, e, win[0], win[1], true), fx.map.image_bg, 'map image, background removed');
    eq(Array.from(V.mapImage(m, data, e, 1e9, 2e9, false)).every((v) => v === 0), true, 'empty window is zeros');
    close(V.meanSpectrum(m, data, null), fx.map.total_mean, 'whole-map mean spectrum');
    const r = V.rectMask(m, fx.map.rect[0], fx.map.rect[1], fx.map.rect[2], fx.map.rect[3]);
    eq(Array.from(r.mask), fx.map.mask, 'rectangle mask');
    eq(r.count, fx.map.mask_count, 'rectangle pixel count');
    eq(Array.from(V.rectMask(m, fx.map.rect[2], fx.map.rect[3], fx.map.rect[0], fx.map.rect[1]).mask), fx.map.mask, 'rectangle corners either way');
    close(V.meanSpectrum(m, data, r.mask), fx.map.roi_mean, 'area mean spectrum');
    fx.map.pixels.forEach((p) => eq(V.pixelAt(m, p[0], p[1]), p[2], 'pixel at ' + p[0] + ',' + p[1]));
    const rng = V.colourRange(V.mapImage(m, data, e, win[0], win[1], false));
    near(rng[0], fx.map.range[0], 'colour range low', 1e-6);
    near(rng[1], fx.map.range[1], 'colour range high', 1e-6);
    eq(V.colourRange([NaN, Infinity]), [0, 1], 'colour range of nothing');
    eq(V.colourRange([5, 5, 5]), [5, 6], 'colour range of a flat map');
    fx.map.window_cases.forEach((c, i) => {
      const w = V.defaultWindow(c.energy, c.y);
      near(w[0], c.expect[0], 'default window low, case ' + i, 1e-9);
      near(w[1], c.expect[1], 'default window high, case ' + i, 1e-9);
    });
    const csv = V.mapCsv(m, fx.map.image).trim().split('\r\n'), want = fx.map.csv.trim().split('\n');
    eq(csv.length, want.length, 'map CSV rows');
    eq(csv[0], want[0], 'map CSV header');
    let cw = 0;
    for (let i = 1; i < want.length; i++) {
      const a = csv[i].split(','), b = want[i].split(',');
      eq(a.length, b.length, 'map CSV columns row ' + i);
      for (let k = 0; k < b.length; k++) cw = Math.max(cw, Math.abs(parseFloat(a[k]) - parseFloat(b[k])) / (Math.abs(parseFloat(b[k])) + 1e-9));
    }
    check(cw < 1e-5, 'map CSV values agree (worst relative ' + cw + ')');
    eq(V.scaleColour('Viridis', 0).map(Math.round), [68, 1, 84], 'viridis starts dark purple');
    eq(V.scaleColour('Viridis', 1).map(Math.round), [253, 231, 37], 'viridis ends yellow');
    eq(V.scaleColour('Nope', 0.5).length, 3, 'unknown scale falls back');
    eq(V.scaleColour('Greys', -5).map(Math.round), V.scaleColour('Greys', 0).map(Math.round), 'colour position clamps');
    let bad = false;
    try { await V.decodeMap(Object.assign({}, m, { n: m.n + 1 })); } catch (err) { bad = true; }
    check(bad, 'a map of the wrong size is an error');
  }

  // ---- hostile text stays text: nothing in the pure half builds HTML ----
  const src = fs.readFileSync(path.join(__dirname, '..', 'viewer', 'viewer.js'), 'utf8');
  check(src.indexOf('innerHTML') < 0, 'viewer never uses innerHTML');
  check(src.indexOf('insertAdjacentHTML') < 0, 'viewer never uses insertAdjacentHTML');
  check(src.indexOf('eval(') < 0 && src.indexOf('new Function') < 0, 'viewer never evals');
  check(!/https?:\/\//.test(src), 'viewer mentions no URLs');
  ['__DATA__', '__CSS__', '__JS__', '__TITLE__'].forEach((t) => check(src.indexOf(t) < 0, 'viewer.js does not contain ' + t));

  console.log((failed ? 'FAILED ' : 'ok ') + (ran - failed) + '/' + ran + ' checks');
  process.exit(failed ? 1 : 0);
})().catch((e) => { console.log('ERROR ' + (e && e.stack || e)); process.exit(2); });
