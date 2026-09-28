"""Inelastic mean free path (IMFP) proxies for the Scofield RSF fallback
(``quant.py``'s ``"scofield_tpp2m"``/``"scofield_ke06"`` tiers), Tk-free.

The standard XPS quantification relation is n_A proportional to I_A / (sigma_A
* lambda_A(KE) * T_A): a pure Scofield cross section (``rsf.py``'s
"scofield" library, C 1s = 1.0, a theoretical cross section only) has no
lambda term at all, so comparing two lines whose kinetic energies differ a
lot (round 6's own motivating case: O 1s ~= 950 eV KE vs. Pt 4f ~= 1420 eV
KE) with cross sections alone ignores a real, non-negligible factor (the
two functions here differ by ~35% for that KE pair). Both functions below
give a *relative* factor to multiply onto a Scofield cross section, never a
number to be used or shown on its own; onto that library only -- never onto
the Kratos Axis F1s library or a file's own recorded RSF, both empirical
(Wagner-style) values already calibrated against a real instrument, with
their own implicit lambda(E)*T(E) dependence baked in by being measured --
multiplying either of those by an independent term here would double-count
it, not correct it.

**Provenance, checked directly against KherveFitting's own source**
(``D:\\Software\\KherveFitting\\_internal\\libraries\\Peak_Functions.py``,
class ``AtomicConcentrations``, plus a standalone ``TPP-2M.py`` script) --
neither of the two functions here is a proven, actively-exercised feature
the way ``rsf.py``'s RSF libraries were:

- ``imfp_nm``: KherveFitting's ``calculate_imfp_tpp2m`` is a correctly
  formed TPP-2M equation (S. Tanuma, C.J. Powell, D.R. Penn, *Surf.
  Interface Anal.* 21, 165-176, 1993 -- the formula shape here matches the
  published equation, independently checked, and the values it gives
  (e.g. ~2.37 nm at 1000 eV) sit in the expected 0.5-4 nm range for
  50-2000 eV) using fixed "average matrix" constants (cited to Briggs &
  Grant, *Surface Analysis by XPS and AES*, 2nd ed., Wiley 2003, p.84-85 --
  not independently checked past that citation) rather than a real
  material's own density/molecular weight/valence-electron count/band gap,
  which sidesteps the fact that eXPoSe has no way to know an arbitrary
  sample's own values for those (KherveFitting's *other* TPP-2M variant,
  ``calculate_imfp_tpp2m_WITHOUT_VALUES_BUT_GOOD``, takes real per-material
  values as parameters, but nothing in KherveFitting ever calls it and no
  material database exists there to supply them; it also uses ``log2``
  where the published formula needs natural ``log`` -- a real
  transcription bug in code this module does not port). Exhaustive search
  of the whole KherveFitting install found **no call site for either
  function outside their own definitions, and no menu item or dialog
  anywhere that reaches them** -- both are dead code there; KherveFitting's
  own actual atomic-percent math is plain user-typed RSF/TXFN, no lambda
  term anywhere.
- ``ke_power_factor``: not derived from any formula at all -- it is
  literally what KherveFitting's own ``calculate_imfp_tpp2m`` docstring
  references as *Thermo Avantage's* own convention (a stray, otherwise
  unused ``imfp2 = imfp * 26.2`` line in that same function, commented
  "Avantage add a scaling factor so that corrected area matches the one
  obtained with KE^0.6 -- To compare KherveFitting with Avantage we will
  also apply this factor"). Included as a second, simpler, faster
  approximation for comparison, not claimed to be as physically complete
  as TPP-2M.

Only *ratios* between lines matter for atomic percent (the same reason the
Scofield table's own absolute scale is arbitrary -- C 1s = 1.0 is a
convention, not a physical constant), so neither function needs, or is
given, a proportionality constant: they return exactly what the formula/
convention states, nothing normalised or rescaled.
"""

import math

# Briggs & Grant's "average matrix" constants (see the module docstring)
N_V = 4.684
RHO = 6.767          # g/cm^3
MOLAR_MASS = 137.51  # g/mol
E_GAP = 0.0          # eV

MIN_KE, MAX_KE = 50.0, 2000.0   # TPP-2M's own stated validity range (eV)

KE_POWER_EXPONENT = 0.6   # Thermo Avantage's own convention -- see the
                          # module docstring's "ke_power_factor" paragraph


def imfp_nm(kinetic_energy):
    """The TPP-2M inelastic mean free path, in nm, for an electron of this
    kinetic energy (eV), in the fixed "average matrix" -- None when
    ``kinetic_energy`` is missing or outside TPP-2M's own stated
    50-2000 eV validity range (never an unreliable extrapolation)."""
    if not kinetic_energy or not (MIN_KE <= kinetic_energy <= MAX_KE):
        return None
    e = float(kinetic_energy)
    e_p = 28.8 * math.sqrt(N_V * RHO / MOLAR_MASS)
    u = N_V * RHO / MOLAR_MASS
    beta = (-0.10 + 0.944 / math.sqrt(e_p ** 2 + E_GAP ** 2)
           + 0.069 * RHO ** 0.1)
    gamma = 0.191 * RHO ** -0.5
    c = 1.97 - 0.91 * u
    d = 53.4 - 20.8 * u
    imfp_angstrom = e / (e_p ** 2 * (beta * math.log(gamma * e)
                                     - c / e + d / e ** 2))
    return imfp_angstrom / 10.0


def ke_power_factor(kinetic_energy):
    """A relative mean-free-path proxy, ``kinetic_energy ** 0.6`` -- not a
    physical length (no nm/Angstrom unit, no material assumed at all), see
    the module docstring's "ke_power_factor" paragraph. None when
    ``kinetic_energy`` is not a positive number."""
    if not kinetic_energy or kinetic_energy <= 0:
        return None
    return float(kinetic_energy) ** KE_POWER_EXPONENT
