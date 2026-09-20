"""How long an analysis took: counting time, wall-clock span and time not
spent counting.

Tk-free and numpy-free. Only what the files record is used; a number a file
does not hold is left out (``None``) rather than guessed.

* *counting time* of a region = dwell × points × scans for a scan; for a
  snapshot the energy channels are recorded in parallel, so it is
  dwell × scans. It needs the number of scans, and is ``None`` without it.
* a *run* is one acquisition window (start, end). A file that holds several
  points or depth levels records one window for the whole run, so time is
  worked out over the distinct windows, never per point.
* *instrument in use* is the union of the runs' windows: files that overlap
  (the core levels of one depth profile are stored one file per line) are not
  counted twice, and gaps between sessions are not counted at all.
* *not counting* = instrument in use − counting time: stage moves, settling,
  autofocus, sputtering and every other overhead. It is only stated when every
  region has both its window and its counting time.

Times are ISO strings ("YYYY-MM-DD HH:MM:SS", no zone) in ``Region.extra``
(``t_start`` / ``t_end``), with ``tz`` naming their zone when the reader knows it.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field

SNAPSHOT_MODES = ("Snapshot", "SnapMap")


def parse_ts(text):
    """A ``datetime`` from 'YYYY-MM-DD HH:MM[:SS]' (or with a 'T'), else None."""
    if not text:
        return None
    s = str(text).strip().replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16)):
        try:
            return _dt.datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def fmt_ts(when, tz=""):
    """'2026-08-24 08:20:50 UTC' (the zone only when known)."""
    if when is None:
        return ""
    return when.strftime("%Y-%m-%d %H:%M:%S") + (f" {tz}" if tz else "")


def fmt_duration(seconds):
    """'71 s', '4 min 12 s', '1 h 05 min', '2 d 3 h': two units at most."""
    if seconds is None:
        return ""
    s = int(round(max(0.0, seconds)))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m} min {s:02d} s" if s else f"{m} min"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h} h {m:02d} min"
    d, h = divmod(h, 24)
    return f"{d} d {h} h"


def net_seconds(r):
    """Counting time of one region in seconds, or None when the file does not
    say how many scans were accumulated (or has no dwell)."""
    dwell = r.dwell
    scans = r.extra.get("n_scans")
    if not dwell or not scans:
        return None
    dwell = float(f"{dwell:.6g}")      # a float32 dwell (0.05000000075) is 0.05
    if r.extra.get("acq_mode") in SNAPSHOT_MODES:
        points = 1
    else:
        points = r.n_points
        if not points:
            return None
    return dwell * points * int(scans)


def interval(r):
    """(start, end) datetimes of the run a region belongs to, or None."""
    a, b = parse_ts(r.extra.get("t_start")), parse_ts(r.extra.get("t_end"))
    if a is None or b is None or b < a:
        return None
    return a, b


def union_seconds(intervals):
    """Seconds covered by at least one of the (start, end) intervals."""
    total, cur_a, cur_b = 0.0, None, None
    for a, b in sorted(intervals):
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += (cur_b - cur_a).total_seconds()
            cur_a, cur_b = a, b
        elif b > cur_b:
            cur_b = b
    if cur_b is not None:
        total += (cur_b - cur_a).total_seconds()
    return total


@dataclass
class Summary:
    """Timing of one or more loaded files."""
    n_regions: int = 0
    net: float | None = None          # summed counting time
    n_without_net: int = 0            # regions whose counting time is unknown
    n_without_run: int = 0            # regions with no recorded start and end
    start: _dt.datetime | None = None
    end: _dt.datetime | None = None
    tz: str = ""
    active: float | None = None       # union of the runs' windows
    runs: list = field(default_factory=list)      # distinct (start, end)
    notes: list = field(default_factory=list)

    @property
    def span(self):
        """First start to last finish (idle gaps included)."""
        if self.start is None or self.end is None:
            return None
        return (self.end - self.start).total_seconds()

    @property
    def overhead(self):
        """Time in use that was not counting; None unless every region has
        both its run window and its counting time."""
        if (self.active is None or self.net is None or self.n_without_net
                or self.n_without_run):
            return None
        return max(0.0, self.active - self.net)


def summarise(docs):
    """Timing of a set of loaded files (``Workspace.docs``, or one file)."""
    out = Summary()
    runs, zones, nets = set(), set(), []
    for doc in docs:
        for r in doc.regions:
            out.n_regions += 1
            n = net_seconds(r)
            if n is None:
                out.n_without_net += 1
            else:
                nets.append(n)
            iv = interval(r)
            if iv is None:
                out.n_without_run += 1
            else:
                runs.add(iv)
                zones.add(r.extra.get("tz", ""))
    out.net = sum(nets) if nets else None
    out.runs = sorted(runs)
    if runs:
        out.start = min(a for a, _b in runs)
        out.end = max(b for _a, b in runs)
        out.tz = zones.pop() if len(zones) == 1 else ""
        out.active = union_seconds(runs)
    if out.n_regions and not runs:
        out.notes.append("Start and end times are not recorded in these files.")
    elif out.n_without_run:
        out.notes.append(f"Start and end times are missing for "
                         f"{out.n_without_run} of {out.n_regions} regions.")
    if out.n_without_net:
        out.notes.append(f"Counting time is unknown for {out.n_without_net} "
                         "region(s): the number of scans is not recorded.")
    return out


def sample_net(doc):
    """{sample: counting seconds or None} for one file (a sample's wall-clock
    time is not defined: a run's window covers all the points of a file)."""
    out = {}
    for r in doc.regions:
        n = net_seconds(r)
        cur = out.get(r.sample, 0.0)
        out[r.sample] = None if (n is None or cur is None) else cur + n
    return out


def describe(summary):
    """Lines for a report: [(label, value)], only what is known."""
    rows = []
    if summary.start and summary.end:
        rows.append(("First start", fmt_ts(summary.start, summary.tz)))
        rows.append(("Last finish", fmt_ts(summary.end, summary.tz)))
        rows.append(("First start to last finish", fmt_duration(summary.span)))
    if summary.active is not None:
        rows.append(("Instrument in use", fmt_duration(summary.active)))
    if summary.net is not None:
        rows.append(("Counting time", fmt_duration(summary.net)))
    if summary.overhead is not None:
        rows.append(("Not counting (moves, settling, sputtering, dead time)",
                     fmt_duration(summary.overhead)))
    return rows
