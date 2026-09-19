# ESCApe Explorer

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
| **Thermo Avantage text dump** | `.avg` (`.avx` text dumps) | Multi-position scans give one region per position; image/map files load as the summed spectrum; header-only dumps (`#empty#`) show as "no data". |
| **Thermo Avantage binary** | `.vgd` (`.avx` binary) | Reverse-engineered OLE2 container (no extra library). Matches the `.avg` of the same data exactly. |
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
| `escape_explorer.py` | the application window and dialogs |
| `readers/` | one reader per format plus the registry that picks one (`readers/__init__.py`) |
| `exporters.py` | CSV, VAMAS and metadata (CSV/PDF) writers |
| `workbook.py`, `workbook_ui.py` | the `.xpscontainer` experiment workbook and its dialogs |
| `report.py` | the experiment report PDF |
| `pptx_export.py` | the PowerPoint export (python-pptx) |
| `annotations.py`, `calibration.py`, `xpslines.py`, `assets/xps_lines.json` | your edits (names, notes, metadata, BE shifts, peak markers), calibration maths and the element-line table |
| `importplan.py` | choosing between `.avg` / `.vgd` copies of the same data |
| `viewdata.py`, `metasummary.py` | plot-view and metadata-tidying helpers |
| `themes.py` | design tokens and colour themes |
| `plotstyle.py`, `plotstyle_ui.py` | the plot style (fonts, lines, ticks, grid, legend, titles, ranges, image size), its presets and its dialog |
| `holder.py` | holder-photo geometry: stage position → photo pixel, calibration nudges, marker picking |
| `fonts.py`, `assets/fonts/` | bundled IBM Plex Sans (SIL Open Font License) |
| `pdf_preview.py` | in-app PDF preview (PyMuPDF) |
| `launch.py` | one-step launcher (creates a venv, installs deps, starts the app) |
| `requirements.txt` | Python packages (matplotlib, Pillow, reportlab, PyMuPDF, python-pptx) |
| `run.bat` / `run.sh` | double-click launchers for Windows / macOS + Linux |
| `tests/` | unit tests (`python -m unittest discover tests`) |

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

1. **Open** (or File menu) → *Spectra files…* to load several files of any
   supported format, or *Folder…* to load every recognised file in a folder.
   Each file is a top-level node in the tree. If a selection or folder holds
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
  apply to old workbooks;
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

**Experiment report** (Workbook menu → *preview…* / *save PDF…*) builds a PDF
you can hand to a customer as a report or appendix: a cover page (logo, title,
details, your summary, the list of data files with hashes), the tidied
metadata of every file, and one page set per saved figure (drawn on white with
its caption). Tick the sections to include in the preview bar. With no saved
figures the current view is used. It needs `reportlab` and `pymupdf`.

**Export PowerPoint…** (Workbook menu) writes a 16:9 `.pptx` from the same
material: a title slide (logo, customer, reference, operator, date), summary,
data files, the metadata as native tables, and one slide per saved figure — a
high-resolution picture with an editable caption and speaker notes describing
the look and the spectra shown. Choose the sections to include in the dialog.
It needs `python-pptx` (installed by the launcher). Slides are built with
plain PowerPoint text and tables, so you can restyle them freely.

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

## Depth profiles

Sputter depth profiles are detected automatically (from the Kratos file's
instrument record, or from a repeated region in a VAMAS file with an etch-time
variable). Ticking a region folder puts every level on one panel. The export
dialog then offers **region-type checkboxes** and **level selection** (*All*,
*First N*, *Every Nth*, or a *range*).

Level 0 is the surface at t = 0, then the cumulative sputter time; etch level
and etch time appear in the metadata CSV/PDF and the Details panel, and are
written into each VAMAS block as comment lines.

## Notes

* **tkinter** is part of Python but needs an OS package on some Linux systems:
  `sudo apt-get install python3-tk` (Debian/Ubuntu),
  `sudo dnf install python3-tkinter` (Fedora). The launcher will tell you if
  it’s missing.
* The interface font is **IBM Plex Sans** (SIL Open Font License, see
  `assets/fonts/OFL.txt`), registered for this app only. If it can't be loaded
  the app quietly falls back to the system font.
* Settings (theme, panel sizes, view options, plot style and your presets) are
  saved in `~/.escape_explorer_config.json`. The holder-photo calibration
  lives in each workbook; the last one used is kept in
  `~/.escape_explorer_calib.json` to start new workbooks with.
* Binding energy is *photon energy − kinetic energy* and is **not
  charge-corrected**, so peaks may be shifted by a few eV on charging samples.
* The `.experiment`, `.vgd` and `.kal` readers are reverse-engineered. The
  `.vgd` and `.kal` readers were checked against the `.avg` / VAMAS exports of
  the same data (identical energies and counts); cross-check anything critical
  against the vendor software.
* If a `.experiment` file was transferred as text rather than binary it can be
  silently corrupted; the app detects this and refuses to export noise.
* Testing on your own data: set `XPS_CORPUS` to a folder of spectra files and
  run `python -m unittest tests.test_corpus` to check that every recognised file
  loads.
