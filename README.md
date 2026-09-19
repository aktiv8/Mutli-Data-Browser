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
| `themes.py` | design tokens and colour themes |
| `fonts.py`, `assets/fonts/` | bundled IBM Plex Sans (SIL Open Font License) |
| `pdf_preview.py` | in-app PDF preview (PyMuPDF) |
| `launch.py` | one-step launcher (creates a venv, installs deps, starts the app) |
| `requirements.txt` | Python packages (matplotlib, Pillow, reportlab, PyMuPDF) |
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
   Each file is a top-level node in the tree.
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
   positions* on a photo needs a one-time **Calibrate…** step (image centre in
   mm, mm per pixel, flip/rotation), saved in your home folder. Select several
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
* Settings (theme, panel sizes, view options) are saved in
  `~/.escape_explorer_config.json`; the camera calibration in
  `~/.escape_explorer_calib.json`.
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
