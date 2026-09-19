# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

ESCApe Explorer: a single-window Tkinter app that browses, plots and exports XPS spectra from many instruments — Kratos ESCApe (`.experiment`) and Vision (`.kal`), VAMAS (any vendor), Thermo Avantage (`.avg`/`.vgd`/`.avx`), PHI MultiPak (`.spe`), Scienta SES (`.txt`) — to CSV or VAMAS. See `README.md` for the user-facing tour.

## Commands

```bash
python launch.py                # create ./.venv, install deps, start the app (python3 on macOS/Linux)
python launch.py --setup-only   # build the venv without starting the app
python launch.py --reinstall    # rebuild the venv from scratch
python launch.py --check        # report venv / tkinter / app-file status
python escape_explorer.py       # run directly with the current interpreter
python -m unittest discover tests            # unit tests (synthetic files, no instrument data needed; includes palette contrast/separation and colour-rule tests)
XPS_CORPUS=<folder> python -m unittest tests.test_corpus   # every recognised file in a folder must load
```

There is no linter or build step. Dependencies (`matplotlib`, `pillow`, `reportlab`, `pymupdf`) are in `requirements.txt`; `launch.py` keeps a `REQUIRED` fallback list that must stay in sync and re-installs when the requirements file's SHA-1 changes. `tkinter` comes from the base Python, not the venv. The app must still start when matplotlib / Pillow / PyMuPDF are missing (`HAVE_MPL`, `HAVE_PIL`, `pdf_preview.HAVE_PDF`).

## Architecture

`escape_explorer.py` is the entry point (window, dialogs, `main()`); everything else is a module beside it:

- **`readers/`** — one reader per format behind `readers.load_file(path)`. `readers/__init__.py` holds the `READERS` registry and picks a reader by **content sniffing** first (extension is only a hint), so renamed files still open; add a format by writing a `SpectrumFile` subclass with a `sniff(head, ext)` function and registering it there (this also feeds the Open dialog filters).
  - `readers/base.py`: `Region` / `TreeNode` / `ImageBlob` dataclasses and the `SpectrumFile` base class. A reader only fills `regions` (+ `instrument`, optional `depth_profile`, `_sample_pos`, `images`) and calls `_finish()`; the tree, per-region metadata and positions then come from the base class. Shared helpers: `canon_region_name` ("C1s" → "C 1s", surveys → "Survey", so the same core level groups across formats), `guess_region_name` (a "core level" on a >250 eV axis is a survey), `kv_from_lines`, `read_bytes` (always use it — never leave file handles open).
  - `Region.energy` is **binding energy** for XPS whenever the photon energy is known (BE = hν − KE, as CasaXPS does); otherwise the native axis is kept and `energy_label` says so (only "Binding…" axes are inverted when plotted).
  - `vamas.py`: field-by-field ISO 14976 parser. Header layout varies by experiment mode (e.g. `SDPSV` has no "number of spectral regions"), so `load()` tries the expected layout then alternatives; numbers between the source label and analyser mode are read by type because the count varies by mode; `IRREGULAR` scans have no start/step (the first corresponding variable is the abscissa).
  - `thermo_avg.py` defines `DataSpace` and `ThermoDataSpaceFile._from_dataspace`, shared with `thermo_vgd.py` (pure-Python OLE2 in `ole2.py`, no `olefile`). `.vgd` property ids → `DS_*` names are the `PID_NAMES` table; the axis stream is decoded by anchoring on the expected item counts.
  - `phi_spe.py` (16-byte preamble, all 96-byte block headers, then float64 blocks; counts/s), `scienta_txt.py`, `kratos_kal.py`, `kratos_experiment.py` (the original reverse-engineered `EscapeParser`).
- **`viewdata.py`** — Tk-free helpers for the alternative views: `energy_axis` (BE ↔ KE per region; kinetic falls back to native when hν is unknown), `resolve_z` / `z_sorted` (z axis of waterfall/heatmap: etch time → level → acquisition time → trace order; all-zero etch times count as absent; acquisition date comes from `SpectrumFile.date_for_region`, because the Kratos `.experiment` reader leaves `Region.date` empty), `build_matrix` (resample onto one grid, NaN outside a trace's range).
- **`metasummary.py`** — Tk-free tidying of `region_metadata` dicts: `summarise` splits fields into common-to-all vs varying (grouped by value → region labels, numbers ascending), `compact_labels`, `date_range`, `split_columns`. Used by the Details panel for multi-selections (`Workspace._metadata_many`) and by the metadata PDF (`exporters._sample_block`); the metadata CSV stays flat.
- **`exporters.py`** — `export_csv`, `export_vamas` (kinetic-energy abscissa with Intensity + interpolated Transmission, CasaXPS-compatible), `export_metadata_csv`, `export_metadata_pdf` (reportlab, matplotlib fallback). They use `Region` only, so any loaded format can be exported.
- **`themes.py`** — the design tokens: six palettes (`Light` default, `Dark`, `Midnight`, `Solarized Light`, `High contrast`, `System` = native ttk theme), each with chrome colours, plot colours and a colour-blind-safe data palette (`cycle`); WCAG `contrast`/`luminance`, `ramp` (one-hue fade for long stacks), `mpl_rc` (open-frame plots, type scale), `SwatchCache` (tree tick boxes) and `scale_colourmap` / `scale_colours` (user-selectable colour scales; traces are trimmed/nudged to keep contrast ≥ 2 on the plot background) and `with_axis_colour` (frame/tick/label colour override, falls back when contrast < 3), `ThemeManager` (all non-System themes use ttk `clam`). **`fonts.py`** registers the bundled IBM Plex Sans per-OS via ctypes before `tk.Tk()`, applies it to Tk's named fonts and matplotlib, and falls back silently to the system font. **`pdf_preview.py`** — `PdfPreview` frame (PyMuPDF → PPM → `tk.PhotoImage`).
- **`Workspace`** (in `escape_explorer.py`) — the single window: Tree | plot | info column in a horizontal `PanedWindow`; the centre is a container that swaps between the plot pane and the `PdfPreview`.
  - **Ticks vs selection:** ticking drives the plot, row *selection* drives Details/Images/Stage map. Ticks are a set of `id(region)` (`Workspace.checked`) so they survive tree rebuilds (filter, theme change, adding/removing files). Tick boxes are `PhotoImage`s on the Treeview rows; a click counts only when `identify_element` reports `"image"`. Redraws go through `_schedule_render` (`after_idle`).
  - **Grouping/stacking:** `group_regions` (by name, ≥50 % x-range overlap, or name per sample / per file) → one panel per group; `draw_stack` draws one spectrum plain or several stacked with an offset and optional normalisation. `view_var` switches each panel to `draw_heatmap` (pcolormesh + colour bar, `heat` ramp per palette) or `draw_waterfall3d` (mplot3d); non-Stack views z-sort each group in `_groups`. `scale_var` / `ke_var` choose the x axis (`add_ke_axis` adds the mirrored top axis); "At cursor" cursors are always stored as binding energy.
  - **View window:** `panels_var` (panels per page) + `panel_start` (row-aligned), `traces_var` + `trace_start` (window over long stacks); wheel / Shift+wheel / scrollbar / slider all just move those two and re-render. Only the visible panels and traces are drawn.
  - **Multiple files:** `Workspace.docs` is a list of readers; `region_parser` maps `id(region)` → its reader (needed for metadata, positions, images, export). `Region.source` labels traces when more than one file is loaded.
  - **Colour = file/sample, tree = legend:** `colour_slots` (one slot per file when several are loaded, else per sample) and `stack_colours` (categorical, or a ramp when a stack shares one slot) are pure functions; `_assign_colours` stores each ticked region's colour in `trace_color`, and `_refresh_boxes` draws that colour as the tree swatch, so tree and plot always agree. `draw_stack` puts end-of-trace labels in a right gutter (`dodge` keeps them apart; the gutter is reserved in `_draw_page`, not by `tight_layout`) and replaces y-ticks on stacks with a scale bar.
  - **Chrome:** one view row (group, normalise, offset), a contextual footer (panels/traces selectors; the scrollbar and trace slider are only packed when they can act, via `_layout_bottom`), a status bar for counts, `Tooltip` for hints, and an info column whose Images / Stage-map notebook only exists when the loaded files have images or positions (`_refresh_info`). The matplotlib toolbar keeps Back/Forward enabled because Windows paints disabled image buttons in the system grey.
  - **Theme:** `set_theme` re-applies ttk styles, rebuilds tick-box images and the tree, recreates the matplotlib toolbar (its icons are recoloured), and updates `matplotlib.rcParams`; PDFs are always drawn inside `rc_context(mpl_rc(PRINT))`.
  - Settings persist in `~/.escape_explorer_config.json` (`load_config`/`save_config`); camera calibration in `~/.escape_explorer_calib.json`.

## Verifying a reader

Readers are validated against **the same data in another format**, never by eye: a text export next to a binary file (`.vgd` ↔ `.avg`), or a vendor's own VAMAS export (`.spe`, `.kal`, `.avg` ↔ `.vms`). Compare energy arrays, counts (allowing documented factors such as dwell time or transmission), hν, pass energy, dwell and positions. Beware that a partner export can itself be wrong (a Casa VAMAS of the Scienta `.txt` has a reversed axis) — check physics (peak positions) before "fixing" a reader to match it. To exercise the GUI without instrument files, monkeypatch `EscapeParser.load` (or a reader's `load`) to fill `regions` and call `_build_tree()` on synthetic `Region`s.
