"""casaquant.py, checked against real CasaXPS exports.

Fixture text below is copied verbatim (tabs and all) from two real
directories: ``D:\\Temp\\for claude files\\PET`` (one sample, "Sample
Name: " prefixed, has a D-parameter file) and ``D:\\Temp\\for claude
files\\PtCl2`` (two samples, unprefixed identifiers, duplicate region
names, no D-parameter file). A third, synthetic fixture isolates the
FWHM/Raw-Area column-order gotcha the real PET file happens not to expose
(there, FWHM and Raw Area are coincidentally both 13.50).
"""

import os
import tempfile
import unittest

import casaquant

PET_SURVEY = (
    "D:\\Temp\\for claude files\\PET\\Fitted PET Beamson and Briggs.vms\t\n"
    "\n"
    "Sample Identifier\tName\tPosition\tFWHM\tRaw Area\t%At Conc\t\n"
    "Sample Name: Poly(ethylene terephthalate)\tO 1s\t531.30\t3.19\t52119.73\t28.44\t\n"
    "\tC 1s\t283.83\t2.73\t44768.19\t71.56\t\n"
    "\n"
    "\n"
    "Peak Area Results Compact form (Atomic Concentrations)\n"
    "Name\t%Conc\tSample Identifier\n"
    "\tSt.Dev.\n"
    "O 1s\t28.44\tSample Name: Poly(ethylene terephthalate)\n"
    "\t \n"
    "C 1s\t71.56\t\n"
    "\t \n"
    "\n"
    "\n"
    "Peak Area Results\n"
    "\n"
    "Sample Name: Poly(ethylene terephthalate)\tO 1s\tC 1s\t\n"
    "%Conc\t28.44\t71.56\t\n"
    "St.Dev.\t \t \t\n"
    "\n"
    "Peak Area Results (RSF Corrected Intensities and St.Dev.)\n"
    "\n"
    "Sample Name: Poly(ethylene terephthalate)\tO 1s\tC 1s\t\n"
    "Area\t17788.3\t44768.2\t\n"
    "St.Dev.\t \t \t\n"
)

PET_REGIONS = (
    "D:\\Temp\\for claude files\\PET\\Fitted PET Beamson and Briggs.vms\t\n"
    "\n"
    "Sample Identifier\tName\tPosition\tRaw Area\tArea/(RSF*T*MFP)\t%At Conc\t\n"
    "Sample Name: Poly(ethylene terephthalate)\tC 1s (Ring)\t284.67\t6769.34\t24350.15\t42.39\t\n"
    "\tC 1s (C-O)\t286.34\t1829.84\t6582.14\t11.46\t\n"
    "\tC 1s (COO)\t288.71\t1829.84\t6582.14\t11.46\t\n"
    "\tC 1s (Sat)\t291.16\t826.09\t2971.56\t5.17\t\n"
    "\tC 1s (Sat)\t294.53\t182.24\t655.53\t1.14\t\n"
    "\tO 1s (C-O)\t533.24\t6829.35\t8755.58\t15.24\t\n"
    "\tO 1s (C=O)\t531.66\t4738.52\t6075.02\t10.57\t\n"
    "\tO 1s (Sat)\t535.19\t375.37\t481.25\t0.84\t\n"
    "\tO 1s (Sat)\t538.10\t160.48\t205.75\t0.36\t\n"
    "\tO 1s (Sat)\t539.15\t614.91\t788.35\t1.37\t\n"
    "\n"
    "\n"
    "Peak Area Results Compact form (Atomic Concentrations)\n"
)

PET_DPARAM = (
    "Fitted PET Beamson and Briggs_envelope_diff\t\n"
    "\n"
    "Sample Identifier\tName\tPosition\tFWHM\tRaw Area\t%At Conc\t\n"
    "Sample Name: Poly(ethylene terephthalate)\tC KVV\t1218.72\t13.50\t13.50\t100.00\t\n"
    "\n"
    "\n"
    "Peak Area Results Compact form (Atomic Concentrations)\n"
)

PTCL2_SURVEY = (
    "D:\\Temp\\for claude files\\PtCl2\\PtCl2_quantified.vms\t\tPtCl2\t1 n/a \t"
    "PtCl2\t2 n/a \tPtO2xH2O\t3 n/a \tPtO2xH2O\t4 n/a \tPtO2xH2O\t5 n/a \t"
    "PtO2xH2O\t6 n/a \n"
    "\n"
    "Sample Identifier\tName\tPosition\tFWHM\tRaw Area\t%At Conc\t\n"
    "PtCl2\tO 1s\t532.70\t2.10\t32369.00\t1.82\t\n"
    "\tC 1s\t284.91\t2.72\t183090.45\t27.46\t\n"
    "\tCl 2p\t200.16\t3.12\t729703.97\t46.80\t\n"
    "\tPt 4f\t73.25\t2.93\t2596166.58\t23.93\t\n"
    "PtCl2 area2\tO 1s\t532.46\t2.41\t19571.25\t1.19\t\n"
    "\tC 1s\t284.89\t2.44\t135162.83\t21.99\t\n"
    "\tCl 2p\t200.15\t3.13\t741394.50\t51.59\t\n"
    "\tPt 4f\t73.29\t2.63\t2521855.81\t25.22\t\n"
    "\n"
    "\n"
    "Peak Area Results Compact form (Atomic Concentrations)\n"
    "Name\t%Conc\tSample Identifier\n"
    "\tSt.Dev.\n"
    "O 1s\t1.82\tPtCl2\n"
    "\t \n"
    "\n"
    "\n"
    "Peak Area Results\n"
    "\n"
    "PtCl2\tO 1s\tC 1s\tCl 2p\tPt 4f\t\n"
    "%Conc\t1.82\t27.46\t46.80\t23.93\t\n"
    "St.Dev.\t \t \t \t \t\n"
    "PtCl2 area2\tO 1s\tC 1s\tCl 2p\tPt 4f\t\n"
    "%Conc\t1.19\t21.99\t51.59\t25.22\t\n"
    "St.Dev.\t \t \t \t \t\n"
    "\n"
    "Peak Area Results (RSF Corrected Intensities and St.Dev.)\n"
    "\n"
    "PtCl2\tO 1s\tC 1s\tCl 2p\tPt 4f\t\n"
    "Area\t12319.9\t186183\t317345\t162243\t\n"
)

PTCL2_REGIONS = (
    "D:\\Temp\\for claude files\\PtCl2\\PtCl2_quantified.vms\t\tPtCl2\t1 n/a \t"
    "PtCl2\t2 n/a \tPtO2xH2O\t3 n/a \tPtO2xH2O\t4 n/a \tPtO2xH2O\t5 n/a \t"
    "PtO2xH2O\t6 n/a \n"
    "\n"
    "Sample Identifier\tName\tPosition\tRaw Area\tArea/(RSF*T*MFP)\t%At Conc\t\n"
    "PtCl2\tC 1s\t284.69\t18766.53\t19751.56\t16.84\t\n"
    "\tCl 2p x\t201.14\t3350.83\t1556.91\t1.33\t\n"
    "\tCl 2p x\t202.76\t1675.41\t778.33\t0.66\t\n"
    "\tCl 2p \t199.75\t52579.65\t24434.26\t20.83\t\n"
    "\tCl 2p #\t201.38\t26289.83\t12214.46\t10.41\t\n"
    "\tPt 4d\t316.37\t223191.32\t12260.78\t10.45\t\n"
    "\tPt 4d\t333.27\t148801.65\t8161.31\t6.96\t\n"
    "\tPt 4f\t73.24\t155571.10\t10848.54\t9.25\t\n"
    "\tPt 4f\t76.56\t116678.33\t8133.24\t6.93\t\n"
    "\tPt 4f loss\t78.42\t12203.18\t850.43\t0.73\t\n"
    "\tPt 4f loss\t81.72\t9152.38\t637.58\t0.54\t\n"
    "\tPt 4f\t84.99\t1453.45\t101.21\t0.09\t\n"
    "\tO 1s\t533.26\t4526.31\t1594.89\t1.36\t\n"
    "\tO 1s\t531.92\t2791.96\t983.81\t0.84\t\n"
    "\tPt 4s\t728.01\t27620.71\t14981.76\t12.77\t\n"
    "PtCl2 area2\tC 1s\t284.78\t15514.15\t16328.29\t22.13\t\n"
    "\tCl 2p\t199.74\t83471.26\t38789.56\t52.57\t\n"
    "\tPt 4f\t73.23\t152987.44\t10668.31\t14.46\t\n"
    "\tPt 4f\t76.54\t114740.58\t7998.11\t10.84\t\n"
    "\n"
    "\n"
    "Peak Area Results Compact form (Atomic Concentrations)\n"
)

# Synthetic: every column holds a distinct value, so a parser that read a
# column by position instead of by header name would return the wrong one.
# (The real PET D-param file can't catch this: FWHM and Raw Area are both
# 13.50 there by coincidence.)
SYNTHETIC_DPARAM = (
    "synthetic\t\n"
    "\n"
    "Sample Identifier\tName\tPosition\tFWHM\tRaw Area\t%At Conc\t\n"
    "Sample Name: X\tPeak A\t100.0\t5.5\t999.9\t11.1\t\n"
)
SYNTHETIC_REGIONS = (
    "synthetic\t\n"
    "\n"
    "Sample Identifier\tName\tPosition\tRaw Area\tArea/(RSF*T*MFP)\t%At Conc\t\n"
    "Sample Name: X\tPeak A\t100.0\t999.9\t888.8\t11.1\t\n"
)


def _make_folder(files):
    d = tempfile.mkdtemp(prefix="casaquant_test_")
    for name, text in files.items():
        with open(os.path.join(d, name), "w", encoding="latin-1", newline="") as fh:
            fh.write(text)
    return d


class SamplePrefixTests(unittest.TestCase):
    def test_strip_when_present(self):
        self.assertEqual(
            casaquant.strip_sample_prefix("Sample Name: Foo Bar"), "Foo Bar")
        self.assertEqual(
            casaquant.strip_sample_prefix("  sample name:   Foo  "), "Foo")

    def test_unchanged_when_absent(self):
        self.assertEqual(casaquant.strip_sample_prefix("PtCl2"), "PtCl2")
        self.assertEqual(casaquant.strip_sample_prefix("PtCl2 area2"),
                         "PtCl2 area2")


class FindTests(unittest.TestCase):
    def test_fuzzy_case_insensitive(self):
        folder = _make_folder({
            "Quant_Survey.TXT": PET_SURVEY,
            "quant_Region.txt": PET_REGIONS,       # singular, mixed case
            "Quant_Dparam.txt": PET_DPARAM,
        })
        found, notes = casaquant.find(folder)
        self.assertEqual(set(found), {"survey", "regions", "dparam"})
        self.assertEqual(notes, [])

    def test_none_found(self):
        folder = _make_folder({"readme.txt": "not a quant file"})
        found, notes = casaquant.find(folder)
        self.assertEqual(found, {})
        self.assertIsNone(casaquant.load(folder))

    def test_multiple_matches_noted(self):
        folder = _make_folder({
            "quant_survey.txt": PET_SURVEY,
            "quant_survey_old.txt": PET_SURVEY,
        })
        found, notes = casaquant.find(folder)
        self.assertIn("survey", found)
        self.assertEqual(len(notes), 1)


class ParsePetTests(unittest.TestCase):
    def test_survey(self):
        rows = casaquant.parse_survey(PET_SURVEY)
        self.assertEqual(rows, [
            {"sample": "Poly(ethylene terephthalate)", "element": "O 1s",
             "pct": 28.44},
            {"sample": "Poly(ethylene terephthalate)", "element": "C 1s",
             "pct": 71.56},
        ])

    def test_regions(self):
        rows = casaquant.parse_regions(PET_REGIONS)
        self.assertEqual(len(rows), 10)
        self.assertTrue(all(r["sample"] == "Poly(ethylene terephthalate)"
                            for r in rows))
        self.assertEqual(rows[0], {"sample": "Poly(ethylene terephthalate)",
                                   "name": "C 1s (Ring)", "position": 284.67,
                                   "at_pct": 42.39})
        self.assertEqual(rows[-1]["name"], "O 1s (Sat)")
        self.assertEqual(rows[-1]["position"], 539.15)
        self.assertEqual(rows[-1]["at_pct"], 1.37)

    def test_dparam(self):
        rows = casaquant.parse_dparam(PET_DPARAM)
        self.assertEqual(rows, [{"sample": "Poly(ethylene terephthalate)",
                                 "name": "C KVV", "fwhm": 13.50}])

    def test_load(self):
        folder = _make_folder({
            "quant_survey.txt": PET_SURVEY,
            "quant_regions.txt": PET_REGIONS,
            "quant_Dparam.txt": PET_DPARAM,
        })
        q = casaquant.load(folder)
        self.assertIsNotNone(q)
        self.assertEqual(list(q.samples), ["Poly(ethylene terephthalate)"])
        s = q.samples["Poly(ethylene terephthalate)"]
        self.assertEqual(len(s.survey), 2)
        self.assertEqual(len(s.regions), 10)
        self.assertEqual(len(s.dparam), 1)


class ParsePtCl2Tests(unittest.TestCase):
    """Two samples, unprefixed identifiers, duplicate region names, no
    D-parameter file."""

    def test_survey_two_samples(self):
        rows = casaquant.parse_survey(PTCL2_SURVEY)
        samples = {r["sample"] for r in rows}
        self.assertEqual(samples, {"PtCl2", "PtCl2 area2"})
        self.assertEqual(len(rows), 8)
        pt1 = {r["element"]: r["pct"] for r in rows if r["sample"] == "PtCl2"}
        self.assertEqual(pt1, {"O 1s": 1.82, "C 1s": 27.46, "Cl 2p": 46.80,
                              "Pt 4f": 23.93})
        pt2 = {r["element"]: r["pct"] for r in rows
              if r["sample"] == "PtCl2 area2"}
        self.assertEqual(pt2, {"O 1s": 1.19, "C 1s": 21.99, "Cl 2p": 51.59,
                              "Pt 4f": 25.22})

    def test_regions_duplicate_names_kept(self):
        rows = casaquant.parse_regions(PTCL2_REGIONS)
        pt1 = [r for r in rows if r["sample"] == "PtCl2"]
        pt2 = [r for r in rows if r["sample"] == "PtCl2 area2"]
        self.assertEqual(len(pt1), 15)
        self.assertEqual(len(pt2), 4)
        pt4d = [r for r in pt1 if r["name"] == "Pt 4d"]
        self.assertEqual(len(pt4d), 2)
        self.assertEqual({r["position"] for r in pt4d}, {316.37, 333.27})
        self.assertEqual({r["at_pct"] for r in pt4d}, {10.45, 6.96})
        # ad-hoc CasaXPS disambiguation suffixes survive untouched
        names = [r["name"] for r in pt1]
        self.assertIn("Cl 2p x", names)
        self.assertIn("Cl 2p #", names)
        self.assertEqual(names.count("Cl 2p x"), 2)

    def test_load_no_dparam(self):
        folder = _make_folder({
            "quant_survey.txt": PTCL2_SURVEY,
            "quant_regions.txt": PTCL2_REGIONS,
        })
        q = casaquant.load(folder)
        self.assertIsNotNone(q)
        self.assertEqual(set(q.samples), {"PtCl2", "PtCl2 area2"})
        for s in q.samples.values():
            self.assertEqual(s.dparam, [])


class ColumnByNameTests(unittest.TestCase):
    """A parser that read columns by position rather than by header name
    would mix these up; every column here holds a distinct value."""

    def test_dparam_column_order(self):
        row = casaquant.parse_dparam(SYNTHETIC_DPARAM)[0]
        self.assertEqual(row["fwhm"], 5.5)

    def test_regions_column_order(self):
        row = casaquant.parse_regions(SYNTHETIC_REGIONS)[0]
        self.assertEqual(row["position"], 100.0)
        self.assertEqual(row["at_pct"], 11.1)


if __name__ == "__main__":
    unittest.main()
