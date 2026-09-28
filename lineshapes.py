"""Line shapes and backgrounds for reconstructing CasaXPS fits.

All curves are computed on an **ascending kinetic-energy grid** (the frame in
which CasaXPS stores positions) and scaled to the stored *area* (intensity
integrated over energy).

* ``GL(m)``  product Gaussian/Lorentzian, ``m`` = % Lorentzian
* ``SGL(m)`` sum Gaussian/Lorentzian
* ``LA(a,b,m)`` (also ``LA(a,m)`` = ``LA(a,a,m)``, or ``LA(m)``) asymmetric
  Lorentzian, Gaussian-broadened
* ``LF(a,b,w,m)`` as LA with a finite tail of width ``w``

GL and SGL are exact. **LA and LF are reconstructions**: their Gaussian
broadening scale is still an empirical calibration (below), but the base
kernel itself is no longer a third-party guess -- CasaXPS's own *Cookbook*
(Casa Software Ltd., 2026, pp.65-66) gives ``LA(x: alpha,beta,w) = N *
INTEGRAL(lg(tau; alpha,beta) * g(x-tau; w) dtau)`` with ``lg(x: alpha,beta)
= l(x)**alpha`` for ``x <= 0`` and ``l(x)**beta`` for ``x > 0`` -- matching
this module's formula exactly, and matching the independent third-party
write-up this was originally reconstructed from (Major et al., *Surf.
Interface Anal.* 53 (2021) 689, Eq. 6; Major, Shah, Fernandez, Fairley (Casa
Software Ltd.) and Linford, *Vacuum Technology & Coating*, March 2020,
Eq. 3). The Gaussian broadening's own scale was calibrated on real CasaXPS
fits (``tests/`` and the validation notes in the README give the residuals).
The stored areas, positions and widths are CasaXPS's own numbers.

**The shared Lorentzian width.** Raising a Lorentzian to a power ``p != 1``
shrinks its own half-max distance by ``sqrt(2**(1/p) - 1)`` relative to
``p = 1``, so using the file's ``fwhm`` unscaled as each side's own width (as
this module did before) makes a strongly asymmetric component (e.g.
``LA(1.2,5,8)``, CasaXPS's sharp metallic-tail cutoff) reconstruct far too
tall for its stored area -- confirmed on two independent real files
(titanium and vanadium metallic-tail examples in ``tests/``), the
reconstructed peak standing up to ~10-18 % of the peak height above the raw
data at the component's own maximum, hidden by ``residual_rms`` because that
metric averages over the whole curve. The fix (from KherveFitting's own
``LA``/``LAxG`` implementation, ``libraries/Peak_Functions.py``,
github.com/KherveFitting/KherveFitting, retrieved 2026-09-25) is **one
Lorentzian width shared by both sides**, chosen so the two sides' own
half-max distances add up to the stored ``fwhm`` (not each side independently
reproducing it, which was tried first and made CasaXPS's own worked LA
examples with mild asymmetry measurably worse while helping the severe
cases): ``F = 2*fwhm / (sqrt(2**(1/a)-1) + sqrt(2**(1/b)-1))``, which is
exactly ``fwhm`` for an unmodified Lorentzian (``a == b == 1``) -- the GL/SGL
shapes and the 2-argument ``LA(m)``/``LF(...)`` shorthand (which default
``a`` and ``b`` to 1) are unaffected; a symmetric but non-unity pair (e.g.
``LA(2,2,m)``) is rescaled too, since raising *either* side to a power other
than 1 narrows it the same way.
Checked against every real ``LA``/``LF``-fitted file available (titanium,
copper, both vanadium exports, MXene): titanium's worst-case overshoot fell
from 18.3 % to 8.7 %, this file's vanadium example from 9.85 % to 4.70 %, and
6 of MXene's 8 affected regions improved too (the other 2 regressed by under
one percentage point). ``TestLAAsymmetryAccuracy`` in ``tests/test_casafit.py``
is a canary against this getting worse.

**The 1-argument ``LA(m)`` shorthand is not ``LA(1,1,m)``.** Every finding
above this paragraph, and two rejected leads that used to be recorded here
(a "corrected direction" retune, and a claim that no ``GAUSS_K`` can round out
a symmetric ``LA(m)`` component's own apex), were all tested by feeding the
shorthand's ``m`` (0-100) straight into the same formula the explicit
``LA(a,b,m)`` form uses -- which is wrong. CasaXPS's own definition (Fairley
et al., "Practical guide to understanding goodness-of-fit metrics ... using
nylon as an example," *J. Vac. Sci. Technol. A* 41(1) 2023, supplementary
information, Eq. 4-6; also *Cookbook* 2026 p.19, Figure 15's caption) is
``LA(x: alpha,beta,n) = N * INTEGRAL(lg(tau; alpha,beta) * g(x-tau; f_G(n))
dtau)`` (a generalised Lorentzian convolved with a Gaussian whose width is
controlled by ``n``) and, separately, ``LA(x,m) = LA(x: 1,1, 1401 -
(m/100)*1401)``: the shorthand's ``m`` and the explicit form's ``n`` run in
**opposite directions** (``LA(0)`` -> ``n = 1401``, ``LA(100)`` -> ``n =
0``), not the same variable. ``parse_shape`` used to set ``m = ps[0]`` for
the shorthand directly; it now applies this conversion, so every real
``LA(m)``-shorthand file (PET's ``LA(50)`` among them) is now evaluated at
its true ``n = 1401 - 14.01*m``, and the explicit 3-argument form is
unaffected (it was already using ``n`` correctly).

**The 2-argument ``LA(a,n)`` form is a separate case, and was not
distinguished from the 1-argument shorthand above at all** -- a second,
independent bug, found while reading the *Cookbook* itself (2026 p.66):
*"Abbreviation for LA lineshape: LA(x: alpha, w) = LA(x: alpha, alpha, w)"*
-- ``b`` is implicitly ``a`` (a symmetric-but-non-unity Lorentzian power),
and the trailing number is the explicit form's own ``n``, used directly --
*not* run through the 1-argument shorthand's ``m``-to-``n`` conversion
above. ``parse_shape`` used to fall into the same ``else`` branch as the
1-argument case for *any* fewer-than-3-argument string, taking only
``ps[0]`` through the wrong (1-argument) formula regardless of whether a
second number was present at all -- so a real ``LA(1.53,243)`` file was
silently evaluated as ``a=b=1, n=1401-14.01*1.53 approx 1380`` instead of
the correct ``a=b=1.53, n=243``, both the exponent and the Gaussian width
wrong.
Confirmed on the one real file with this form found across the full local
corpus (~700 files, ``D:\Temp`` and ``~\Downloads``):
``~\Downloads\assigned.vms``, a 5-sample Mo 3d/S 2s fit (MoS2/MoO2/MoO3/WS2
mixed system, ~10 ``LA(1.53,243)`` components per region). Comparing
``casafit.curves()``'s reconstruction against this file's own raw data,
before/after the fix, ``residual_rms`` / ``chi2_red`` per region:
``RW_WS2_MoS2_thicker`` 8.86% / 139.3 -> 5.32% / 54.9,
``RW_Tha_MoS2`` 7.23% / 930.2 -> 3.98% / 329.8,
``RW_sonic_MoS2`` 7.73% / 2339.2 -> 4.39% / 917.5,
``RW_WS2_MoS2`` 8.59% / 129.8 -> 5.38% / 52.6,
``RW_Nb_MoS2`` 10.81% / 455.3 -> 6.84% / 209.7 -- both metrics roughly halve
across every region.

This was found the same way the ``DS`` calibration below was: two new
synthetic files built specifically to sweep ``m`` in a controlled way against
one shared raw peak, with the components' FWHM deliberately linked equal so
it is the only free parameter left to compensate for a "wrong" ``m`` --
``D:\Temp\for claude files\synthetic PMMA.vms`` (``LA(m)`` shorthand, ``m =
0..100``, 11 CasaXPS refits) and ``D:\Temp\for claude files\synthetic PMMA.
3 param LAvms.vms`` (explicit ``LA(1,1,m)``, ``m = 1000..0``), both refitting
the same raw data. Comparing the reconstructed envelope to the raw data
directly does not work on this pair (their components' stored ``Area`` is
~100-450x too small for the data's actual peak height -- an unrelated
data-quality artifact of the file, not a shape question); instead, since FWHM
is the fit's only free width parameter, how the reported (linked) FWHM must
drift as ``m`` sweeps -- via the standard pseudo-Voigt width approximation,
``FWHM_V = 0.5346*FWHM_L + sqrt(0.2166*FWHM_L**2 + FWHM_G**2)`` -- is a clean
signature of the true broadening-vs-``m`` relationship: the correct ``(K, P)``
should make the implied total width stay constant across the whole sweep,
since it is the same underlying peak throughout. Feeding both files' raw
``m`` into one formula gave opposite-signed answers (this is what surfaced
the shorthand/explicit scale bug above); on the corrected, unified ``n``
scale, a joint fit -- minimising that width-consistency spread (today's
formula: 8.9 % coefficient of variation across the 21-point sweep) while
never letting any real ``LA``/``LF``-fitted region in the existing corpus get
more than ~0.25 percentage points worse than it already was -- converges on
``GAUSS_K["LA"] = 0.41``, ``GAUSS_P["LA"] = 0.60`` (replacing ``0.20`` and an
implicit exponent of 1; used the same way ``GAUSS_P["DS"]`` already is,
below), bringing the sweep's spread down to ~7.9 %. **The real corpus this
was checked against is bigger than the "six real fits" this constant was
first calibrated on**, and bigger than what the earlier "not adopted"
attempts above were checked against: 25 ``LA``/``LF``-fitted regions across 7
files (titanium `fitting example` and the `Metal Depth Profile` instructors'
file -- the latter has both a clean 2-component metal region and an
8-component mixed metal+oxide region in one file, the busiest region in the
corpus and the one that ruled out a more aggressive retune tried first --
copper, vanadium (both the plain and `For Instructors` exports), two MXene
files, PET). Measured effect: titanium `fitting example`'s worst-case
overshoot (the number the old ``TestLAAsymmetryAccuracy`` ceiling comment was
built around) falls from 8.70 % to 6.27 %; every other region in the corpus
moves by at most ~0.24 percentage points either way; PET's shorthand
``LA(50)`` component (now correctly ``n = 700.5``, not ``50``) moves its
C 1s/O 1s overshoot by ~0.02 pp. The worst case across the whole corpus stays
PET's O 1s, 9.46 % to 9.43 % (very slightly better). Do not retune
``GAUSS_K``/``GAUSS_P`` again without new evidence beyond what produced this
result -- but do re-run this comparison (this file's own module docstring
here, and ``TestLAAsymmetryAccuracy``/``TestPETFile``/``TestLASweepShape``)
before touching either constant, since the previous two "not adopted"
conclusions in this file were reached on a mis-scaled ``m`` and turned out to
be wrong, and a first attempt at this same retune (``K=0.90, P=0.80``, fit
only against a 5-file subset of the corpus) passed every test available at
the time but pushed the `Metal Depth Profile` file's 8-component region's
overshoot from 8.8 % to 16.3 % -- always check the *busiest*, most
overlapping real region available, not just the cleanest ones.

**A finite tail cutoff (generalising ``LF``'s ``w`` to plain ``LA``) does not
help either, and makes most real files worse.** The obvious-looking fix for a
tall, narrow component's tail visibly outrunning the real data (also seen on
the PET file: ``C 1s (Ring)``, ``LA(0.8,1.5,243)``, contributes 51.7 counts
~2.8 eV past its own peak where the real background-subtracted signal is only
~17) is to taper the raw shape to zero at some multiple of its width. Tried
and rejected: ``component_curve`` always rescales a component so its
*analytic* integral equals CasaXPS's stored area (this is what
``test_a_narrow_window_does_not_inflate_the_peak`` protects), so cutting the
tail removes area that the rescaling then has to put back into the peak,
making the peak itself taller. Swept against every real ``LA``/``LF`` file
this codebase has (titanium, vanadium, copper, HOPG, ``DS Variations``, PET --
18 fitted regions): every taper width tried (from 15 down to 3 times the
component's own FWHM) made more real regions' overshoot worse than it made
PET's better -- e.g. at a 3-FWHM cutoff, PET's own C 1s overshoot went from
7.6% to 26% (the inflated Ring peak now overshoots its neighbours instead).
The tail's visible extent is fixed in ``plots.draw_fit`` instead (a display
choice, not a change to the shape or its stored area -- see
``_COMPONENT_VISIBLE_FLOOR`` there).

**A third-party independent reconstruction (Kiwi AI, retrieved 2026-09-27,
``D:\Temp\for claude files\lineshapes with cliping.txt``) was reviewed against
this module.** Its kernels match the same published forms already used here
(no new information). Its treatment of CasaXPS's fit-region window hard-clips
each shape and **renormalizes by the clipped area** -- the same family of idea
as the rejected tail cutoff above, and wrong for the same reason (confirmed
again here, not just inferred): our own display-only clip in
``casafit.curves`` (NaN outside the region, no renormalization) is what real
files need. Its ``LF`` finite tail, though, uses a **logistic sigmoid** damping
function rather than this module's polynomial ``(1 - r^2)^2`` window -- a
genuinely different, previously untried idea, checked here: swapping in a
same-convention sigmoid (cutoff centred at the same ``r = |x-pos|/fwhm/w = 1``)
and re-running ``casafit.curves`` on every real ``LF``-fitted component
available (5, across ``Titanium Metal Depth Profile - INSTRUCTORS.vms`` and
``D:\Temp\for claude files\PtCl2\PtCl2_quantified.vms``) moved
``residual_rms``/overshoot by under half a percentage point either way
(``residual_rms`` very slightly worse on all 5, overshoot very slightly better
on 3 of 5) -- noise, not an improvement. Expected: every real ``w`` seen there
(45-75) puts the taper's own cutoff radius (57-274 eV) far outside any of
these files' fit-region windows (a few to a few tens of eV), so in every real
file available ``LF`` is numerically indistinguishable from plain ``LA`` (bar
the ``m``/Gaussian-width term) regardless of which taper shape is used -- this
comparison cannot tell the two forms apart without a file whose ``w`` is small
enough to produce a visible cutoff inside its own window. Not adopted; do not
retune the taper's functional form again without one.

**A(a,b,n)GL(m) / A(a,b,n)SGL(m): the Gelius asymmetric shape.** Sourced
from CasaXPS's own "Peak Fitting in XPS" (Casa Software Ltd, 2006, p.20 --
read directly, not via a third party): a symmetric ``GL(m)``/``SGL(m)`` base
plus a one-sided tail on the low-KE (high binding energy) side,
``A(x) = base(x) + w(a,b)*[AW(x) - G0(x)]`` for ``x`` below the position,
plain ``base(x)`` above it, where ``w(a,b) = b*(0.7 + 0.3/(a+0.01))``,
``AW(x) = exp(-(u/(fwhm + a*u))**2)`` with ``u = 2*sqrt(ln2)*|x-pos|``, and
``G0`` the plain Gaussian of the same ``fwhm`` (``AW`` at ``a = 0``). This
independent reading matches KherveFitting's own ``A_GL``/``A_SGL``
(``Peak_Functions.py``, retrieved 2026-09-27), which cites the same primary
source and, once its own BE-ascending axis is un-mirrored back to this
module's ascending-KE grid, is algebraically identical -- good agreement
between an independent derivation and a third party's, from the same source.

**The tail term does not always decay to zero.** ``AW(x) - G0(x)`` approaches
a nonzero plateau ``w*exp(-1/a**2)`` as ``x`` moves far from the peak
(confirmed both analytically and numerically), rather than the power-law
decay every other reconstructed shape here has -- CasaXPS's own whitepaper
warns of exactly this ("intensity from the nominal ... region ... can cause
... to move beyond the region defining the background ... not suitable for
quantification without intensity calibration"). For small ``a`` (the one
real value seen anywhere, in the whitepaper's own worked poly(propylene)
example, ``A(0.15,0.7,20)SGL(12)``, is ``0.15``) the plateau is negligible
(``exp(-1/0.15**2)`` ~ 1e-19) and ``component_curve``'s wide-grid area
normalisation is unaffected; a fit using a much larger ``a`` would make that
normalisation window-dependent and unreliable. Not guarded against here --
no real file with a large ``a`` has been seen to know whether CasaXPS's own
usage ever goes there.

**The Gaussian convolution width (the shape string's ``n``, 0-499) is
uncalibrated.** The primary source's own formula has no ``n`` in it at all
(a separate line says only that the shape is "convoluted with a Gaussian
with width characterized by an integer 0 <= n <= 499", the same phrasing
used for ``DS``); lacking a real ``A``/``SGL``-Gelius-fitted file anywhere in
the available corpora (checked: the Brazil Training Course, both Avantage/
Kratos reference sets, the CasaXPS VAMAS corpus and the MXene/PET files all
have zero components using this shape), ``GAUSS_K["A"]`` and
``GAUSS_P["A"]`` are left at the same neutral ``(25/n)**1`` reference point
DS/LA already use (``K = 1.0, P = 1.0`` -- i.e. ``gw = fwhm`` at ``n = 25``),
not a calibrated value. Retune when a real fitted file becomes available,
the same way DS's own calibration was redone once real ``(a, n)`` coverage
appeared.

**TLA: formula and parameter order now confirmed from a primary source; the
Gaussian-convolution calibration is not.** Originally implemented (flagged,
at the user's explicit direction) from KherveFitting's own reconstruction
alone (``Peak_Functions.py``, ``TLA``/``_tla_unit_profile``/
``_tla_width_scale``), which itself cited an unlocatable "CasaXPS Cookbook
(2026), Line shapes section" -- no way at the time to cross-check it against
a primary CasaXPS source, the same "third party might be wrong" risk the
``LA(m)`` shorthand bug above was a cautionary tale about. That Cookbook has
since been located (Casa Software Ltd., 2026, p.66) and checked term by
term: ``TLA(x: alpha,mu,w) = N * INTEGRAL(T(tau; alpha,mu) * g(x-tau; w)
dtau)``, ``T(x: alpha,mu) = [1/(1+4x^2)]**alpha * [pi/2 - atan(2x) + pi/mu]``
for ``mu > 0, alpha > 0`` -- an exact match to this module's own
``_tla_values`` (Lorentzian raised to ``alpha`` = ``sp["a"]``, modulated by
the same arctangent tail factor with ``mu`` = ``sp["b"]``, larger ``mu`` =
weaker asymmetry), **and** confirms the shape string's parameter order is
``TLA(alpha, mu, n)`` as this module already assumed (KherveFitting's own
function signature groups ``(mu, wg, alpha)`` for its *fitting grid
columns* only, which said nothing about the on-disk string's own order --
this was a guess that turned out right, not something the Cookbook itself
was needed to get the code working, but it removes the doubt). What the
Cookbook does *not* give is a numeric Gaussian-convolution width: the width
``w``/``n`` has no closed form connecting the shape string's ``0-499`` code
to an actual eV width for a given ``fwhm``, so ``GAUSS_K["TLA"] =
GAUSS_P["TLA"] = 1.0`` remains the same neutral, uncalibrated reference
point DS/``A`` above use (``gw = fwhm`` at ``n = 25``) -- retune only when a
real ``TLA``-fitted file becomes available, the same way DS's and the
2-argument ``LA`` bug above were. ``_tla_width_scale`` measuring the base
shape's FWHM numerically (no closed form exists for that either) is
unaffected by any of this. Until a real file calibrates the convolution
width, treat a ``TLA``-reconstructed component's overall breadth as
illustrative even though its underlying asymmetric-Lorentzian shape and
parameter order are now on solid ground.

**Tail suffix -- formula now known, still unvalidated.** CasaXPS also lets a
``GL``/``SGL`` shape string carry a trailing ``T(k)`` tail modifier
(``GL(30)T(1.5)``), used for asymmetric metallic peaks. ``parse_shape``
recognises and strips this suffix so the base shape's own parameters parse
correctly, but the tail itself is not reconstructed. Unlike when this was
first written, the formula is no longer unpublished: the *Cookbook* (2026,
p.67) gives it in full -- ``E(x: j,k) = j*exp(k*x)`` for ``x < 0`` else
``0``, and ``SGL(x,m,n)T(k) = (SGL(x,m) + (1-SGL(x,m))*E(x: 1,k)) * G(n)``
(``T(k)`` is the ``j=1`` case of a more general ``PHI(j,k)``; ``GL`` has the
same two variants). The Cookbook also documents two further mechanisms not
implemented here: a general ``ST(mu,gamma)`` asymmetry prefix applicable to
*any* line shape (p.66: ``S(mu)F(x) = N*F(x)*[INTEGRAL(F(phi)dphi, x, inf) +
A/mu]``, ``ST(mu,gamma)F(x) = S(mu)F convolved with a Gaussian of width
gamma`` -- distinct from both ``T(k)``/``PHI(j,k)`` above and the Gelius
``A(a,b,n)`` shape below), and a plain 3-argument extension of ``GL``/
``SGL`` themselves, ``GL(x,m,n) = GL(x,m) * G(n)`` (p.67) -- a second
Gaussian convolution on top of the base pseudo-Voigt that this module's own
``GL``/``SGL``/``VOIGT`` branch of ``parse_shape`` would today silently
truncate to plain ``GL(m)``, reading only ``ps[0]``, if a string like that
ever appeared. None of ``T(k)``/``PHI(j,k)``, ``ST(mu,gamma)``, or a
2-argument ``GL(m,n)``/``SGL(m,n)`` turned up anywhere in the ~700-file
local corpus scan that found the real 2-argument ``LA`` file above, nor in
any of the individually-named real files elsewhere in this module -- so
none of the three is implemented; an affected component still draws as its
plain base shape and is flagged ``approximate`` by ``is_exact`` (honestly
unreconstructed, the same treatment ``QF``/``H``/``F`` get below), rather
than silently wrong. Implement whichever one a real fitted file turns up
first.

**Unrecognised shape names.** A shape name CasaXPS writes that this module
does not implement (``QF``, or CasaXPS's own undocumented ``H``/``F``
families -- seen, unreconstructed, on a real file with three refits of one
C 1s region: ``H(0.09,250)SGL(90)`` and ``F(0.09,32,150)SGL(90)`` alongside
the ``DS`` fit below) used to be silently coerced into an exact ``GL(mix)``
using its first numeric token as a 0-100 % mix -- for ``DS(0.09,500)`` (see
below) this drew an almost-pure Gaussian and reported it as *exact*, 12 % of
peak height off and 68 % over the real peak at its own maximum, with no
warning. ``parse_shape`` now keeps the real name (so ``is_exact`` correctly
reports it unreconstructed) and ``_raw_values`` draws it as a plain
unmodified Lorentzian of the component's own ``fwhm`` (the ``a = b = 1``,
``w = 0`` default of the LA/LF branch below, no Gaussian broadening) purely
so something renders -- not a guess at the real shape, just a placeholder
that is honestly flagged. A compound name CasaXPS writes as a base shape
followed by a second one in its own parentheses (``H(0.09,250)SGL(90)``, or
the documented ``DS(a,n)GL(m)``/``DS(a,n)SGL(m)`` blend) parses as the
leading shape with the remainder kept verbatim in ``parse_shape``'s
``suffix`` key rather than failing to parse at all; the blend itself is not
reconstructed (no real file with it has been available), so a ``DS`` with a
suffix draws as plain ``DS``, same precedent as the ``T(k)`` tail.

**DS(a, n): Doniach-Sunjic.** CasaXPS's asymmetric-tail shape for metallic /
graphitic peaks (e.g. HOPG's C 1s). Reconstructed from the published kernel
(Doniach & Sunjic 1970; the form here matches an independent reconstruction
retrieved 2026-09-26 from public papers, itself unvalidated) --
``t = 2(x-pos)/fwhm``, ``DS_raw(t; a) = cos(pi*a/2 + (1-a)*atan(t)) /
(1+4t^2)**((1-a)/2)`` -- convolved with a Gaussian through the same
``gauss_conv`` + area-normalisation pipeline LA/LF already use. This raw
kernel's own asymmetry direction is exact (a fast, power-law-t^-(2-a) decay
on the low-binding-energy side, KE > pos; the well-known long t^-(1-a) tail
on the high-BE side, KE < pos) -- only the Gaussian convolution width is a
calibration.

The convolution width uses the same ``GAUSS_K`` dial as LA/LF but, unlike
them, its own exponent on ``(25/n)`` (``GAUSS_P``, 1 for every other shape):
``gw = fwhm * GAUSS_K["DS"] * (25/n) ** GAUSS_P["DS"]``. First calibrated on
one ``DS(0.09,500)`` component (a plain ``K``, implicit exponent 1) it
overshot the real data specifically on the low-BE side once more real
``(a, n)`` variations of the *same* underlying spectrum became available
(``D:\Temp\for claude files\DS Variations.vms``: 7 CasaXPS refits of one C1s
scan, ``a`` in 0.05-0.10, ``n`` in 200/400/500) -- a symmetric Gaussian
widens a naturally sharp edge (the fast-decaying low-BE side) far more
visibly than it perturbs an already-broad tail, so too large a ``gw`` there
reads exactly as "the low-BE side extends past the data". A per-region
residual-minimising search over ``gw`` on those 7 regions showed the true
optimum scales more weakly with ``n`` than ``25/n`` (exponent 1): fitting
``gw* = fwhm * K' * (25/n)**p`` by ordinary least squares on
``log(gw*/fwhm)`` vs ``log(25/n)`` gives **``GAUSS_K["DS"] = 1.8445``,
``GAUSS_P["DS"] = 0.5737``** (R^2 = 0.886 over the 7 points -- real but
imperfect; ``a`` has a secondary effect on the true optimum, ~5.5 % relative
spread within one ``n`` group, not modelled -- a third parameter is not
worth fitting on 7 points). Against today's numbers (``K=5.6``, implicit
``p=1``) this drops the mean ``residual_rms`` across the 7 regions from
1.49 % to 1.30 % of peak height and the mean low-BE-side overshoot from
5.27 % to 3.83 % (worst case 6.68 % to 6.69 %; one region regresses
~0.03 pp, the rest improve, e.g. ``DS(0.05,200)``'s overshoot 5.68 % to
3.41 %). A ``gw`` with no ``n`` dependence at all was tried and rejected: it
removes the low-BE overshoot almost entirely but then under-broadens the
peak apex at ``n=200``, visibly worsening the whole-curve fit there --
``n`` has to stay in the formula, just with a weaker exponent. **This is
still one calibration spectrum** (now with rich ``(a, n)`` coverage rather
than one point, not an independent second measurement): retune again only
with a ``DS`` fit on genuinely different real data, not on general
principle.

numpy is needed for evaluation; everything else here is plain Python.
"""

from __future__ import annotations

import math
import re

GAUSS_K = {"LF": 0.60, "LA": 0.41, "DS": 1.8445, "A": 1.0, "TLA": 1.0}
GAUSS_P = {"DS": 0.5737, "LA": 0.60, "A": 1.0, "TLA": 1.0}  # exponent on
                                    # (25/m); every other shape is 1 (below)
_LN2_4 = 2.772588722239781               # 4 ln 2


_TAIL_SUFFIX_RE = re.compile(r"^(.*\))\s*T\(\s*[^()]*\s*\)\s*$", re.IGNORECASE)
_SHAPE_RE = re.compile(r"^\s*([A-Za-z]+)\s*\(([^()]*)\)\s*(.*)$")
_A_BASE_RE = re.compile(r"(?i)^(SGL|GL)\(([^()]*)\)")


def parse_shape(text) -> dict:
    """``{"kind", "a", "b", "w", "m", "mix", "tail", "suffix", "params"}``
    from a shape string such as ``GL(30)``, ``LA(1.1,1.9,7)``,
    ``LF(1.1,1.2,75,200)``, ``DS(0.09,500)``, a ``GL``/``SGL`` shape with a
    CasaXPS tail suffix (``GL(30)T(1.5)``, used for asymmetric metallic
    peaks) or a compound shape naming a second one in its own parentheses
    (``H(0.09,250)SGL(90)``, or the documented ``DS(a,n)GL(m)``/
    ``DS(a,n)SGL(m)`` blend). ``tail`` is True when the ``T(k)`` suffix was
    present -- the base shape's own parameters still parse correctly, but
    the tail itself is not reconstructed (see the module docstring).
    ``suffix`` holds a compound name's second shape verbatim, unparsed. A
    name this module does not implement (``QF``, CasaXPS's own ``H``/``F``
    families, ...) keeps its real ``kind`` and stores its raw numeric tokens
    in ``params`` rather than being coerced into a fabricated ``GL(mix)`` --
    see the module docstring. An unreadable string (no ``NAME(...)`` at all)
    is a symmetric Lorentzian-Gaussian mix ("GL(30)")."""
    text = str(text or "")
    tail = False
    tm = _TAIL_SUFFIX_RE.match(text)
    if tm:
        text = tm.group(1)
        tail = True
    m = _SHAPE_RE.match(text)
    if not m:
        return {"kind": "GL", "mix": 30.0, "a": 1.0, "b": 1.0, "w": 0.0,
                "m": 0.0, "tail": tail, "suffix": "", "params": []}
    kind = m.group(1).upper()
    ps = []
    for tok in m.group(2).split(","):
        try:
            ps.append(float(tok))
        except ValueError:
            pass
    suffix = m.group(3).strip()
    out = {"kind": kind, "a": 1.0, "b": 1.0, "w": 0.0, "m": 0.0, "mix": 0.0,
           "tail": tail, "suffix": suffix, "params": ps}
    if kind == "LF":
        out.update(a=ps[0] if ps else 1.0, b=ps[1] if len(ps) > 1 else 1.0,
                   w=ps[2] if len(ps) > 2 else 0.0,
                   m=ps[3] if len(ps) > 3 else 0.0)
    elif kind == "LA":
        if len(ps) >= 3:
            out.update(a=ps[0], b=ps[1], m=ps[2])
        elif len(ps) == 2:
            # CasaXPS Cookbook 2026, p.66: "Abbreviation for LA lineshape:
            # LA(x: alpha, w) = LA(x: alpha, alpha, w)" -- the 2-argument
            # form's own w/n is used directly, unlike the 1-argument
            # shorthand below (see module docstring: this used to be
            # conflated with that shorthand, a real bug on a real file).
            out.update(a=ps[0], b=ps[0], m=ps[1])
        else:
            # The 1-argument shorthand's m (0-100) is NOT the explicit form's
            # own m/n -- CasaXPS defines LA(m) = LA(1,1, 1401 - (m/100)*1401)
            # (Cookbook 2026 p.19/66; Fairley et al., JVST A 41(1) 2023
            # supplementary, Eq. 6): the two run in opposite directions
            # (LA(0) -> n=1401, LA(100) -> n=0).
            raw = ps[0] if ps else 0.0
            out.update(m=1401.0 - 14.01 * raw)
    elif kind == "DS":
        out.update(a=ps[0] if ps else 0.0, m=ps[1] if len(ps) > 1 else 0.0)
    elif kind in ("GL", "SGL", "VOIGT"):
        out["mix"] = ps[0] if ps else 30.0
    elif kind == "A":
        # A(a,b,n)GL(m) / A(a,b,n)SGL(m): the Gelius asymmetric shape (see
        # module docstring). a, b control the tail; n (kept in "m", like DS's
        # own Gaussian-conv code) is the Gaussian convolution width; the
        # trailing GL(m)/SGL(m) is the symmetric base and its own mix.
        out.update(a=ps[0] if ps else 0.2, b=ps[1] if len(ps) > 1 else 0.4,
                   m=ps[2] if len(ps) > 2 else 0.0)
        bm = _A_BASE_RE.match(suffix)
        out["base"] = bm.group(1).upper() if bm else "GL"
        out["mix"] = float(bm.group(2)) if bm and bm.group(2) else 30.0
    elif kind == "TLA":
        # TLA(alpha, mu, n): see the module docstring for how uncertain this
        # parameter order is. a = alpha (Lorentzian power), b = mu (tail
        # strength), m = n (Gaussian-conv code, same convention as DS/A).
        out.update(a=ps[0] if ps else 1.0, b=ps[1] if len(ps) > 1 else 20.0,
                   m=ps[2] if len(ps) > 2 else 0.0)
    return out


def is_exact(shape) -> bool:
    """True for shapes that are exact rather than reconstructed."""
    ps = parse_shape(shape)
    return ps["kind"] in ("GL", "SGL") and not ps["tail"]


def _np():
    import numpy
    return numpy


def gauss_conv(x, y, gfwhm):
    """``y`` convolved with a Gaussian of FWHM ``gfwhm`` (same units as
    ``x``, a uniform grid); edges are extended flat."""
    np = _np()
    if not gfwhm > 0 or len(x) < 3:
        return y
    dx = abs(x[1] - x[0])
    sig = gfwhm / 2.3548200450309493
    n = int(min(200, max(1, round(4 * sig / dx))))
    k = np.exp(-0.5 * (np.arange(-n, n + 1) * dx / sig) ** 2)
    k /= k.sum()
    pad = np.concatenate([np.full(n, y[0]), y, np.full(n, y[-1])])
    return np.convolve(pad, k, mode="valid")


def _half_width_term(p):
    """``sqrt(2**(1/p) - 1)``: how far (in units of the shared Lorentzian
    width ``F``) ``1/(1+4t^2)**p`` must go to reach half its maximum. ``1``
    at ``p = 1``, so a symmetric shape's ``F`` below is exactly ``fwhm``."""
    if p <= 0:
        return 1.0
    return math.sqrt(max(1e-12, 2.0 ** (1.0 / p) - 1.0))


def _shared_width(fwhm, a, b):
    """The one Lorentzian width shared by both sides of an ``LA``/``LF``
    shape, chosen so the two sides' own half-max distances add up to the
    file's stated ``fwhm`` (KherveFitting's ``LA`` formula; see the module
    docstring). Reduces to ``fwhm`` only for an unmodified Lorentzian
    (``a == b == 1``); a symmetric but non-unity pair is rescaled too."""
    denom = _half_width_term(a) + _half_width_term(b)
    return 2.0 * fwhm / denom if denom > 0 else fwhm


def _gl_sgl_values(x, kind, mix, pos, fwhm):
    """The plain symmetric GL(mix) product or SGL(mix) sum, no broadening.
    Shared by the standalone GL/SGL shapes and, as the base term, by the
    Gelius asymmetric shape (``kind == "A"``) below."""
    np = _np()
    t = (x - pos) / fwhm
    lor = 1.0 / (1.0 + 4.0 * t * t)
    m = min(max(mix, 0.0), 100.0) / 100.0
    gau = np.exp(-_LN2_4 * t * t)
    if kind == "GL":
        return (lor ** m) * (gau ** (1.0 - m))
    return m * lor + (1.0 - m) * gau


def _gelius_tail(x, pos, fwhm, a, b):
    """The Gelius asymmetric shape's one-sided tail term,
    ``w(a,b)*[AW(x) - G0(x)]`` on the low-KE (high binding energy) side,
    zero elsewhere (see the module docstring: CasaXPS "Peak Fitting in
    XPS", 2006, p.20)."""
    np = _np()
    t = x - pos
    w = b * (0.7 + 0.3 / (a + 0.01))
    u = 2.0 * math.sqrt(math.log(2.0)) * np.where(t < 0, -t, 0.0)
    aw = np.exp(-(u / (fwhm + a * u)) ** 2)
    g0 = np.exp(-(u / fwhm) ** 2)
    return np.where(t < 0, w * (aw - g0), 0.0)


def _tla_width_scale(alpha, mu):
    """FWHM (in Lorentzian-width units) of the unconvolved CasaXPS ``TLA``
    base shape, found numerically since it has no closed form (mirrors
    KherveFitting's own ``_tla_width_scale``; see the module docstring for
    how uncertain this reconstruction is)."""
    np = _np()
    t = np.linspace(-40.0, 40.0, 8001)
    lor = (1.0 / (1.0 + 4.0 * t * t)) ** alpha
    tail = math.pi / 2.0 - np.arctan(2.0 * t) + math.pi / mu
    y = lor * tail
    above = np.nonzero(y >= float(y.max()) / 2.0)[0]
    if len(above) >= 2:
        return float(t[above[-1]] - t[above[0]])
    return 1.0


def _tla_values(x, pos, fwhm, alpha, mu):
    """The CasaXPS ``TLA`` raw shape (before Gaussian convolution, applied
    afterwards by ``component_curve`` like every other reconstructed shape
    here): a Lorentzian raised to ``alpha``, modulated by an arctangent tail
    factor. See the module docstring -- this shape is substantially less
    certain than the others in this module."""
    np = _np()
    alpha = max(float(alpha), 0.05)
    mu = max(float(mu), 1e-3)
    f_lor = fwhm / _tla_width_scale(alpha, mu)
    u = (x - pos) / f_lor
    lor = (1.0 / (1.0 + 4.0 * u * u)) ** alpha
    tail = math.pi / 2.0 - np.arctan(2.0 * u) + math.pi / mu
    return lor * tail


def _voigt_fwhm_split(fwhm, fraction):
    """``(Gaussian FWHM, Lorentzian FWHM)`` for a total Voigt FWHM and an
    L/G fraction (per cent Lorentzian of the total width), via the analytic
    Olivero-Longbothum inverse -- an exact match to KherveFitting's own
    ``voigt_fwhm_split`` (``Peak_Functions.py``, retrieved 2026-09-27): the
    forward relation ``F = 0.5346*f_l + sqrt(0.2166*f_l**2 + f_g**2)`` is
    linear in the overall scale, so splitting a stated total ``fwhm`` by a
    fraction ``r`` is analytic (``f_g = (1-r)*scale``, ``f_l = r*scale``,
    ``scale = fwhm/k``)."""
    r = min(max(fraction / 100.0, 0.0), 0.999)
    k = 0.5346 * r + math.sqrt(0.2166 * r * r + (1.0 - r) ** 2)
    scale = fwhm / k if k > 0 else fwhm
    return (1.0 - r) * scale, r * scale


def _voigt_values(x, pos, fwhm, fraction):
    """A true Voigt (Gaussian convolved with Lorentzian), split from its
    total FWHM and L/G fraction the same way KherveFitting's own
    ``voigt_simple`` does. Not a CasaXPS shape string -- ``"VOIGT(fraction)"``
    is this module's own encoding, used only by the KherveFitting ``.kfit``
    reader (CasaXPS itself has no true-Voigt shape string; its own
    Voigt-like shapes are the ``GL``/``SGL`` pseudo-Voigt already above).
    Computed as a plain Lorentzian of the split Lorentzian FWHM, Gaussian-
    convolved by the split Gaussian FWHM -- the same convolution
    KherveFitting evaluates analytically via the Faddeeva function
    (``lmfit``'s ``voigt``), not an approximation of a different kind."""
    np = _np()
    f_g, f_l = _voigt_fwhm_split(fwhm, fraction)
    f_l = f_l if f_l > 0 else 1e-6
    t = (x - pos) / f_l
    lor = 1.0 / (1.0 + 4.0 * t * t)
    return gauss_conv(x, lor, f_g)


def _raw_values(x, sp, pos, fwhm):
    """The lineshape before any Gaussian broadening (GL/SGL/VOIGT have their
    own convolution already folded in): the GL product, the SGL sum, the
    true Voigt, the Gelius asymmetric shape, the TLA shape, or the raw
    asymmetric Lorentzian (with its LF finite-tail taper) on grid ``x``.
    Used both for the values a caller asked for and, on a separate wide
    grid, for area normalisation."""
    np = _np()
    if sp["kind"] in ("GL", "SGL"):
        return _gl_sgl_values(x, sp["kind"], sp["mix"], pos, fwhm)
    if sp["kind"] == "VOIGT":
        return _voigt_values(x, pos, fwhm, sp["mix"])
    if sp["kind"] == "DS":
        t = 2.0 * (x - pos) / fwhm
        a = sp["a"]
        return np.cos(np.pi * a / 2.0 + (1.0 - a) * np.arctan(t)) \
            / (1.0 + 4.0 * t * t) ** ((1.0 - a) / 2.0)
    if sp["kind"] == "A":
        base = _gl_sgl_values(x, sp["base"], sp["mix"], pos, fwhm)
        return base + _gelius_tail(x, pos, fwhm, sp["a"], sp["b"])
    if sp["kind"] == "TLA":
        return _tla_values(x, pos, fwhm, sp["a"], sp["b"])
    F = _shared_width(fwhm, sp["a"], sp["b"])
    t = (x - pos) / F
    lor = 1.0 / (1.0 + 4.0 * t * t)
    v = np.where(t < 0, lor ** sp["a"], lor ** sp["b"])
    if sp["w"] > 0:                              # finite tail (LF): the
        r = np.abs((x - pos) / fwhm) / sp["w"]    # taper stays on the
        v = np.where(r < 1, v * (1 - r * r) ** 2, 0.0)  # nominal fwhm
    return v


# How far a component's own area is measured, in FWHM either side of its
# position: independent of the (possibly narrower) CasaXPS fit-region window
# it is drawn on, so a tail cut off by a tight region box is not mistaken for
# missing area and used to inflate the visible peak.
_NORM_HALF_WIDTH = 100.0
_NORM_POINTS = 4001


def component_curve(ke, shape, pos, fwhm, area):
    """The component on the ascending KE grid ``ke`` (numpy array), scaled so
    that its integral over its own full extent — not just over ``ke``, which
    may be a CasaXPS region window narrower than the shape's tail — is
    ``area``. A component whose tail runs past the displayed window is
    therefore not inflated to make up area that simply isn't in the window."""
    np = _np()
    ke = np.asarray(ke, dtype=float)
    sp = parse_shape(shape)
    fwhm = fwhm if fwhm and fwhm > 0 else 1.0
    v = _raw_values(ke, sp, pos, fwhm)
    if sp["kind"] in ("GL", "SGL", "VOIGT"):
        conv = v
    else:
        gw = fwhm * GAUSS_K.get(sp["kind"], 0.0) * (
            (25.0 / sp["m"]) ** GAUSS_P.get(sp["kind"], 1.0)
            if sp["m"] else 0.0)
        conv = gauss_conv(ke, v, gw)
    span = _NORM_HALF_WIDTH * fwhm
    wide = np.linspace(pos - span, pos + span, _NORM_POINTS)
    wstep = wide[1] - wide[0]
    s = float(_raw_values(wide, sp, pos, fwhm).sum()) * wstep
    return conv * (area / s if s > 0 else 0.0)


def shirley(y, avg=1, iters=100):
    """Iterative Shirley background of ``y`` on an ascending-KE slice (the
    low-KE end is the high-binding-energy side, which sits higher). ``avg``
    points are averaged at each end for the end levels."""
    np = _np()
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    k = max(1, min(int(avg), n // 2 or 1))
    lo, hi = float(y[:k].mean()), float(y[-k:].mean())
    b = np.full(n, lo)
    for _ in range(iters):
        cum = np.cumsum(np.maximum(y - b, 0.0))
        tot = cum[-1] if cum[-1] > 0 else 1.0
        nb = lo + (hi - lo) * cum / tot
        done = float(np.abs(nb - b).max()) < 1e-9 * max(1.0, abs(hi - lo))
        b = nb
        if done:
            break
    return b


def linear_bg(y, avg=1):
    np = _np()
    y = np.asarray(y, dtype=float)
    n = len(y)
    k = max(1, min(int(avg), n // 2 or 1))
    return float(y[:k].mean()) + (float(y[-k:].mean()) - float(y[:k].mean())) \
        * np.linspace(0.0, 1.0, n)


def tougaard_u2(x, y, b, c, avg=1):
    """The two-parameter universal Tougaard background of ``y`` on the
    ascending-KE grid ``x``: the level at the high-KE end (mean of ``avg``
    points) plus the inelastic tail of everything above each point,
    ``sum K(T) (y - end) dE`` over ``T = x' - x``, with the cross-section
    ``K(T) = B T / (C + T^2)^2``. CasaXPS stores C with a minus sign (its
    general form is ``B T / ((C - T^2)^2 + D T^2)`` and the two-parameter
    version has D = 0). ``b`` is B (eV^2), ``c`` the positive C (eV^2).
    Checked on real CasaXPS fits (see ``tests/test_casafit.py``)."""
    np = _np()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    k = max(1, min(int(avg), n // 2 or 1))
    base = float(y[-k:].mean())
    dx = float(np.abs(np.diff(x)).mean())
    yb = y - base
    bg = np.empty(n)
    for i in range(n):
        t = x[i + 1:] - x[i]
        bg[i] = float(np.sum(b * t / ((c + t * t) ** 2) * yb[i + 1:]))
    return base + bg * dx


def tougaard_3param(x, y, b, c, d, avg=1):
    """The three-parameter universal Tougaard background of ``y`` on the
    ascending-KE grid ``x``: same construction as :func:`tougaard_u2` (the
    level at the high-KE end plus the inelastic tail of everything above each
    point) but with the three-parameter cross section
    ``K(T) = B T / ((C - T^2)^2 + D T^2)`` (Tougaard, *Surf. Interface Anal.*
    25, 137 (1997); CasaXPS's own "Peak Fitting in XPS" names this the
    ``U 4 Tougaard`` cross section, with ``U Poly``/``U Si``/``U SiO2``/
    ``U Ge``/``U Al`` as its built-in material presets). Unlike
    :func:`tougaard_u2`, CasaXPS stores ``B``, ``C`` and ``D`` here with their
    natural sign (no minus on ``C``). Checked against a real CasaXPS
    ``U Poly Tougaard`` fit (``D:\\Temp\\for claude files\\PET``): the file's
    own ``params[2:5]`` for both its C 1s and O 1s regions are ``396, 551,
    436`` -- an exact match to Tougaard's published Polymers row -- and
    reconstructing background + the file's own components against its own raw
    data with these values gives residuals in the same few-percent range as
    this module's pre-existing ``LA``-shape reconstruction noise, not a
    background-shape mismatch. CasaXPS's region line for this cross-section
    family carries two further numbers ahead of ``B`` (``params[0]``,
    ``params[1]``) that are **not reconstructed here**: CasaXPS's docs
    describe both a per-cross-section T0 energy-loss cutoff and, separately,
    generic per-region St/End Offset percentages, either of which could
    explain them, and treating ``params[1]`` as a literal T0 cutoff on the
    real file above collapses the entire C 1s background to flat (19.6 eV
    exceeds the whole 15 eV fit window) -- evidence against that reading
    without enough real files to confirm the right one, so, as with
    :func:`tougaard_u2`'s own unused slots, they are left alone rather than
    guessed."""
    np = _np()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    k = max(1, min(int(avg), n // 2 or 1))
    base = float(y[-k:].mean())
    dx = float(np.abs(np.diff(x)).mean())
    yb = y - base
    bg = np.empty(n)
    for i in range(n):
        t = x[i + 1:] - x[i]
        bg[i] = float(np.sum(b * t / ((c - t * t) ** 2 + d * t * t) * yb[i + 1:]))
    return base + bg * dx


def tougaard_w(x, y, b, c):
    """The W Tougaard background of ``y`` on the ascending-KE grid ``x``:
    reconstructed from KherveFitting's own
    ``calculate_w_tougaard_background`` (github.com/KherveFitting/
    KherveFitting, ``libraries/Peak_Functions.py``, read directly 2026-09-27)
    -- a genuinely different cross section from both :func:`tougaard_u2` and
    :func:`tougaard_3param`, not a renamed duplicate: ``K(T) = B' T /
    (C + T^2)`` (no ``D`` term, and ``C`` is not squared), where
    ``B' = B * y[0] / y[-1]`` -- an endpoint-intensity-ratio adjustment to
    ``B`` KherveFitting's own comment calls "Adjust B based on endpoint
    intensities" that no other Tougaard variant in this module has. Ported
    faithfully, including that KherveFitting's own version does **not**
    subtract and restore a flat baseline the way :func:`tougaard_u2`/
    :func:`tougaard_3param` do (so no ``avg`` parameter here: there is no
    baseline level to average).

    **Two things are left unconfirmed, same tier as the Gelius/TLA shapes**:
    no real CasaXPS-fitted file using literally ``"W Tougaard"`` as its
    region type is available anywhere in the corpora this module was
    checked against, so this is a reconstruction from a credible secondary
    source only, self-consistency tested, not validated against a real
    residual; and KherveFitting's own ``y[0]``/``y[-1]`` endpoint indices are
    taken as-is with no confirmation of which physical end (high or low
    binding energy) they are meant to be on *this* module's own
    ascending-kinetic-energy convention."""
    np = _np()
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 3:
        return y.copy()
    b_adj = b * (y[0] / y[-1]) if y[-1] else b
    dx = float(np.abs(np.diff(x)).mean())
    bg = np.empty(n)
    for i in range(n):
        t = x[i + 1:] - x[i]
        bg[i] = float(np.sum(b_adj * t / (c + t * t) * y[i + 1:]))
    return bg * dx


_TOUGAARD_U2 = re.compile(r"^u\s*2\s*tougaard")
_TOUGAARD_3P = re.compile(r"^(?:u\s*(?:poly|sio2|si|ge|al|4)\s*)?tougaard\b")
_TOUGAARD_W = re.compile(r"^w\s*tougaard\b")


def background(kind, y, avg=1, x=None, params=()):
    """Background under ``y`` for a CasaXPS type name ('Shirley', 'Linear',
    'None', 'Tougaard', 'U 2 Tougaard', 'U Poly Tougaard', 'U Si Tougaard',
    'U SiO2 Tougaard', 'U Ge Tougaard', 'U Al Tougaard', 'U 4 Tougaard',
    'W Tougaard' ...); None for a type this module cannot reproduce ('E
    Tougaard', a Spline background -- checked against KherveFitting's own
    readable background source too: it has no ``E`` Tougaard function at all
    either, and its own Spline background is anchor-point/interactive, not a
    closed form of the handful of numbers a CasaXPS region line's ``params``
    can carry, so there is nothing to reconstruct it from). ``x`` (ascending
    KE) and ``params`` (the region line's six numbers after the averaging
    width) are needed for every Tougaard variant.

    Plain ``'Tougaard'`` (no ``U ...`` prefix) shares :func:`tougaard_3param`
    with the ``U ...`` family: KherveFitting's own ``calculate_
    tougaard_background`` uses the identical ``B T / ((C - T^2)^2 + D T^2)``
    cross section (confirmed by reading both side by side) with generic
    default constants instead of a named material preset -- a second,
    independent confirmation of that function (Tougaard's own paper was the
    first), though still not a validation against a real CasaXPS file using
    literally ``"Tougaard"`` as its type (none found), so it carries the
    same caveat :func:`tougaard_3param`'s own docstring already states.
    ``'W Tougaard'`` is a distinct cross section (:func:`tougaard_w`, its own
    caveats there); its ``C`` sign convention (which family it follows,
    :func:`tougaard_u2`'s negated storage or :func:`tougaard_3param`'s
    natural one) is unconfirmed, so it is read with the natural sign, the
    more common convention among CasaXPS's Tougaard types."""
    t = str(kind or "").strip().lower()
    if t.startswith("shirley"):
        return shirley(y, avg)
    if _TOUGAARD_U2.match(t):
        if x is None or len(params) < 4 or not params[2]:
            return None
        return tougaard_u2(x, y, params[2], abs(params[3]) or 1643.0, avg)
    if _TOUGAARD_W.match(t):
        if x is None or len(params) < 4 or not params[2] or not params[3]:
            return None
        return tougaard_w(x, y, params[2], params[3])
    if _TOUGAARD_3P.match(t):
        if x is None or len(params) < 5 or not params[2] or not params[3]:
            return None
        return tougaard_3param(x, y, params[2], params[3], params[4], avg)
    if t.startswith("linear"):
        return linear_bg(y, avg)
    if t in ("none", "", "offset"):
        np = _np()
        return np.zeros(len(y))
    return None
