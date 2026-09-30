"""casacsv.py: parsing CasaXPS "Export All to ASCII" CSVs (both layouts) and
matching their blocks onto already-loaded Region/FitRegion/FitComponent
objects, including the real PtCl2_new files when present.

Run:  python -m unittest discover tests
"""

import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import casacsv  # noqa: E402
import casafit  # noqa: E402
import readers  # noqa: E402
from readers import Region  # noqa: E402

try:
    import numpy as np
    HAVE_NP = True
except Exception:
    HAVE_NP = False


def _write(text):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    return path


# ------------------------------------------------------------- layout detect
class TestDetectLayout(unittest.TestCase):
    def test_columns(self):
        self.assertEqual(casacsv.detect_layout(["Cycle 0:S:X Scan"]), "columns")

    def test_rows(self):
        self.assertEqual(casacsv.detect_layout(["Name", "", ""]), "rows")

    def test_neither(self):
        self.assertIsNone(casacsv.detect_layout(["K.E.", "Counts"]))
        self.assertIsNone(casacsv.detect_layout([]))
        self.assertIsNone(casacsv.detect_layout(None))


# --------------------------------------------------------- columns layout
NO_FIT = """"Cycle 0:TestSample:X1 Scan"
,Characteristic Energy eV,1000.0,Acquisition Time s,1.0
Name,,
Position,,
FWHM,,
Area,,
Lineshape,,
K.E.,Counts,,B.E.,CPS
100.0,10.0,,900.0,10.0
101.0,20.0,,899.0,20.0
102.0,15.0,,898.0,15.0
"""

BG_ONLY = """"Cycle 0:TestSample:X2 Scan"
,Characteristic Energy eV,1000.0,Acquisition Time s,1.0
Name,,
Position,,
FWHM,,
Area,,
Lineshape,,
K.E.,Counts,Background,Envelope,,B.E.,CPS,Background CPS,Envelope CPS
100.0,10.0,10.0,10.0,,900.0,10.0,10.0,10.0
101.0,20.0,10.0,10.0,,899.0,20.0,10.0,10.0
102.0,15.0,10.0,10.0,,898.0,15.0,10.0,10.0
"""

DOUBLET = """"Cycle 0:TestSample:X3 Scan"
,Characteristic Energy eV,1000.0,Acquisition Time s,1.0
Name,,Peak A,Peak A
Position,,500.0,502.0
FWHM,,1.0,1.0
Area,,100.0,50.0
Lineshape,,GL(30),GL(30)
K.E.,Counts,Peak A,Peak A,Background,Envelope,,B.E.,CPS,Peak A,Peak A,Background CPS,Envelope CPS
100.0,10.0,12.0,10.5,5.0,17.5,,900.0,10.0,12.0,10.5,5.0,17.5
101.0,20.0,23.0,20.2,5.0,38.2,,899.0,20.0,23.0,20.2,5.0,38.2
102.0,15.0,17.0,15.3,5.0,27.3,,898.0,15.0,17.0,15.3,5.0,27.3
"""

TWO_BLOCKS = NO_FIT + BG_ONLY


class TestParseColumns(unittest.TestCase):
    def _parse(self, text):
        path = _write(text)
        try:
            return casacsv.parse(path)
        finally:
            os.remove(path)

    def test_no_fit_block(self):
        imp = self._parse(NO_FIT)
        self.assertEqual(imp.layout, "columns")
        self.assertEqual(len(imp.blocks), 1)
        b = imp.blocks[0]
        self.assertEqual((b.cycle, b.sample, b.scan_name),
                         (0, "TestSample", "X1 Scan"))
        self.assertEqual(b.hv, 1000.0)
        self.assertEqual(b.dwell_total, 1.0)
        self.assertEqual(b.ke, (100.0, 101.0, 102.0))
        self.assertEqual(b.counts, (10.0, 20.0, 15.0))
        self.assertEqual(b.be, (900.0, 899.0, 898.0))
        self.assertEqual(b.cps, (10.0, 20.0, 15.0))
        self.assertIsNone(b.background_cps)
        self.assertIsNone(b.envelope_cps)
        self.assertEqual(b.components, [])

    def test_background_only_block(self):
        imp = self._parse(BG_ONLY)
        b = imp.blocks[0]
        self.assertEqual(b.background_cps, (10.0, 10.0, 10.0))
        self.assertEqual(b.envelope_cps, (10.0, 10.0, 10.0))
        self.assertEqual(b.components, [])

    def test_doublet_component_background_subtracted(self):
        imp = self._parse(DOUBLET)
        b = imp.blocks[0]
        self.assertEqual(len(b.components), 2)
        a, c = b.components
        self.assertEqual((a.name, a.position_be), ("Peak A", 500.0))
        self.assertEqual((c.name, c.position_be), ("Peak A", 502.0))
        # component_col had background added in (12.0 = 5.0 bg + 7.0 peak);
        # parse() must subtract it back out (peak-only, like
        # lineshapes.component_curve()'s own convention)
        self.assertEqual(a.curve_cps, (7.0, 18.0, 12.0))
        self.assertEqual(c.curve_cps, (5.5, 15.2, 10.3))
        # Envelope == Background + sum(peak-only components)
        env = [b.background_cps[i] + a.curve_cps[i] + c.curve_cps[i]
               for i in range(3)]
        self.assertEqual(tuple(env), b.envelope_cps)

    def test_two_blocks_in_one_file(self):
        imp = self._parse(TWO_BLOCKS)
        self.assertEqual(len(imp.blocks), 2)
        self.assertEqual([b.scan_name for b in imp.blocks],
                         ["X1 Scan", "X2 Scan"])
        self.assertEqual([b.block_index for b in imp.blocks], [0, 1])


# ------------------------------------------------------------ rows layout
ROWS_TWO_SPECTRA = (
    "Name,,,Name,\n"
    "Position,,,Position,\n"
    "FWHM,,,FWHM,\n"
    "Area,,,Area,\n"
    "Lineshape,,,Lineshape,\n"
    'B.E.,"Cycle 0:TestSample:X1 Scan:CPS",,B.E.,"Cycle 0:TestSample:X2 Scan:CPS"\n'
    "900.0,10.0,,850.0,5.0\n"
    "899.0,20.0,,849.0,6.0\n"
    "898.0,15.0,,,\n"
)


class TestParseRows(unittest.TestCase):
    def _parse(self, text):
        path = _write(text)
        try:
            return casacsv.parse(path)
        finally:
            os.remove(path)

    def test_two_spectra_short_second_one(self):
        imp = self._parse(ROWS_TWO_SPECTRA)
        self.assertEqual(imp.layout, "rows")
        self.assertEqual(len(imp.blocks), 2)
        x1, x2 = imp.blocks
        self.assertEqual((x1.sample, x1.scan_name), ("TestSample", "X1 Scan"))
        self.assertEqual(x1.be, (900.0, 899.0, 898.0))
        self.assertEqual(x1.cps, (10.0, 20.0, 15.0))
        self.assertIsNone(x1.ke)
        self.assertIsNone(x1.hv)
        # X2's third row is blank -- it must stop there, not crash or pad
        self.assertEqual((x2.sample, x2.scan_name), ("TestSample", "X2 Scan"))
        self.assertEqual(x2.be, (850.0, 849.0))
        self.assertEqual(x2.cps, (5.0, 6.0))


# --------------------------------------------------------------- real files
PTCL2_CASA_CSV_DIR = os.environ.get(
    "XPS_PTCL2_CASA_CSV_DIR", r"D:\Temp\for claude files\PtCl2_new")


def _real_csv(name):
    path = os.path.join(PTCL2_CASA_CSV_DIR, name)
    return path if os.path.isfile(path) else None


def _columns_csv():
    return _real_csv("PtCl2_casa_output_columns.csv")


def _rows_csv():
    return _real_csv("PtCl2_casa_output_rows.csv")


def _refitted_vms():
    path = os.environ.get(
        "XPS_PTCL2_REFITTED_VMS",
        os.path.join(PTCL2_CASA_CSV_DIR, "PtCl2_refitted.vms"))
    return path if os.path.isfile(path) else None


@unittest.skipUnless(HAVE_NP and _columns_csv(),
                     "PtCl2_casa_output_columns.csv not present")
class TestRealColumnsFile(unittest.TestCase):
    """Pins the two numeric facts the whole module's design depends on,
    confirmed on the real PtCl2_refitted.vms export."""

    def test_counts_equals_cps_times_dwell_total(self):
        imp = casacsv.parse(_columns_csv())
        b = next(b for b in imp.blocks
                 if b.sample == "PtCl2 LA(m)" and b.scan_name == "Cl2p Scan")
        for c, p in zip(b.counts, b.cps):
            self.assertAlmostEqual(c, p * b.dwell_total, places=4)

    def test_envelope_equals_background_plus_components(self):
        imp = casacsv.parse(_columns_csv())
        b = next(b for b in imp.blocks
                 if b.sample == "PtCl2 LA(m)" and b.scan_name == "Cl2p Scan")
        for i in range(len(b.be)):
            total = b.background_cps[i] + sum(c.curve_cps[i]
                                              for c in b.components)
            self.assertAlmostEqual(total, b.envelope_cps[i], places=1)


@unittest.skipUnless(HAVE_NP and _columns_csv() and _rows_csv(),
                     "both PtCl2 CSV exports not present")
class TestRealFilesCrossCheck(unittest.TestCase):
    def test_rows_and_columns_layouts_agree(self):
        cols = casacsv.parse(_columns_csv())
        rows = casacsv.parse(_rows_csv())
        c = next(b for b in cols.blocks
                 if b.sample == "PtCl2 LA(m)" and b.scan_name == "Cl2p Scan")
        r = next(b for b in rows.blocks
                 if b.sample == "PtCl2 LA(m)" and b.scan_name == "Cl2p Scan")
        self.assertEqual(len(c.cps), len(r.cps))
        for a, b_ in zip(c.cps, r.cps):
            self.assertAlmostEqual(a, b_, places=2)


@unittest.skipUnless(HAVE_NP and _columns_csv() and _refitted_vms(),
                     "PtCl2_refitted.vms + its CSV export not present")
class TestRealEndToEndMatch(unittest.TestCase):
    def test_every_fitted_region_component_aligns(self):
        doc = readers.load_file(_refitted_vms())
        imp = casacsv.parse(_columns_csv())
        report = casacsv.match_to_regions(imp.blocks, doc.regions)
        fitted_names = {"C 1s", "Cl 2p", "Pt 4d", "Pt 4f", "Pt 4p"}
        checked = 0
        for res in report.results:
            if res.region is None or res.region.name not in fitted_names:
                continue
            if res.block.scan_name.endswith("Scan2"):
                continue
            self.assertEqual(res.reason, "",
                             f"{res.region.sample}/{res.region.name}: "
                             f"{res.reason}")
            self.assertEqual(res.n_components_aligned,
                             res.n_components_total)
            checked += 1
        self.assertEqual(checked, 10)     # 5 fitted regions x 2 samples

    def test_curves_prefer_csv_beats_reconstruction(self):
        doc = readers.load_file(_refitted_vms())
        imp = casacsv.parse(_columns_csv())
        report = casacsv.match_to_regions(imp.blocks, doc.regions)
        casacsv.apply_matches(report)
        r = next(r for r in doc.regions
                 if r.sample == "PtCl2 LA(m)" and r.name == "Cl 2p")
        dwell, scans = r.dwell_and_scans()
        recon = casafit.curves(r.fit, r.energy, r.counts, r.photon_energy,
                               dwell, scans, prefer_csv=False)[0]
        via_csv = casafit.curves(r.fit, r.energy, r.counts, r.photon_energy,
                                 dwell, scans, prefer_csv=True)[0]
        self.assertTrue(recon.approximate)
        self.assertFalse(via_csv.approximate)
        self.assertLess(via_csv.residual_rms, recon.residual_rms)


@unittest.skipUnless(HAVE_NP and _rows_csv() and _refitted_vms(),
                     "PtCl2_refitted.vms + its rows CSV export not present")
class TestRealEndToEndMatchRowsLayout(unittest.TestCase):
    """The "rows" layout has no raw K.E./Counts, so it relies entirely on
    the BE-range + point-count fallback -- this used to compare the CSV
    block's full-scan range against a FitRegion's own narrower fit window
    and so matched nothing at all (a real bug the user hit). Mirrors
    TestRealEndToEndMatch's own columns-layout checks to confirm the fix
    brings rows up to the same result."""

    def test_every_fitted_region_component_aligns(self):
        doc = readers.load_file(_refitted_vms())
        imp = casacsv.parse(_rows_csv())
        report = casacsv.match_to_regions(imp.blocks, doc.regions)
        fitted_names = {"C 1s", "Cl 2p", "Pt 4d", "Pt 4f", "Pt 4p"}
        checked = 0
        for res in report.results:
            if res.region is None or res.region.name not in fitted_names:
                continue
            if res.block.scan_name.endswith("Scan2"):
                continue
            self.assertEqual(res.reason, "",
                             f"{res.region.sample}/{res.region.name}: "
                             f"{res.reason}")
            self.assertEqual(res.n_components_aligned,
                             res.n_components_total)
            checked += 1
        self.assertEqual(checked, 10)     # 5 fitted regions x 2 samples

    def test_curves_prefer_csv_beats_reconstruction(self):
        doc = readers.load_file(_refitted_vms())
        imp = casacsv.parse(_rows_csv())
        report = casacsv.match_to_regions(imp.blocks, doc.regions)
        casacsv.apply_matches(report)
        r = next(r for r in doc.regions
                 if r.sample == "PtCl2 LA(m)" and r.name == "Cl 2p")
        dwell, scans = r.dwell_and_scans()
        recon = casafit.curves(r.fit, r.energy, r.counts, r.photon_energy,
                               dwell, scans, prefer_csv=False)[0]
        via_csv = casafit.curves(r.fit, r.energy, r.counts, r.photon_energy,
                                 dwell, scans, prefer_csv=True)[0]
        self.assertFalse(via_csv.approximate)
        self.assertLess(via_csv.residual_rms, recon.residual_rms)


# ------------------------------------------------------------- matching
def _mk_region(name, sample, be, counts, hv, dwell=0.1, scans=1, fit=None):
    r = Region(name=name, index=0, offset=0, energy=list(be),
              counts=list(counts), decodable=True, sample=sample,
              photon_energy=hv, dwell=dwell, source="a.vms")
    r.extra["n_scans"] = scans
    r.fit = fit
    return r


def _mk_fit(region_name, comps):
    fr = casafit.FitRegion(name=region_name, background="Shirley",
                           start_ke=0.0, end_ke=1e9)
    return casafit.Fit(regions=[fr], components=list(comps))


class TestMatchToRegions(unittest.TestCase):
    def test_disambiguates_identical_range_by_raw_counts(self):
        hv = 1000.0
        be = [10.0, 9.0, 8.0]
        counts_a = [100.0, 110.0, 120.0]
        counts_b = [200.0, 210.0, 220.0]
        fit_a = _mk_fit("R", [])
        fit_a.regions[0].start_ke = hv - max(be)
        fit_a.regions[0].end_ke = hv - min(be)
        region_a = _mk_region("R", "S", be, counts_a, hv, fit=fit_a)
        region_b = _mk_region("R", "S", be, counts_b, hv, fit=None)
        block_a = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="columns", cycle=0,
            sample="S", scan_name="R Scan",
            hv=hv, dwell_total=0.1,
            ke=tuple(hv - b for b in be), counts=tuple(counts_a),
            be=tuple(be), cps=tuple(c / 0.1 for c in counts_a),
            background_cps=tuple(c / 0.1 for c in counts_a),
            envelope_cps=tuple(c / 0.1 for c in counts_a), components=[])
        report = casacsv.match_to_regions([block_a], [region_a, region_b])
        self.assertEqual(len(report.results), 1)
        self.assertIs(report.results[0].region, region_a)
        self.assertEqual(report.results[0].reason, "")

    def test_ambiguous_when_only_be_cps_and_ranges_collide(self):
        hv = 1000.0
        be = [10.0, 9.0, 8.0]
        fit_a = _mk_fit("R", [])
        fit_b = _mk_fit("R", [])
        region_a = _mk_region("R", "S", be, [1, 2, 3], hv, fit=fit_a)
        region_b = _mk_region("R", "S", be, [1, 2, 3], hv, fit=fit_b)
        fit_a.regions[0].start_ke = min(hv - b for b in be)
        fit_a.regions[0].end_ke = max(hv - b for b in be)
        fit_b.regions[0].start_ke = fit_a.regions[0].start_ke
        fit_b.regions[0].end_ke = fit_a.regions[0].end_ke
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="rows", cycle=0,
            sample="S", scan_name="R Scan", hv=None, dwell_total=None,
            ke=None, counts=None, be=tuple(be), cps=(1.0, 2.0, 3.0),
            background_cps=None, envelope_cps=None, components=[])
        report = casacsv.match_to_regions([block], [region_a, region_b])
        self.assertIsNone(report.results[0].region)
        self.assertTrue(report.results[0].reason.startswith("ambiguous"))

    def test_rows_layout_matches_by_full_region_span_not_fit_window(self):
        """Regression for the real bug: a rows-layout block (no raw K.E./
        Counts) has to fall back to BE range + point count, and that
        fallback must compare against the REGION's own full acquisition
        span, not a FitRegion's own narrower fit window -- a real CSV
        export always covers the whole scan, while start_ke/end_ke only
        bounds the portion CasaXPS fit a background over inside it (e.g.
        the real Cl 2p region: fit window 194.4-209.0 eV, full scan
        185.1-215.1 eV). Comparing against the fit window instead (the
        original bug) made every rows-layout block match nothing."""
        hv = 1000.0
        be = [20.0 - i for i in range(21)]           # full scan: 20..0 eV
        fc = casafit.FitComponent(name="A", pos_ke=hv - 12.0, region="R")
        fit = _mk_fit("R", [fc])
        fit.regions[0].start_ke = hv - 12.0           # narrow fit window:
        fit.regions[0].end_ke = hv - 8.0              # BE 8..12, not 0..20
        region = _mk_region("R", "S", be, [1.0] * 21, hv, fit=fit)
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="rows", cycle=0,
            sample="S", scan_name="R Scan", hv=None, dwell_total=None,
            ke=None, counts=None, be=tuple(be), cps=tuple([1.0] * 21),
            background_cps=None, envelope_cps=None, components=[
                casacsv.CsvComponent(name="A", position_be=12.0, fwhm=1.0,
                                     area=1.0, lineshape="GL(30)",
                                     curve_cps=tuple([0.1] * 21))])
        report = casacsv.match_to_regions([block], [region])
        self.assertIs(report.results[0].region, region)
        self.assertEqual(report.results[0].reason, "")

    def test_several_fit_windows_sharing_one_block_all_align(self):
        """Regression for a real file: a combined "S2p B1s Scan" is fitted
        as two separate, non-overlapping named CasaXPS regions ("S 2p" and
        "P 2s") on ONE spectrum/scan, so their union -- not either one
        alone -- equals the CSV block's own BE range. The old code required
        a single FitRegion's own window to match the whole block, so
        neither ever matched ("none spans this CSV block's own BE range")
        even though each region's own window individually falls inside the
        block. Both must now align independently from the one shared
        block."""
        hv = 1000.0
        be = [20.0 - i for i in range(21)]           # full scan: 20..0 eV
        fc_a = casafit.FitComponent(name="a1", pos_ke=hv - 16.0, region="A")
        fc_b = casafit.FitComponent(name="b1", pos_ke=hv - 4.0, region="B")
        fr_a = casafit.FitRegion(name="A", background="Linear",
                                 start_ke=hv - 18.0, end_ke=hv - 14.0)
        fr_b = casafit.FitRegion(name="B", background="Shirley",
                                 start_ke=hv - 6.0, end_ke=hv - 2.0)
        fit = casafit.Fit(regions=[fr_a, fr_b], components=[fc_a, fc_b])
        region = _mk_region("R", "S", be, [1.0] * 21, hv, fit=fit)
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="rows", cycle=0,
            sample="S", scan_name="A B Scan", hv=None, dwell_total=None,
            ke=None, counts=None, be=tuple(be), cps=tuple([1.0] * 21),
            background_cps=None, envelope_cps=None, components=[
                casacsv.CsvComponent(name="a1", position_be=16.0, fwhm=1.0,
                                     area=1.0, lineshape="GL(30)",
                                     curve_cps=tuple([0.1] * 21)),
                casacsv.CsvComponent(name="b1", position_be=4.0, fwhm=1.0,
                                     area=1.0, lineshape="GL(30)",
                                     curve_cps=tuple([0.2] * 21))])
        report = casacsv.match_to_regions([block], [region])
        by_fit_region = {res.fit_region.name: res for res in report.results}
        self.assertEqual(set(by_fit_region), {"A", "B"})
        for res in by_fit_region.values():
            self.assertEqual(res.reason, "")
            self.assertIsNotNone(res.csv_curves)

    def test_unmatched_sample_reported(self):
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="columns", cycle=0,
            sample="Nowhere", scan_name="R Scan", hv=1000.0,
            dwell_total=0.1, ke=(1.0,), counts=(1.0,), be=(1.0,),
            cps=(10.0,), background_cps=None, envelope_cps=None,
            components=[])
        region = _mk_region("R", "S", [1.0], [1.0], 1000.0)
        report = casacsv.match_to_regions([block], [region])
        self.assertEqual(report.unmatched_samples, ["Nowhere"])

    def test_unfitted_region_is_skipped_not_synthesized(self):
        hv = 1000.0
        be = [10.0, 9.0, 8.0]
        counts = [100.0, 110.0, 120.0]
        region = _mk_region("R", "S", be, counts, hv, fit=None)
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="columns", cycle=0,
            sample="S", scan_name="R Scan", hv=hv, dwell_total=0.1,
            ke=tuple(hv - b for b in be), counts=tuple(counts),
            be=tuple(be), cps=tuple(c / 0.1 for c in counts),
            background_cps=None, envelope_cps=None, components=[])
        report = casacsv.match_to_regions([block], [region])
        self.assertIsNone(region.fit)
        self.assertIn("no CasaXPS fit", report.results[0].reason)

    def test_doublet_aligned_by_position_not_column_order(self):
        hv = 1000.0
        fc_near = casafit.FitComponent(name="A", pos_ke=hv - 500.0, region="R")
        fc_far = casafit.FitComponent(name="A", pos_ke=hv - 502.0, region="R")
        fit = _mk_fit("R", [fc_near, fc_far])
        be = [10.0, 9.0, 8.0]
        fit.regions[0].start_ke = hv - max(be)
        fit.regions[0].end_ke = hv - min(be)
        region = _mk_region("R", "S", be, [10.0, 10.0, 10.0], hv, fit=fit)
        # CSV columns swapped relative to fit component order: the "502"
        # position column comes first in the file
        cc_far = casacsv.CsvComponent(name="A", position_be=502.0, fwhm=1.0,
                                      area=1.0, lineshape="GL(30)",
                                      curve_cps=(1.0, 2.0, 3.0))
        cc_near = casacsv.CsvComponent(name="A", position_be=500.0, fwhm=1.0,
                                       area=1.0, lineshape="GL(30)",
                                       curve_cps=(4.0, 5.0, 6.0))
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="columns", cycle=0,
            sample="S", scan_name="R Scan", hv=hv, dwell_total=0.1,
            ke=tuple(hv - b for b in be), counts=(10.0, 10.0, 10.0),
            be=tuple(be), cps=(100.0, 100.0, 100.0),
            background_cps=(0.0, 0.0, 0.0), envelope_cps=(5.0, 7.0, 9.0),
            components=[cc_far, cc_near])
        report = casacsv.match_to_regions([block], [region])
        res = report.results[0]
        self.assertEqual(res.reason, "")
        got = {id(c): v for c, v in res.csv_curves.components}
        self.assertEqual(got[id(fc_near)], (4.0, 5.0, 6.0))
        self.assertEqual(got[id(fc_far)], (1.0, 2.0, 3.0))

    def test_all_or_nothing_when_a_component_is_missing(self):
        hv = 1000.0
        fc_a = casafit.FitComponent(name="A", pos_ke=hv - 500.0, region="R")
        fc_b = casafit.FitComponent(name="B", pos_ke=hv - 510.0, region="R")
        fit = _mk_fit("R", [fc_a, fc_b])
        fit.regions[0].start_ke = 0.0
        fit.regions[0].end_ke = 1e6
        be = [10.0, 9.0, 8.0]
        region = _mk_region("R", "S", be, [100.0, 100.0, 100.0], hv, fit=fit)
        cc_a = casacsv.CsvComponent(name="A", position_be=500.0, fwhm=1.0,
                                    area=1.0, lineshape="GL(30)",
                                    curve_cps=(1.0, 2.0, 3.0))
        block = casacsv.CsvBlock(
            source="x.csv", block_index=0, layout="columns", cycle=0,
            sample="S", scan_name="R Scan", hv=hv, dwell_total=0.1,
            ke=tuple(hv - b for b in be), counts=(10.0, 10.0, 10.0),
            be=tuple(be), cps=(100.0, 100.0, 100.0),
            background_cps=(0.0, 0.0, 0.0), envelope_cps=(1.0, 2.0, 3.0),
            components=[cc_a])
        report = casacsv.match_to_regions([block], [region])
        res = report.results[0]
        self.assertIsNone(res.csv_curves)
        self.assertIn("B", res.reason)


# --------------------------------------------------- casafit.curves(prefer_csv)
@unittest.skipUnless(HAVE_NP, "numpy not installed")
class TestCurvesPreferCsv(unittest.TestCase):
    def _build(self):
        hv = 1000.0
        fc = casafit.FitComponent(name="A", pos_ke=hv - 5.0, region="R",
                                  area=10.0, fwhm=1.0, shape="GL(30)")
        fr = casafit.FitRegion(name="R", background="Shirley",
                               start_ke=990.0, end_ke=1000.0)
        fit = casafit.Fit(regions=[fr], components=[fc])
        n = 21
        be = [10.0 - i * 0.5 for i in range(n)]   # 10..0, ke 990..1000
        ke_axis = tuple(hv - b for b in be)
        csv_bg = tuple(2.0 for _ in ke_axis)
        csv_comp = tuple(1.0 for _ in ke_axis)
        csv_env = tuple(b + c for b, c in zip(csv_bg, csv_comp))
        fr.csv_curves = casafit.CsvCurves(
            ke=ke_axis, background=csv_bg,
            components=((fc, csv_comp),), envelope=csv_env, source="x.csv")
        counts = [3.0 for _ in be]     # scale=1 -> counts == cps
        return fit, be, counts, hv

    def test_prefer_csv_true_uses_the_csv_arrays(self):
        fit, be, counts, hv = self._build()
        cv = casafit.curves(fit, be, counts, hv, dwell=1.0, scans=1,
                            prefer_csv=True)[0]
        self.assertFalse(cv.approximate)
        vals = [v for v in cv.background if v == v]   # drop NaN
        self.assertTrue(all(abs(v - 2.0) < 1e-9 for v in vals))
        env = [v for v in cv.envelope if v == v]
        self.assertTrue(all(abs(v - 3.0) < 1e-9 for v in env))

    def test_prefer_csv_false_is_unchanged_reconstruction(self):
        fit, be, counts, hv = self._build()
        cv = casafit.curves(fit, be, counts, hv, dwell=1.0, scans=1,
                            prefer_csv=False)[0]
        self.assertTrue(cv.approximate is False or cv.approximate is True)
        # must differ from the literal CSV-flat background (2.0 everywhere)
        # since it's reconstructed from the data instead
        vals = [v for v in cv.background if v == v]
        self.assertFalse(all(abs(v - 2.0) < 1e-9 for v in vals))

    def test_prefer_csv_true_with_no_csv_curves_falls_through(self):
        fit, be, counts, hv = self._build()
        fit.regions[0].csv_curves = None
        with_csv = casafit.curves(fit, be, counts, hv, dwell=1.0, scans=1,
                                  prefer_csv=True)[0]
        without = casafit.curves(fit, be, counts, hv, dwell=1.0, scans=1,
                                 prefer_csv=False)[0]
        self.assertEqual(with_csv.background, without.background)

    def test_prefer_csv_true_with_incomplete_components_falls_through(self):
        fit, be, counts, hv = self._build()
        fc2 = casafit.FitComponent(name="B", pos_ke=hv - 6.0, region="R",
                                   area=5.0, fwhm=1.0, shape="GL(30)")
        fit.components.append(fc2)     # a second component with no CSV curve
        with_csv = casafit.curves(fit, be, counts, hv, dwell=1.0, scans=1,
                                  prefer_csv=True)[0]
        without = casafit.curves(fit, be, counts, hv, dwell=1.0, scans=1,
                                 prefer_csv=False)[0]
        self.assertEqual(with_csv.background, without.background)
        self.assertEqual(len(with_csv.components), len(without.components))


if __name__ == "__main__":
    unittest.main()
