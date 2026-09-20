"""Element data and kinematics for ISS (ion scattering spectroscopy) peak
identification.

A projectile of mass ``M1`` and energy ``E0`` scattering elastically from a
surface atom of mass ``M2`` through the lab angle ``theta`` leaves with

    E1 / E0 = [ (cos theta + sqrt(A^2 - sin^2 theta)) / (1 + A) ]^2,
    A = M2 / M1

(the single-collision binary-collision model). For ``theta >= 90 deg`` a
target lighter than the projectile cannot scatter it backwards, so ``A`` must
be at least 1 there.

Masses are those of the most abundant isotope of each element (u), which is
what defines the ISS peak. The table is the one used by the author's XPSView
project. Pure functions, no Tk.
"""

from __future__ import annotations

import math
import re

# projectile masses (u)
ION_MASS = {"H+": 1.0078, "He+": 4.0026, "Ne+": 19.9924, "Ar+": 39.9624}
DEFAULT_THETA = 123.03           # deg: the scattering angle of some instruments
DEFAULT_ION = "He+"

# symbol: (Z, mass of the most abundant isotope (u), name)
ELEMENTS = {
    'H': (1, 1.0078, 'Hydrogen'), 'He': (2, 4.0026, 'Helium'),
    'Li': (3, 7.016, 'Lithium'), 'Be': (4, 9.0122, 'Beryllium'),
    'B': (5, 11.0093, 'Boron'), 'C': (6, 12.0, 'Carbon'),
    'N': (7, 14.0031, 'Nitrogen'), 'O': (8, 15.9949, 'Oxygen'),
    'F': (9, 18.9984, 'Fluorine'), 'Ne': (10, 19.9924, 'Neon'),
    'Na': (11, 22.9898, 'Sodium'), 'Mg': (12, 23.985, 'Magnesium'),
    'Al': (13, 26.9815, 'Aluminium'), 'Si': (14, 27.9769, 'Silicon'),
    'P': (15, 30.9738, 'Phosphorus'), 'S': (16, 31.9721, 'Sulfur'),
    'Cl': (17, 34.9689, 'Chlorine'), 'Ar': (18, 39.9624, 'Argon'),
    'K': (19, 38.9637, 'Potassium'), 'Ca': (20, 39.9626, 'Calcium'),
    'Sc': (21, 44.9559, 'Scandium'), 'Ti': (22, 47.9479, 'Titanium'),
    'V': (23, 50.944, 'Vanadium'), 'Cr': (24, 51.9405, 'Chromium'),
    'Mn': (25, 54.938, 'Manganese'), 'Fe': (26, 55.9349, 'Iron'),
    'Co': (27, 58.9332, 'Cobalt'), 'Ni': (28, 57.9353, 'Nickel'),
    'Cu': (29, 62.9296, 'Copper'), 'Zn': (30, 63.9291, 'Zinc'),
    'Ga': (31, 68.9256, 'Gallium'), 'Ge': (32, 73.9212, 'Germanium'),
    'As': (33, 74.9216, 'Arsenic'), 'Se': (34, 79.9165, 'Selenium'),
    'Br': (35, 78.9183, 'Bromine'), 'Kr': (36, 83.9115, 'Krypton'),
    'Rb': (37, 84.9118, 'Rubidium'), 'Sr': (38, 87.9056, 'Strontium'),
    'Y': (39, 88.9058, 'Yttrium'), 'Zr': (40, 89.9047, 'Zirconium'),
    'Nb': (41, 92.9064, 'Niobium'), 'Mo': (42, 97.9054, 'Molybdenum'),
    'Tc': (43, 97.9072, 'Technetium'), 'Ru': (44, 101.9043, 'Ruthenium'),
    'Rh': (45, 102.9055, 'Rhodium'), 'Pd': (46, 105.9035, 'Palladium'),
    'Ag': (47, 106.9051, 'Silver'), 'Cd': (48, 113.9034, 'Cadmium'),
    'In': (49, 114.9039, 'Indium'), 'Sn': (50, 119.9022, 'Tin'),
    'Sb': (51, 120.9038, 'Antimony'), 'Te': (52, 129.9062, 'Tellurium'),
    'I': (53, 126.9045, 'Iodine'), 'Xe': (54, 131.9042, 'Xenon'),
    'Cs': (55, 132.9055, 'Caesium'), 'Ba': (56, 137.9052, 'Barium'),
    'La': (57, 138.9064, 'Lanthanum'), 'Ce': (58, 139.9054, 'Cerium'),
    'Pr': (59, 140.9077, 'Praseodymium'), 'Nd': (60, 141.9077, 'Neodymium'),
    'Pm': (61, 144.9128, 'Promethium'), 'Sm': (62, 151.9197, 'Samarium'),
    'Eu': (63, 152.9212, 'Europium'), 'Gd': (64, 157.9241, 'Gadolinium'),
    'Tb': (65, 158.9254, 'Terbium'), 'Dy': (66, 163.9292, 'Dysprosium'),
    'Ho': (67, 164.9303, 'Holmium'), 'Er': (68, 165.9303, 'Erbium'),
    'Tm': (69, 168.9342, 'Thulium'), 'Yb': (70, 173.9389, 'Ytterbium'),
    'Lu': (71, 174.9408, 'Lutetium'), 'Hf': (72, 179.9466, 'Hafnium'),
    'Ta': (73, 180.948, 'Tantalum'), 'W': (74, 183.951, 'Tungsten'),
    'Re': (75, 186.9558, 'Rhenium'), 'Os': (76, 191.9615, 'Osmium'),
    'Ir': (77, 192.9629, 'Iridium'), 'Pt': (78, 194.9648, 'Platinum'),
    'Au': (79, 196.9666, 'Gold'), 'Hg': (80, 201.9706, 'Mercury'),
    'Tl': (81, 204.9744, 'Thallium'), 'Pb': (82, 207.9767, 'Lead'),
    'Bi': (83, 208.9804, 'Bismuth'), 'Po': (84, 208.9824, 'Polonium'),
    'At': (85, 209.9871, 'Astatine'), 'Rn': (86, 222.0176, 'Radon'),
    'Fr': (87, 223.0197, 'Francium'), 'Ra': (88, 226.0254, 'Radium'),
    'Ac': (89, 227.0278, 'Actinium'), 'Th': (90, 232.0381, 'Thorium'),
    'Pa': (91, 231.0359, 'Protactinium'), 'U': (92, 238.0508, 'Uranium'),
}


def kinematic_factor(m_ion, m_target, theta_deg):
    """E1/E0 for a single elastic collision, or None when the projectile
    cannot be scattered through that angle by that target."""
    if not (m_ion > 0 and m_target > 0):
        return None
    a = m_target / m_ion
    th = math.radians(theta_deg)
    s2 = math.sin(th) ** 2
    if a * a < s2:
        return None
    if math.cos(th) < 0 and a < 1.0:          # backscatter from a lighter atom
        return None
    return ((math.cos(th) + math.sqrt(a * a - s2)) / (1.0 + a)) ** 2


def iss_energy(e0, m_ion, m_target, theta_deg):
    """Energy of the scattered projectile (same units as ``e0``), or None."""
    k = kinematic_factor(m_ion, m_target, theta_deg)
    return None if k is None else e0 * k


def ion_mass(ion):
    """Projectile mass for 'He+' / 'He' (u); ValueError for an unknown ion."""
    key = ion if ion in ION_MASS else str(ion).rstrip("+") + "+"
    if key not in ION_MASS:
        raise ValueError(f"unknown ion {ion!r}")
    return ION_MASS[key]


def iss_table(e0=1000.0, ion=DEFAULT_ION, theta_deg=DEFAULT_THETA):
    """``[{symbol, name, z, mass, energy}]`` for every element the ion can
    scatter from, sorted by peak energy."""
    m_ion = ion_mass(ion)
    out = []
    for sym, (z, m, name) in ELEMENTS.items():
        e = iss_energy(e0, m_ion, m, theta_deg)
        if e is not None and m > m_ion:
            out.append({"symbol": sym, "name": name, "z": z, "mass": m,
                        "energy": e})
    out.sort(key=lambda d: d["energy"])
    return out


def candidates(energy, e0=1000.0, ion=DEFAULT_ION, theta_deg=DEFAULT_THETA,
               window=None):
    """Elements whose ISS peak lies near ``energy``, nearest first, each with
    ``delta`` = predicted - measured. ``window`` defaults to
    +-(0.5 % of e0 + 2 eV)."""
    if window is None:
        window = 0.005 * e0 + 2.0
    hits = []
    for d in iss_table(e0, ion, theta_deg):
        delta = d["energy"] - energy
        if abs(delta) <= window:
            hits.append(dict(d, delta=delta))
    hits.sort(key=lambda d: abs(d["delta"]))
    return hits


def mass_from_energy(e1, e0=1000.0, ion=DEFAULT_ION, theta_deg=DEFAULT_THETA):
    """The target mass (u) that scatters to ``e1``: the inverse of the
    kinematic factor (bisection). None outside the possible range."""
    m_ion = ion_mass(ion)
    lo = m_ion * 1.0001 if math.cos(math.radians(theta_deg)) < 0 else \
        m_ion * abs(math.sin(math.radians(theta_deg))) * 1.0001
    hi = 400.0
    k_lo = kinematic_factor(m_ion, lo, theta_deg)
    k_hi = kinematic_factor(m_ion, hi, theta_deg)
    if k_lo is None or k_hi is None or not (k_lo * e0 <= e1 <= k_hi * e0):
        return None
    for _ in range(100):
        mid = (lo + hi) / 2.0
        k = kinematic_factor(m_ion, mid, theta_deg)
        if k is None or k * e0 < e1:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def parse_symbols(text):
    """Element symbols from free text ('Cu, au  NI' -> ['Cu', 'Au', 'Ni']),
    unknown words are ignored; duplicates removed, order kept."""
    out = []
    for word in re.findall(r"[A-Za-z]{1,2}", str(text or "")):
        sym = word[0].upper() + word[1:].lower()
        if sym in ELEMENTS and sym not in out:
            out.append(sym)
    return out


def marks_for(symbols, e0, ion=DEFAULT_ION, theta_deg=DEFAULT_THETA,
              lo=None, hi=None):
    """``[(symbol, energy)]`` predicted peaks of the given elements, limited
    to ``lo``..``hi`` when given."""
    m_ion = ion_mass(ion)
    out = []
    for sym in symbols:
        e = iss_energy(e0, m_ion, ELEMENTS[sym][1], theta_deg)
        if e is None:
            continue
        if (lo is not None and e < lo) or (hi is not None and e > hi):
            continue
        out.append((sym, e))
    return out
