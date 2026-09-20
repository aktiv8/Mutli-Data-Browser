# eXPoSe SpectraDeck

A browser, viewer and exporter for XPS spectra from many instruments. Open one
or several files at once, tick the spectra you want, and they are plotted
immediately — spectra of the same element are **stacked with a y offset** on a
shared panel. Metadata, camera images and a stage map sit alongside; spectra
can be exported to **CSV** or **VAMAS (ISO 14976)**, and PDF output can be
previewed before it is saved.

## Supported files

| Format | Extension | Notes |
|--------|-----------|-------|
| **VAMAS (ISO 14976)** | `.vms` `.vamas` | From any vendor (Kratos/CasaXPS, PHI, SPECS, Thermo, …). Field-by-field parser; handles `NORM`/`MAP`/`SDPSV` modes, regular and irregular scans, several corresponding variables (intensity + transmission) and vendor comment blocks. |
| **Thermo Avantage text dump** | `.avg` (`.avx` text dumps) | Multi-position scans give one region per position; a SnapMap loads as its summed spectrum with the pixels behind it; camera images become pictures, not spectra; header-only dumps (`#empty#`) show as "no data". |
| **Thermo Avantage binary** | `.vgd` (`.avx` binary) | Reverse-engineered OLE2 container (no extra library). Matches the `.avg` of the same data exactly. |
| **Thermo Avantage experiment** | a folder, or `.VGX` | Opens the whole experiment as one session (samples, analysis points, scans in run order, camera images, SnapMaps): see [Avantage experiments](#avantage-experiments-camera-images-and-snapmaps). |
| **PHI / ULVAC-PHI MultiPak** | `.spe` | Intensities are counts per second, as stored. |
| **Scienta Omicron SES** | `.txt` | Detector/angle columns are summed to one spectrum. |
| **Kratos Vision** | `.kal` | Includes the transmission function. Files that don't record the X-ray source stay on a kinetic-energy axis (a warning says so). |
| **Kratos ESCApe** | `.experiment` | Undocumented binary container; best-effort reverse engineering. |

Files are recognised by **content**, not only by extension, so renamed files
still open. Every loaded format can be exported to CSV or VAMAS, which makes the
app a converter (e.g. Thermo `.avg` → VAMAS). Binding energy is *hν − kinetic
energy* (not charge-corrected) whenever the photon energy is known.

## Files

| File | Purpose |
|------|---------|
| `spectradeck.py` | the application window and dialogs |
| `readers/` | one reader per format plus the registry that picks one (`readers/__init__.py`); `thermo_experiment.py` / `thermo_vgx.py` open an Avantage experiment folder |
| `snapmap.py`, `snapmap_ui.py` | SnapMap pixels (a spectrum at every pixel), the map viewer and its dialog |
| `snapshot.py` | camera-image geometry: stage position ↔ picture pixel |
| `exporters.py` | CSV, VAMAS and metadata (CSV/PDF) writers |
| `workbook.py`, `workbook_ui.py` | the `.xpscontainer` experiment workbook and its dialogs |
| `report.py`, `pdfstyle.py` | the experiment report PDF (contents, bookmarks, section footer) and its typeface and colours |
| `pptx_export.py` | the PowerPoint export (python-pptx): contents, dividers, quantification, figures |
| `reportspec.py`, `reportgen_ui.py` | what a report contains and in what order (one choice for the PDF, the slides and the hand-over), and the Report generator dialog |
| `covers.py`, `assets/covers/` | the cover pictures of the report and the slides |
| `quant.py`, `resultspages.py` | atomic percent from CasaXPS fits, and its tables and depth-profile charts for the report and the slides |
| `timing.py` | how long an analysis took (counting time, span, overhead) |
| `imagepages.py` | camera-picture sheets and SnapMap pages, drawn once for the PDF report and the slides |
| `mosaic.py` | stitching overlapping camera pictures into one mosaic (stage positions, matched where they overlap, blended) |
| `methods.py` | the methods text, written from what the files record |
| `handover.py` | the hand-over ZIP (report, spectra, figures, metadata, README, checksums) |
| `htmlbrowser.py`, `viewer/` | the offline HTML data browser (payload builder and the page: template, CSS, JavaScript) |
| `annotations.py`, `calibration.py`, `xpslines.py`, `assets/xps_lines.json` | your edits (names, notes, metadata, BE shifts, peak markers), calibration maths and the element-line table |
| `importplan.py` | choosing between `.avg` / `.vgd` copies of the same data |
| `viewdata.py`, `metasummary.py` | plot-view and metadata-tidying helpers |
| `themes.py` | design tokens and colour themes |
| `plotstyle.py`, `plotstyle_ui.py` | the plot style (fonts, lines, ticks, grid, legend, titles, ranges, image size), its presets and its dialog |
| `lineshapes.py`, `casafit.py` | CasaXPS fits from VAMAS: line shapes, backgrounds, parsing and reconstruction |
| `sputter.py`, `sputter_ui.py` | sputter settings, fluence and depth axes |
| `vamasmeta.py` | metadata carried in VAMAS comments |
| `elements.py`, `reels.py`, `iss_ui.py` | ISS element identification, REELS band gap and their dialog |
| `holder.py` | holder-photo geometry: stage position → photo pixel, calibration nudges, marker picking |
| `fonts.py`, `assets/fonts/` | bundled IBM Plex Sans (SIL Open Font License) |
| `splash.py`, `about_ui.py`, `appinfo.py`, `assets/splash.png` | the start-up splash, the About box, the app name / version / link, and the picture you supply |
| `ribbon.py`, `icons.py` | the tabbed toolbar and the icons drawn in code for it |
| `pdf_preview.py` | in-app PDF preview (PyMuPDF) |
| `launch.py` | one-step launcher (creates a venv, installs deps, starts the app) |
| `requirements.txt` | Python packages (matplotlib, Pillow, reportlab, PyMuPDF, python-pptx) |
| `run.bat` / `run.sh` | double-click launchers for Windows / macOS + Linux |
| `tests/` | unit tests (`python -m unittest discover tests`; the browser's JavaScript is also tested when Node.js is installed) |

Keep all of these in the same folder.

## Quick start

**Windows**

1. Install Python 3.8+ from https://www.python.org/downloads/ and tick
   *“Add python.exe to PATH”* during setup.
2. Double-click **`run.bat`**.

**macOS / Linux**

```bash
chmod +x run.sh        # first time only
./run.sh
```

On the first launch it builds an isolated environment in `./.venv` and installs
the packages in `requirements.txt` (an internet connection is needed once).
Later launches start immediately. Nothing is installed into your system Python.
The launcher re-installs automatically if `requirements.txt` changes.

## Manual launch (optional)

```bash
python launch.py            # Windows
python3 launch.py           # macOS / Linux
```

| Flag | Effect |
|------|--------|
| `--setup-only` | build the environment but don’t start the app |
| `--reinstall`  | rebuild the environment from scratch |
| `--check`      | report environment status and exit |

## Using the app

One workspace window: the **file tree** on the left, a large **plot** in the
middle, and an **info column** on the right (Details above an
Images / Stage map notebook). Drag any splitter; sizes are remembered.

Under the menu bar is a **tabbed toolbar**: *Home* (open, workbook, save,
export, image), *Analyse* (calibrate, identify peaks, ISS / REELS, sputter,
SnapMap, rename, notes), *Report* (details, figures, report PDF, slides,
hand-over ZIP, HTML browser, PDF previews) and *View* (theme, plot style, the
Files / Details panes, focus, expand / collapse, untick). Every button is a
shortcut for a menu command, so the menu bar still holds everything; buttons
that need spectra are dimmed until a file is open. Double-click a tab (or use
the arrow at the right) to fold the toolbar down to the tab row and give the
plot the height back; the tab and fold state are remembered.

**Splash and About.** A splash screen with your picture shows while the
program starts; click it or press Esc to close it. Put the picture at
`assets/splash.png` (PNG, JPG or GIF; any size, it is scaled to at most 60 %
of the screen; the same file is shrunk for the window icon). An optional
`assets/about.png` replaces it in the **Help → About** box, which also shows the
version, a link to the project page, the libraries in use and a *Copy version
info* button for bug reports. Without a picture both show just the name.
Start with `--no-splash`, or untick *Help → Show splash screen at start*, to
skip it.

1. **Open** (or File menu) → *Spectra files…* to load several files of any
   supported format, or *Folder…* to load every recognised file in a folder.
   Each file is a top-level node in the tree. (A folder from a Thermo Avantage
   experiment, or its `.VGX`, opens as **one experiment**: see below.) If a selection or folder holds
   the same dataset as both `.avg` and `.vgd`, you are asked which to import
   (`.avg` is pre-selected; *Remember my choice* stops the question, and
   File → *Ask about .avg / .vgd duplicates again* brings it back).
2. Every node that holds spectra has a **tick box** (click it, or press
   **Space**). Ticking a sample, region folder or whole file ticks everything
   under it; a partly-ticked parent shows a bar. **Filter** narrows the tree
   (ticks are kept). Right-click a row to tick/untick a subtree, export from
   there down, or remove a file.
3. **Ticked spectra are plotted at once, and the tree is the legend.** Spectra
   sharing an element name (every *C 1s*, across samples and across files) are
   drawn on **one panel, stacked with a y offset**; other elements get their own
   panels. A ticked box in the tree is a **swatch in the trace's colour**: one
   colour per file when several files are loaded (otherwise per sample), and a
   fading ramp of one hue for long stacks such as depth profiles. Stacked panels
   have no y-ticks: a scale bar gives the intensity scale, and each trace is
   labelled at its right-hand end. The selected spectrum is drawn heavier.
   A sample holding a single spectrum appears as one row. View controls:
   * **Group by** — *Element name*, *Energy range* (spectra whose x-ranges
     overlap by at least half share a panel), or *Element, per sample* /
     *Element, per file* (one panel per depth or time series).
   * **Normalise** — *None*, *Max = 1*, *Area = 1*, or *At cursor* (click a panel
     to set an energy; every spectrum in it is scaled to match there).
   * **Offset** — the gap between stacked traces (0 overlays them);
     **Reverse stack** flips the order.
   * **View** — *Stack* (the default), *Waterfall 3D* (energy, trace and
     intensity in a rotatable 3-D plot) or *Heatmap* (intensity as colour
     against energy and trace, with a colour bar). Both also honour
     **Normalise**, the panel paging and the trace window, and print to PDF.
   * **Z axis** (waterfall / heatmap) — what the trace axis shows: *Auto*
     (etch time if the file recorded it, else etch level, else acquisition
     time, else trace order), or pick one. Traces are ordered by it, surface /
     earliest first; if it is unavailable for a group the status bar says what
     was used instead.
   * **Colour** — *Theme default* keeps the current theme's colours. Pick a
     scale (Viridis, Plasma, Magma, Inferno, Cividis, Turbo, Coolwarm, Greys,
     Blues, YlOrRd) to colour the heatmap's intensity and to spread the traces
     of a stack or waterfall along the scale (by their place in the series, so
     a depth profile runs from surface to bulk); **Reverse** flips it. The tree
     swatches follow, so the tree stays the legend. Ends of a scale that would
     vanish into the plot background are trimmed. With a scale chosen, traces
     are no longer coloured per file / sample.
   * **Axes** — colour of the axis lines, ticks and labels: *Theme default*,
     *Black*, *White* or *Custom…*. A choice that would be hard to see on the
     current background (black on Dark, white on Light) is ignored and the
     status bar says so. PDFs ignore *White*.
   * **Energy** — *Binding* or *Kinetic* (KE = hν − BE; needs the photon
     energy, otherwise the spectrum stays on binding energy and the status bar
     says so). **KE top axis** mirrors the binding-energy axis along the top as
     kinetic energy.
4. **How many, and scrolling.**
   * **Panels per page** — Auto, 1, 2, 4, 6, 9, 12 or 16. Scroll the panels with
     the mouse wheel, the scrollbar beside the plot, PageUp/PageDown, Home/End or
     the Prev/Next buttons.
   * **Traces per panel** — All, or a number (3–100, or type your own). For a long
     stack (say a 200-level depth profile) each panel then shows a window of
     that many traces; slide it with **Shift + wheel** or the *Traces* slider
     under the plot.
5. **Selecting** a row (rather than ticking it) fills the **Details** panel
   (sample, acquisition and region, copyable) and the **Images** / **Stage map**
   tabs, which only appear when the loaded files have images or stage positions. *Overlay
   positions* on a photo needs a **Calibrate…** step. The calibration panel
   works live: tick *Flip X / Flip Y*, nudge the markers with the arrows,
   rotate or spread them, or type exact values (image centre in mm, mm per
   pixel, rotation) and watch the markers move onto the samples. The
   calibration is saved **in the workbook** (the last one used also seeds new
   workbooks). Markers carry a halo so their names stay readable over any
   photo; **click a marker** (on the photo or on the Stage map) to select that
   sample in the tree. Select several
   rows (or a whole sample or file) and Details is tidied: what is the same for
   all of them (photon energy, lens mode, …) is stated once, and settings that
   differ are grouped by value — e.g. *Pass energy: 40 · Mo 3d, S 2p, C 1s /
   160 · Survey*. The metadata PDF does the same per sample.
6. **Colour themes** — *Light* (the default), *Dark* (the plot sits recessed
   below the chrome, like an instrument screen), *Midnight*, *Solarized Light*,
   *High contrast*, and *System* (the native OS look). Change them from the
   **Theme** box or View → Colour theme; the choice is remembered. Every theme
   has its own colour-blind-safe data palette and meets WCAG AA text contrast
   (checked by the tests). The native Windows menu bar and message boxes can't
   be recoloured. PDFs always print on white.
7. **Layout** — **Files** and **Details** in the toolbar show or hide the side
   panels, and **Focus** (F11) hides both so the plot fills the window. Hover a
   control for a short explanation.
8. **PDF** — *Preview spectra* and *Preview metadata* show the PDF inside the
   app (page navigation, zoom, **Save as…**, *Open in viewer*). The spectra
   preview lets you change panels per page, portrait/landscape and whether to
   use only the traces currently in view; **Save as…** writes exactly what you
   see. Without PyMuPDF the PDF opens in your default viewer instead.
9. **Export** — *Ticked spectra to CSV / VAMAS* writes exactly what is ticked.
   *Regions and levels…* opens the export dialog (pre-set to your ticks) for
   picking regions or depth-profile levels. VAMAS output is CasaXPS-compatible:
   a kinetic-energy abscissa with **Intensity** and the spectrometer
   **Transmission** function as corresponding variables (toggle it off in the
   dialog). *Metadata to CSV / PDF* saves per-sample acquisition metadata; with
   several files open, select a row of the file you want first.

## Editing, calibration and element labels (Tools menu)

Nothing here changes the instrument files: your edits are stored beside the
data (in the workbook) and applied when you plot, export and report.

* **Rename** (F2, or right-click a sample / region): give samples and regions
  display names; the original name is always kept and shown in Details.
  **Notes…** adds free text to a sample or region.
* **Edit metadata**: double-click a value in *Details* (or right-click → Edit
  value / Add field / Reset). Edited values carry a ✎ mark and flow into the
  PDF, PowerPoint and CSV.
* **Calibrate binding energy…**: pick a reference spectrum, find the peak
  (or click it on the plot), choose the reference (C 1s 284.8, Au 4f7/2
  83.95, Ag, Cu, Fermi edge or your own value) and apply the shift to a
  region, a sample or a whole file. Plots, CSV and VAMAS exports use the
  shifted energies (VAMAS carries the shift through the source energy, so
  kinetic energies are unchanged), and the report gets a calibration
  statement.
* **Identify peaks…**: click a survey peak to list candidate element lines,
  add the one you want as a marker, or **Auto-label** every peak. Markers
  follow BE shifts and the KE axis. Line positions are approximate (typical
  values, chemical shifts of a few eV are normal); edit
  `assets/xps_lines.json` to change or extend them.
* **Cursor read-out** (status bar): BE, KE and intensity under the pointer.
* **Comforts**: File → *Open recent*, *Save plot image…* (PNG / SVG / PDF, any
  size and dpi), drag files or folders onto the window (needs the optional
  `tkinterdnd2`, which the launcher installs when it can), a progress box with
  **Cancel** when loading many files, and ▶ / ← → to play through the traces
  (set *Traces* to 1 to step through depth levels one at a time).

## Experiment workbooks (`.xpscontainer`)

The **Workbook** menu saves everything about an experiment in one file that
you can reopen at any time (or double-click / pass on the command line):

* the **original data files**, byte-for-byte (so the workbook is
  self-contained and the originals can be moved or deleted), with SHA-256
  hashes as provenance; files are re-read on opening, so reader improvements
  apply to old workbooks. An Avantage experiment is kept as its whole folder
  layout (it can be large: the camera images and SnapMaps are the bulk, and
  you are warned above 500 MB); workbooks without one are still readable by
  older copies of the app;
* the **look**: what is ticked, view, grouping, normalisation, energy scale,
  colour scale, axis colour, panels/traces and "At cursor" energies;
* **Details and notes** — title, customer, reference, operator, date, a free
  text summary and a letterhead logo;
* **Figures** — any number of named looks with captions (*Add current view…*,
  then recall, update, rename, reorder or delete them);
* a snapshot of the acquisition metadata and a preview image.

Save with **Ctrl+S**; the title bar shows `*` for unsaved changes and closing
asks whether to save. The file is a ZIP archive with JSON and the original
files inside, so it can be inspected with any zip tool and never runs code.

**Metadata layout.** The metadata PDF and the report's metadata section use
portrait A4 pages and lose nothing: settings that are the same for every
region (photon energy, lens mode, …) are stated once at the top, settings that
are constant within a sample (stage position, date, …) sit on that sample's
line, and the rest is a compact scan table (pass energy, step, dwell, scan
range, points, acquisition time). Samples flow one after another instead of
one per page. A depth profile is one row per region — e.g. *levels 0–60 (61),
etch 0–1800 s, 30 s steps* — but only where that reproduces every level
exactly; otherwise (irregular etch times, per-level timestamps) a compact
"per-level details" table lists every level. The metadata CSV still has one
row per region and level.

**Report generator** (Workbook menu → *Report generator…*, or Report ▸ Generator
on the ribbon) is where you say what a report contains. Tick the sections and
put them in the order you want; the same choice is used for the **PDF report**
(*Save PDF…*), the **PowerPoint deck** (*Export PowerPoint…*), the previews and
the report inside the hand-over package, is remembered, and is saved with the
workbook. Sections, in the default results-first order:

* **Cover page** — logo, title, customer, reference, operator and date, under a
  **cover picture** you choose on the *Cover* tab: five designs drawn from one
  accent colour (spectrum ribbon, band, minimal, your own data, peak map), a
  picture of your own (or one you drop in `assets/covers/`), or none, in one of
  six accent colours or your own. Presets never change the cover.
* **Contents** — the sections and their pages (slides), with the real numbers;
  the PDF also gets bookmarks. Slides get divider slides before long sections
  (*Options* tab), and every slide is numbered "n of N".
* **Summary**, then **Quantification** — atomic percent from CasaXPS areas and
  sensitivity factors: a table per sample (with chemical states) or, for a depth
  profile, a chart and a table by level. A region fitted in more than one
  spectrum is counted once (the dedicated scan, not the survey), an element
  counted from two lines is flagged, and no transmission correction is applied;
  the pages say so. Each sample can be ticked separately.
* **Figures** — one page set per saved figure (drawn on white with its caption);
  with none saved the current view is used.
* **Camera pictures and SnapMaps** — see below; each picture and map site can be
  ticked separately, and overlapping pictures can also be **stitched into a
  mosaic** (*Options* tab).
* **Methods**, **Energy calibration**, **Acquisition metadata** (the tidied
  metadata of every file) and **Data files** (with checksums; the *Options* tab
  can leave them out) — the audit trail, last.

Built-in presets (*Everything*, *Customer report*, *Quick look*, *Audit trail*)
and your own saved ones fill the ticks in one go. Sections with many items
(figures, pictures, files, samples) open with a double-click, and **All / None**
ticks the items of the selected section. The PDF needs `reportlab` and `pymupdf`,
the deck `python-pptx` (installed by the launcher); slides use plain PowerPoint
text and tables, so you can restyle them freely.

A figure slide is a high-resolution picture with an editable caption and speaker notes describing the look and the spectra shown.

**Camera pictures and SnapMaps in the report and slides.** When the loaded
files have them (an Avantage experiment), the report gets pages after the
metadata and the deck gets slides before the figures:

* **Mosaics**: pictures that overlap (say, several points along a row) are
  also joined into one large picture. They are laid out by their stage
  positions, then matched to each other where the overlap has enough detail to
  match (a few pixels of correction), and blended without a seam; the analysis
  points and map outlines are drawn on it. Where a picture was taken twice
  (before and after a pass) the later one is used. A note on the page says how
  many overlaps were matched.
* **Camera pictures**: six to a report page (three to a slide), each with the
  analysis points that fall in it (its own highlighted), the outline of any
  SnapMap taken there and a scale bar. Both pictures of a point (before and
  after a pass) are shown, so beam damage is visible.
* **One page (slide) per SnapMap site**: the camera picture taken there beside a
  grid of element maps, each the counts in the window round that element's
  strongest peak (the window is in the title), with its own colour bar scaled
  from the 1st to the 99th percentile. The colour scale is the one chosen in the
  SnapMap viewer. The speaker notes list the windows.

Names, notes and energy shifts you set are applied. Camera slides are JPEG (the
deck stays a few MB); the report keeps the pictures at 640 px wide. The
hand-over ZIP's report includes these pages too. They need matplotlib and
Pillow; pictures are not repeated per figure, and each picture or map site can be ticked separately in the Report generator.

**Methods text.** *Workbook → Details…* has a **Methods** box holding a
paragraph written from what your files actually record: instrument and
source, pass energies (surveys and high-resolution scans kept apart), step
sizes and dwell times, lens mode, charge neutraliser, sputtering, depth
profiles, the dates, and your binding-energy calibration statement. A setting
a file does not record is left out, never guessed. Edit the text to use your
own wording (*Regenerate* brings the automatic text back; text you leave
untouched keeps following the data). It appears on the report cover, on a
*Methods* slide, in `methods.txt` and in the data browser.

**Hand-over package** (Workbook menu → *Hand-over package (ZIP)…*) puts an
experiment in one ZIP for a customer or collaborator: the report PDF, the
methods, **one VAMAS and one CSV file per sample** (display names and energy
shifts applied), the metadata as CSV, every saved figure as a PNG, optionally
the interactive data browser and the workbook itself, a `README.txt` listing
it all, and `SHA256SUMS.txt` (`sha256sum -c SHA256SUMS.txt` checks the
contents). Tick what to include in the dialog.

**Interactive data browser** (Workbook menu → *Interactive data browser
(HTML)…*) writes **one self-contained `.html` file** that anyone can open in a
modern browser, offline, with nothing to install. It holds every spectrum and
lets the reader filter the sample list, tick spectra to plot them (stacked or
overlaid, normalised, binding or kinetic energy, drag to zoom, hover for
values), step through depth levels one at a time, read the acquisition
metadata, notes and methods, look at your saved figures with their captions,
see the holder photo with the analysis positions (click a marker to select
that sample) and download the ticked spectra as CSV. It has light, dark and
print styles. The data are compressed inside the file; it uses no libraries and
makes no network requests.

For an Avantage experiment it also holds the **camera images** and **SnapMaps**:

* **Camera images** tab: each picture (shrunk to 800 px, JPEG) with the analysis
  points that fall in it, the outline of any SnapMap taken there and a scale bar.
  Click a marker to select that sample; selecting a sample in the list brings up
  its picture.
* **SnapMaps** tab (or the small *map* button beside a SnapMap in the list): the
  same viewer as in the app. Drag across the spectrum to choose the energy window
  and the map redraws; drag a box (or click a pixel) for that area's spectrum
  against the whole map's; switch element (the area is kept); choose the colour
  scale; remove a sloping background; lay the map over the camera image; download
  the map values or the spectra as CSV. The pixels are stored as counts in steps
  of 1/8 (well below the counting noise), compressed. A whole point's eight maps
  add roughly 7 MB; if the maps would pass 40 MB the energy channels are summed
  in twos, then fours, and as a last resort the last maps are left out, and the
  dialog that reports the saved file says so.

## Plot style

**View → Plot style…** (or the *Style…* button under the plot controls) opens
one dialog for how plots *look*: font and sizes, line width / style, markers,
fill under traces, frame (open or box), tick direction / length / minor ticks,
grid, panel titles and axis labels (or your own text), y units, energy and
intensity ranges, trace labels (at the end of each trace, a legend box or
none) and the size and resolution of saved images. Changes apply at once and
reach the screen, **PDFs**, **slides** and **Save plot image…** (PNG / SVG /
PDF). An energy range applies only to panels it reaches, so one C 1s window
can sit on a page that also shows O 1s.

Pick a **preset** (*Journal (compact)*, *Presentation (large)*, *Data points*,
*Filled peaks*, …) or save your own with *Save as preset…*. The current style is
remembered between sessions, saved in the workbook and stored with **each saved
figure**, so a figure keeps its look in the report even after you change the
live plot.

## Stacked / waterfall / heatmap plots

There is no separate plotting window: tick several spectra — e.g. depth-profile
levels, or the same region across samples and files — and they stack on one
panel. Combine with *Normalise → At cursor* to compare peak-shape changes.
Switch **View** to *Waterfall 3D* or *Heatmap* to see a whole depth or time
series at once; use *Group by → Element, per sample* to keep each sample's
series on its own panel.

## Sputter settings, depth and fluence

**Tools → Sputter settings…** holds the ion gun settings of each depth profile:
ion and charge state, energy, current (pA–mA), raster size and etch rate. They
are prefilled from the file where it states them (a Kratos depth profile
records the beam, e.g. *5 keV Ar+*; PHI and Avantage files are read where they
carry ion-gun properties) and you fill in the rest — **nothing is guessed**,
and a bare number whose unit is unknown is left for you. With them the *Z axis*
of a waterfall or heat map can be **Depth (nm)** (etch rate × etch time) or
**Fluence** (ions/cm² = current × time ÷ (charge × e × raster area)). Asking for
one that cannot be worked out says what to enter, e.g. *"enter the etch rate in
Tools ▸ Sputter settings"*. The settings are kept in the workbook per sample,
appear in the metadata (per level: depth and fluence) and in the methods text.

## VAMAS that keeps its metadata

VAMAS has no fields for most acquisition details, so an exported `.vms` now
carries them in its comments: a delimited block
(`=== eXPoSe SpectraDeck metadata ===` … `=== end of … ===`) in the file header for the
instrument-wide entries and in each block comment for that spectrum — lens
mode, aperture, neutraliser, ion gun, dates, stage position, depth level and
etch time, sputter settings, your notes and energy shift. Other software just
shows it as text. **Reading such a file back restores it** (instrument, dates,
positions, depth profile, sputter settings), while values VAMAS stores exactly
(photon energy, pass energy, dwell, step) are never taken from the text. Files
without the block read exactly as before. The abscissa start, step and photon
energy are now written to 10 significant digits (they were 6), so a re-read
spectrum matches the original to the last digit.

## CasaXPS fits

A VAMAS file saved from CasaXPS after peak fitting carries the fit in its block
comments (regions, backgrounds, components, INDEX chemical-state groups, the
`Calib` binding-energy offset). Opening such a file shows the fit under any
panel that holds **one spectrum**: tick *Components*, *Envelope* and/or
*Background* in the **Fit** row under the plot controls. A depth profile keeps
one fit per level (each block its own), so stepping through levels shows each
level's fit where it has one. Components that share an INDEX are one chemical
state and one colour.

* **Charge correction carried over.** CasaXPS records its binding-energy
  correction in each block as `Calib M = 281.7289 A = 282 BE ADD` (measured
  peak, assigned value): the spectra are shown shifted by A − M, as in CasaXPS,
  and the shift appears in the Details ("BE calibration (CasaXPS)") and in the
  report's calibration statement. A block with no `Calib` line takes the
  correction of the other blocks of its **sample** when they all agree (a wide
  scan next to calibrated core levels); depth-profile levels calibrated
  individually keep their own. Your own **Calibrate…** replaces it.
* **Correct frame and scale.** CasaXPS stores positions as kinetic energies and
  intensities in counts per second. Where a `Calib` line carries the
  `Regions Comps` flags the positions moved with the spectrum (raw frame);
  without them they are in the calibrated frame. The curves are reconstructed
  in the spectrum's own axis and counts, and follow the app's energy
  calibration. When a block holds several overlapping regions with one name,
  the widest is drawn.
* **Exact and reconstructed shapes.** `GL` and `SGL` shapes and Shirley / linear
  backgrounds are computed exactly; the two-parameter universal Tougaard
  background (`U 2 Tougaard`) is reproduced from its stored B and C to 2–5 %
  of the peak height on the MXene HAXPES/XPS regions we checked. Other
  Tougaard variants are not reproduced: the components are then drawn without an
  envelope and the status bar says so. CasaXPS does not publish its `LA` and `LF`
  kernels, so those are **reconstructions** from the stored parameters (the
  status bar says so): checked against real CasaXPS fits (titanium, copper,
  vanadium, a titanium depth profile) they reproduce the data to 3–7 % rms of
  the peak height (the fit's own scatter included). The areas, positions and
  widths shown are CasaXPS's own numbers.
* **Export.** VAMAS export writes the fit back unchanged (CasaXPS reopens its
  own fit); CSV export adds the background, each component and the envelope as
  columns. The metadata lists the number of components and the calibration.
* The fit is read, not edited: fit in CasaXPS, review it here.

## ISS and REELS

**Tools → ISS / REELS…** works on the spectrum you have ticked (tick only that
one), whatever its energy axis.

* **ISS peaks.** Give the ion (H⁺, He⁺, Ne⁺, Ar⁺), the beam energy and the
  scattering angle (the beam energy is taken from the file where it states
  it; the angle is your instrument's). Click a peak on the plot and the
  elements that scatter the ion to that energy are listed, nearest first, from
  the single-collision model E₁/E₀ = [(cos θ + √(A² − sin²θ)) / (1 + A)]²
  with A = M_target / M_ion (a projectile cannot backscatter from a lighter
  atom). *Add marker* labels the peak; or type the elements you expect
  (*Cu Au Ni*) and *Mark* puts each at its predicted energy. Masses are those
  of the most abundant isotope. ISS markers are at **kinetic energies**, so an
  energy calibration never moves them, and they show on either energy axis
  and in the HTML data browser.
* **REELS band gap.** Find the elastic peak (*Find the maximum*, type it, or
  click it), then click two points on the **rising edge** of the loss
  spectrum. The straight line through them meets the baseline (the flat level
  between the elastic peak and the onset) at the band gap, which is drawn on
  the plot (points, tangent, baseline, *Eg = …*), stored in the workbook and
  written into the spectrum's metadata. Points that do not give a positive
  gap are explained rather than stored as a result.

## Avantage experiments, camera images and SnapMaps

Avantage writes one `.VGD` per scan into `<experiment>/<source configuration>/
<sample>/…` next to `<experiment>.VGX`. **Open → Folder…** on that folder (or
on the `.VGX`, or on a single sample folder inside it) loads everything as one
experiment, with a progress box you can cancel:

* the tree runs **experiment → sample → analysis point → scan**, in the order
  the `.VGX` says they were run; scans of the same core level line up across
  points, and two scans of one line in a sample (say at 20 and 50 eV pass
  energy) are told apart by the scan name;
* the `.VGX` supplies the experiment, project and platter names and the run
  order; the sample names come from the folder names. When a scan exists as
  both `.VGD` and `.avg`, the binary one is used;
* files that cannot be read are listed once at the end and the rest still
  loads; an acquisition that was aborted before any data existed and the
  auto-height (Z) tables are set aside, not treated as errors;
* a scan of two lines (*Si2p Al2p Scan*) is named for both (*Si 2p Al 2p*), and
  *Cu2p3* reads as *Cu 2p3/2*.

**Camera images.** The sample-view pictures Avantage takes at each point
(before and after each pass) are attached to their points; select a point and
its picture appears in the **Images** tab. Each picture carries its own stage
calibration, so no holder photo or manual calibration is needed: the analysis
points that fall inside it are drawn, with the outline of any SnapMap taken
there and a scale bar. Click a point to select it in the tree. (On the
K-Alpha+ the image's *x* runs against the stage X and *y* with the stage Y; this
was measured by registering neighbouring pictures against each other.)

**SnapMaps** (a spectrum at every pixel) are one region each in the tree,
marked *(SnapMap)*, showing the summed spectrum like any scan. **Double-click**
one (or right-click → *Open SnapMap…*, or Tools → *SnapMap viewer…*) to see
where the signal comes from:

* **Drag across the spectrum** to choose the energy window; the map shows the
  counts in it (*Remove background* takes a straight line off first, so a
  sloping baseline does not show as contrast). The window starts on the
  strongest peak.
* **Drag a box on the map** (or click one pixel) to see that area's spectrum
  next to the whole map's; *Whole map* clears it. Switching element keeps the
  area.
* **On camera image** lays the map over the picture taken at the same spot
  (the slider sets how much of the picture shows through).
* **Save…** writes the picture (PNG), the map values (CSV) or the spectra (CSV).

## Depth profiles

Sputter depth profiles are detected automatically (from the Kratos file's
instrument record, or from a repeated region in a VAMAS file with an etch-time
variable). Ticking a region folder puts every level on one panel. The export
dialog then offers **region-type checkboxes** and **level selection** (*All*,
*First N*, *Every Nth*, or a *range*).

Level 0 is the surface at t = 0, then the cumulative sputter time; etch level
and etch time appear in the metadata CSV/PDF and the Details panel, and are
written into each VAMAS block as comment lines.

## Not there yet

Ideas that are planned or open, so you know what to expect (the developer notes
in `CLAUDE.md` have the detail):

* a **quantification view in the app itself** (the report, the slides and the
  data browser have one), and choosing **which regions count** in the report's
  quantification (today only whole samples can be left out);
* a **viewer for the mosaic** in the app or the data browser (today it is in the
  report and the slides);
* section **divider pages** in the PDF (the slides have them) and clickable
  entries in the slides' contents;
* opening a saved workbook **without re-reading** the original files, and
  importing / exporting the XPSView `.xpsv` package;
* a command-line **batch mode** (left out on purpose for now).

## Notes

* **tkinter** is part of Python but needs an OS package on some Linux systems:
  `sudo apt-get install python3-tk` (Debian/Ubuntu),
  `sudo dnf install python3-tkinter` (Fedora). The launcher will tell you if
  it’s missing.
* The interface font is **IBM Plex Sans** (SIL Open Font License, see
  `assets/fonts/OFL.txt`), registered for this app only. If it can't be loaded
  the app quietly falls back to the system font.
* Settings (theme, panel sizes, view options, plot style and your presets) are
  saved in `~/.spectradeck_config.json`. The holder-photo calibration
  lives in each workbook; the last one used is kept in
  `~/.spectradeck_calib.json` to start new workbooks with. (Files saved under the
  former name, `~/.escape_explorer_*.json`, are picked up automatically.)
* Binding energy is *photon energy − kinetic energy* and is **not
  charge-corrected**, so peaks may be shifted by a few eV on charging samples.
* The `.experiment`, `.vgd` and `.kal` readers are reverse-engineered. The
  `.vgd` and `.kal` readers were checked against the `.avg` / VAMAS exports of
  the same data (identical energies and counts); cross-check anything critical
  against the vendor software. The `.VGX` reader takes only names and run
  order from it; camera images were compared pixel for pixel with Avantage's
  own PNG export.
* The acquisition times stored inside Avantage files appear to be UTC (they
  differ from the local time in the file name by the UTC offset), and are shown
  as stored; the camera-image labels use the local time from the file name.
* If a `.experiment` file was transferred as text rather than binary it can be
  silently corrupted; the app detects this and refuses to export noise.
* Testing on your own data: set `XPS_CORPUS` to a folder of spectra files and
  run `python -m unittest tests.test_corpus` to check that every recognised file
  loads.
