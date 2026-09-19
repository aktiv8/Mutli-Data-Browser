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

  // ---- metadata summary ----
  const sm = V.summariseMeta([{ A: '1', B: 'x', C: '' }, { A: '1', B: 'y', C: '' }, { A: '1', B: 'x', D: '5' }], []);
  eq(sm.common, [['A', '1']], 'common metadata');
  eq(sm.varying, ['B', 'D'], 'varying metadata');
  eq(V.summariseMeta([{ Sample: 'a', Q: '1' }, { Sample: 'b', Q: '1' }], ['Sample']).common, [['Q', '1']], 'skipped keys');

  // ---- paragraphs ----
  eq(V.paragraphs('a\nb\n\n\nc\r\n\r\nd\n'), ['a\nb', 'c', 'd'], 'paragraphs');
  eq(V.paragraphs(''), [], 'no paragraphs');

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
