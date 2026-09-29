"""Generates real illustrative PNGs for the user manual by calling the
application's own Tk-free rendering code (plots.py, themes.py, covers.py,
report.py, resultspages.py, casafit.py, elements.py, reels.py) with small
synthetic example spectra. No Tkinter, no live GUI, no instrument files.

Run with the project's own virtualenv interpreter (has matplotlib, numpy,
reportlab, pymupdf, pillow already installed):
    ../.venv/Scripts/python.exe build_illustrations.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from PIL import Image, ImageChops

OUT = os.path.join(os.path.dirname(__file__), "figures")
os.makedirs(OUT, exist_ok=True)

HV = 1486.6  # Al Kalpha


# ----------------------------------------------------------------------
# synthetic Region factory
# ----------------------------------------------------------------------

def region(name, sample="S1", n=161, lo=280.0, hi=292.0, peak=284.8,
           amp=900.0, base=100.0, width=1.0, hv=HV,
           energy_label="Binding Energy", etch_level=None, etch_time=None,
           technique="XPS", extra_energy=None, extra_counts=None):
    """A synthetic Region: a single Gaussian-ish peak on a flat baseline,
    or (if extra_energy/extra_counts given) exactly those values."""
    from readers import Region
    if extra_energy is not None:
        e, c = list(extra_energy), list(extra_counts)
    else:
        e = [hi - i * (hi - lo) / (n - 1) for i in range(n)]
        c = [base + amp * np.exp(-((x - peak) / width) ** 2) for x in e]
    return Region(name=name, index=0, offset=0, energy=e, counts=c,
                  decodable=True, sample=sample, photon_energy=hv,
                  pass_energy=20.0, dwell=0.1, step=(hi - lo) / max(n - 1, 1),
                  energy_label=energy_label, technique=technique,
                  etch_level=etch_level, etch_time=etch_time,
                  source="demo.vms", count_units="counts/s",
                  count_label="Intensity")


def cycle_colours(pal, n):
    cyc = pal["cycle"]
    return [cyc[i % len(cyc)] for i in range(n)]


def save_fig(fig, path, dpi=150):
    fig.savefig(path, dpi=dpi, facecolor=fig.get_facecolor())
    print("wrote", path)


def crop_whitespace(path, pad=12, bg=(255, 255, 255)):
    im = Image.open(path).convert("RGB")
    bgim = Image.new("RGB", im.size, bg)
    diff = ImageChops.difference(im, bgim)
    bbox = diff.getbbox()
    if bbox:
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(im.width, x1 + pad)
        y1 = min(im.height, y1 + pad)
        im.crop((x0, y0, x1, y1)).save(path)


# ----------------------------------------------------------------------
# 1-3: stack / waterfall / heatmap views of a synthetic depth profile
# ----------------------------------------------------------------------

def depth_profile_regions(n_levels=8):
    regs = []
    for i in range(n_levels):
        amp = 900.0 * np.exp(-i / 4.0) + 60.0   # surface signal decays with depth
        peak = 284.8 + 0.02 * i                 # a tiny drift, for realism
        regs.append(region(f"C 1s", sample="Film A", peak=peak, amp=amp,
                           base=80.0, etch_level=i, etch_time=i * 300.0))
    return regs


def fig_stack():
    import plots
    import themes
    regs = [region("C 1s", sample=s, amp=a, peak=284.8 + d)
            for s, a, d in [("Film A", 900, 0.0), ("Film B", 700, 0.3),
                            ("Film C", 500, 0.6)]]
    pal = themes.PALETTES["Light"]
    cols = cycle_colours(pal, len(regs))
    with matplotlib.rc_context(themes.mpl_rc(pal)):
        fig = Figure(figsize=(9, 5.2), dpi=150)
        ax = fig.add_subplot(111)
        plots.draw_stack(ax, regs, 0.6, "None", None, cols, "C 1s",
                         "3 samples, stacked", (), False)
        fig.subplots_adjust(left=0.08, right=0.86, top=0.90, bottom=0.12)
        save_fig(fig, os.path.join(OUT, "fig_stack.png"))


def fig_waterfall():
    import plots
    import themes
    import viewdata
    regs = depth_profile_regions()
    zi = viewdata.ZInfo([r.etch_level for r in regs], "Etch level", "Etch level")
    pal = themes.PALETTES["Light"]
    with matplotlib.rc_context(themes.mpl_rc(pal)):
        fig = Figure(figsize=(9, 6.0), dpi=150)
        ax = fig.add_subplot(111, projection="3d")
        plots.draw_waterfall3d(ax, regs, zi, "None", cycle_colours(pal, len(regs)),
                               "C 1s", "Depth profile, 8 levels", pal)
        save_fig(fig, os.path.join(OUT, "fig_waterfall.png"))


def fig_heatmap():
    import plots
    import themes
    import viewdata
    from matplotlib.colors import LinearSegmentedColormap
    regs = depth_profile_regions()
    zi = viewdata.ZInfo([r.etch_level for r in regs], "Etch level", "Etch level")
    pal = themes.PALETTES["Light"]
    cmap = LinearSegmentedColormap.from_list("heat", ["#2C3E50", "#F2C14E", "#FFF7E0"])
    with matplotlib.rc_context(themes.mpl_rc(pal)):
        fig = Figure(figsize=(9, 5.2), dpi=150)
        ax = fig.add_subplot(111)
        plots.draw_heatmap(fig, ax, regs, zi, "None", cmap, "C 1s",
                           "Depth profile, 8 levels")
        fig.tight_layout()
        save_fig(fig, os.path.join(OUT, "fig_heatmap.png"))


# ----------------------------------------------------------------------
# 4: light vs dark theme comparison
# ----------------------------------------------------------------------

def fig_theme_compare():
    import plots
    import themes
    regs = [region("C 1s", sample=s, amp=a, peak=284.8 + d)
            for s, a, d in [("Film A", 900, 0.0), ("Film B", 700, 0.3)]]
    halves = []
    for theme_name in ("Light", "Dark"):
        pal = themes.PALETTES[theme_name]
        cols = cycle_colours(pal, len(regs))
        with matplotlib.rc_context(themes.mpl_rc(pal)):
            fig = Figure(figsize=(5.2, 4.6), dpi=150)
            fig.patch.set_facecolor(pal["bg"])
            ax = fig.add_subplot(111)
            plots.draw_stack(ax, regs, 0.6, "None", None, cols, "C 1s",
                             theme_name + " theme", (), False)
            fig.subplots_adjust(left=0.10, right=0.84, top=0.90, bottom=0.12)
            tmp = os.path.join(OUT, f"_theme_{theme_name}.png")
            save_fig(fig, tmp)
            halves.append(Image.open(tmp))
    w = sum(h.width for h in halves) + 20
    hgt = max(h.height for h in halves)
    combo = Image.new("RGB", (w, hgt), (255, 255, 255))
    x = 0
    for im in halves:
        combo.paste(im, (x, 0))
        x += im.width + 20
    out = os.path.join(OUT, "fig_theme_compare.png")
    combo.save(out)
    for theme_name in ("Light", "Dark"):
        os.remove(os.path.join(OUT, f"_theme_{theme_name}.png"))
    print("wrote", out)


# ----------------------------------------------------------------------
# 5: cover page design
# ----------------------------------------------------------------------

def fig_cover():
    import covers
    art = covers.art({"design": "ribbon", "image": "", "accent": "#2C3E50"}, "pdf")
    out = os.path.join(OUT, "fig_cover.png")
    with open(out, "wb") as f:
        f.write(art.data)
    print("wrote", out)


# ----------------------------------------------------------------------
# 6: a sample page from the PDF report
# ----------------------------------------------------------------------

def fig_report_page():
    import report
    import reportspec as rs
    from readers.base import SpectrumFile

    class Doc(SpectrumFile):
        def __init__(self, regions, path):
            super().__init__()
            self.path = path
            self.regions = regions
            self._finish()

    docs = [Doc([region("Survey", lo=0.0, hi=1200.0, n=241, peak=285.0,
                        amp=400.0, base=50.0),
                region("C 1s"), region("O 1s", lo=525.0, hi=540.0, peak=532.0)],
               "demo.vgd")]
    rows = [{"name": "demo.vgd", "format": "Thermo Avantage", "regions": 3,
            "size": 20480, "sha256": "ab" * 32}]
    details = {"title": "Thin film oxidation study", "customer": "Acme Coatings",
              "operator": "D. Morgan", "reference": "TF-2026-014",
              "summary": "A demonstration report used to illustrate this manual.",
              "methods": "Spectra were recorded with a monochromated Al "
                        "Kα source at 1486.6 eV.",
              "calibration": "Calibrated to the C 1s adventitious carbon "
                            "peak at 284.8 eV."}
    figs = [{"name": "Survey overview", "caption": "", "state": {}}]

    def render_figure(pdf, n, fig):
        f = Figure(figsize=(11.7, 8.3))
        ax = f.add_subplot(111)
        r = docs[0].regions[0]
        ax.plot(r.energy, r.counts, color="#0F6B8C")
        ax.set_xlabel("Binding energy (eV)")
        ax.set_ylabel("Intensity (counts/s)")
        ax.set_title(fig["name"])
        ax.invert_xaxis()
        pdf.savefig(f)
        return 1

    pdf_path = os.path.join(OUT, "_sample_report.pdf")
    report.build_report(pdf_path, details, "", rows, docs, figs,
                        render_figure, spec=rs.default_spec())

    import pymupdf as mu
    doc = mu.open(pdf_path)
    page_index = len(doc) - 1
    for i, page in enumerate(doc):
        text = page.get_text()
        if "abababab" in text:      # the fake sha256 -- unique to the files table
            page_index = i
            break
    pix = doc[page_index].get_pixmap(dpi=170)
    out = os.path.join(OUT, "fig_report_page.png")
    pix.save(out)
    doc.close()
    os.remove(pdf_path)
    print("wrote", out, "(page", page_index, ")")


# ----------------------------------------------------------------------
# 7: a sample quantification table
# ----------------------------------------------------------------------

def fig_quant_table():
    import resultspages as rp
    import pdfstyle
    from reportlab.platypus import SimpleDocTemplate
    from reportlab.lib.pagesizes import A4

    def row(name, rsf, area, states=(), background="Shirley"):
        comps = [{"name": n, "group": "", "index": -1, "be": 285.0,
                 "fwhm": 1.0, "area": a, "shape": "GL(30)", "rsf": rsf,
                 "gk": f"n{n}", "state": n} for n, a in states]
        return {"region": name, "background": background, "rsf": rsf,
               "area": area, "area_t": None, "basis": "data", "be_lo": 280.0,
               "be_hi": 290.0, "avg": 1, "rms": 0.018, "chi2_red": 1.21,
               "approximate": False, "background_known": True,
               "scale_known": True, "components": comps}

    lv = rp.Level(None)
    lv.entries = [{"spectrum": r["region"], "row": r} for r in [
        row("C 1s", 1.00, 620.0, states=[("C-C / C-H", 400.0), ("C-O", 140.0),
                                         ("O-C=O", 80.0)]),
        row("O 1s", 2.85, 980.0),
        row("Ti 2p", 7.91, 210.0),
    ]]
    rp._settle(lv, "Film A", [])
    sample = rp.Sample("f1/Film A", "Film A", [lv])
    results = rp.Results(samples=[sample])

    look = pdfstyle.look("#2C3E50")
    story = report_results_story(results, look)

    pdf_path = os.path.join(OUT, "_quant_table.pdf")
    doc = SimpleDocTemplate(pdf_path, pagesize=A4, leftMargin=18, rightMargin=18,
                            topMargin=18, bottomMargin=18)
    doc.build(story)

    import pymupdf as mu
    pdoc = mu.open(pdf_path)
    pix = pdoc[0].get_pixmap(dpi=200)
    out = os.path.join(OUT, "fig_quant_table.png")
    pix.save(out)
    pdoc.close()
    os.remove(pdf_path)
    crop_whitespace(out)
    print("wrote", out)


def report_results_story(results, look):
    import report
    return report.results_story(results, skip=(), look=look)


# ----------------------------------------------------------------------
# 8: a CasaXPS-style fit overlay
# ----------------------------------------------------------------------

def fig_casafit():
    import casafit
    import plots
    import themes

    hv = HV
    lo_be, hi_be = 280.0, 292.0
    n = 241
    be = [hi_be - i * (hi_be - lo_be) / (n - 1) for i in range(n)]
    ke = np.array([hv - b for b in be])

    fit_region = casafit.FitRegion(name="C 1s", background="Shirley",
                                   start_ke=float(ke.min()),
                                   end_ke=float(ke.max()))
    comp = casafit.FitComponent(name="C-C / C-H", shape="GL(30)", area=6000.0,
                                fwhm=1.2, pos_ke=hv - 284.8, region="C 1s")
    fit = casafit.Fit(regions=[fit_region], components=[comp])

    import lineshapes as ls
    peak = ls.component_curve(ke, "GL(30)", hv - 284.8, 1.2, 6000.0)
    step = 200.0 + 300.0 / (1.0 + np.exp((np.array(be) - 284.8) / 0.4))
    counts = (peak + step).tolist()

    reg = region("C 1s", energy_label="Binding Energy",
                extra_energy=be, extra_counts=counts)
    reg.fit = fit

    curves = casafit.curves(fit, be, counts, hv)
    pal = themes.PALETTES["Light"]
    with matplotlib.rc_context(themes.mpl_rc(pal)):
        fig = Figure(figsize=(9, 5.2), dpi=150)
        ax = fig.add_subplot(111)
        plots.draw_stack(ax, [reg], 0, "None", None, ["#0F6B8C"], "C 1s",
                         "CasaXPS fit: components, envelope, background",
                         (), False,
                         fit={"curves": curves,
                             "show": {"envelope": True, "components": True,
                                     "background": True}})
        fig.tight_layout()
        save_fig(fig, os.path.join(OUT, "fig_casafit.png"))


# ----------------------------------------------------------------------
# 9: ISS peak identification
# ----------------------------------------------------------------------

def fig_iss():
    import elements as el
    import plots
    import themes

    e0, ion, theta = 1000.0, "He+", 137.0
    marks = el.marks_for(["O", "Ti", "Fe"], e0, ion=ion, theta_deg=theta)

    ke = np.linspace(300.0, 1000.0, 701)
    counts = np.full_like(ke, 40.0)
    for _sym, energy in marks:
        counts += 1400.0 * np.exp(-((ke - energy) / 6.0) ** 2)

    reg = region("ISS", energy_label="Kinetic Energy", technique="ISS",
                extra_energy=ke.tolist(), extra_counts=counts.tolist())
    markers = [(energy, sym, True) for sym, energy in marks]

    pal = themes.PALETTES["Light"]
    with matplotlib.rc_context(themes.mpl_rc(pal)):
        fig = Figure(figsize=(9, 5.2), dpi=150)
        ax = fig.add_subplot(111)
        plots.draw_stack(ax, [reg], 0, "None", None, ["#0F6B8C"],
                         f"ISS: {ion} at {e0:.0f} eV, {theta:.0f}°",
                         "candidate elements marked", (), False,
                         markers=markers, scale="Kinetic")
        fig.tight_layout()
        save_fig(fig, os.path.join(OUT, "fig_iss.png"))


# ----------------------------------------------------------------------
# 10: REELS band-gap construction
# ----------------------------------------------------------------------

def fig_reels():
    import reels
    import plots
    import themes

    elastic0 = 1000.0
    ke = np.linspace(elastic0 - 12.0, elastic0 + 2.0, 561)
    loss = elastic0 - ke
    onset = 3.0
    y = (40.0
        + 6000.0 * np.exp(-(loss / 0.25) ** 2)
        + np.where(loss > onset, 350.0 * np.clip(loss - onset, 0, None) ** 1.2, 0.0))

    elastic = reels.elastic_peak(ke.tolist(), y.tolist())
    loss_list = reels.loss_axis(ke.tolist(), elastic)
    p1, p2 = (2.0, 45.0), (5.5, 900.0)
    result = reels.band_gap(loss_list, y.tolist(), p1, p2)
    reels_dict = {"elastic": elastic, "p1": p1, "p2": p2, **(result or {})}

    reg = region("REELS", energy_label="Kinetic Energy", technique="REELS",
                extra_energy=ke.tolist(), extra_counts=y.tolist())

    pal = themes.PALETTES["Light"]
    with matplotlib.rc_context(themes.mpl_rc(pal)):
        fig = Figure(figsize=(9, 5.2), dpi=150)
        ax = fig.add_subplot(111)
        gap = reels_dict.get("gap")
        subtitle = f"Eg = {gap:.2f} eV" if gap else "band-gap construction"
        plots.draw_stack(ax, [reg], 0, "None", None, ["#0F6B8C"],
                         "REELS loss spectrum", subtitle, (), False,
                         reels=reels_dict, scale="Kinetic")
        fig.tight_layout()
        save_fig(fig, os.path.join(OUT, "fig_reels.png"))


# ----------------------------------------------------------------------
# 11: the interactive HTML data browser (real file; screenshot is separate)
# ----------------------------------------------------------------------

def build_demo_browser_html():
    import htmlbrowser as hb
    from readers.base import SpectrumFile

    class Doc(SpectrumFile):
        def __init__(self, regions, path):
            super().__init__()
            self.path = path
            self.regions = regions
            self.instrument = {"Instrument": "Demo Spectrometer"}
            self._finish()

    docs = [
        Doc([region("C 1s", sample="Film A"),
            region("O 1s", sample="Film A", lo=525.0, hi=540.0, peak=532.0)],
           "demo_a.vms"),
        Doc([region("C 1s", sample="Film B", amp=650.0, peak=285.1),
            region("O 1s", sample="Film B", lo=525.0, hi=540.0, peak=532.2,
                   amp=650.0)],
           "demo_b.vms"),
    ]
    payload = hb.build_payload(
        docs, details={"title": "Demonstration experiment",
                      "summary": "Synthetic data for the user manual."},
        methods_text="Two synthetic samples, C 1s and O 1s.",
        calibration="Not charge-corrected.")
    out = os.path.join(OUT, "demo_browser.html")
    hb.write_html(out, payload)
    print("wrote", out)
    return out


# ----------------------------------------------------------------------

def main():
    fig_stack()
    fig_waterfall()
    fig_heatmap()
    fig_theme_compare()
    fig_cover()
    fig_report_page()
    fig_quant_table()
    fig_casafit()
    fig_iss()
    fig_reels()
    build_demo_browser_html()


if __name__ == "__main__":
    main()
