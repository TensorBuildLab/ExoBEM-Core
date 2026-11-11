"""ExoBEM-Core M2c patch set: Mars downwelling long-wave recalibrated (kept identical in both codes).

Run from the repository root:  python planetary/tools/apply_hooks_m2c.py   (idempotent)

The Mars sky emission is L = eps_sky(tau) sigma T_air^4 + f_re <G_toa,h - G_h>_sol with
eps_sky = min(e0 + e1 tau, 0.6).  The previous values (e0 0.08, e1 0.125, f_re 0.45) made a global dust storm
warm the sol-mean air temperature by about 18 K, whereas Curiosity saw it fall by about 4 K in 2018
(Viudez-Moreiras et al. 2019; Guzewich et al. 2019).  ExoBEM's studies/calibrate_mars_storm_ir.py refitted the
three parameters to the MEDA/TIRS clear-season mean (~30 W/m2) and that storm response: e0 0.12, e1 0.10,
f_re 0.20 give 30.4 W/m2 and -4.6 K.  Earth runs are unaffected (Mars-only code path).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
C = ROOT / "src" / "EnergyPlus" / "PlanetaryBody.cc"


def edit(path, old, new, marker):
    p = Path(path)
    s = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in s
    s = s.replace("\r\n", "\n")
    if marker in s:
        return
    assert s.count(old) == 1, (p.name, s.count(old), old[:120])
    s = s.replace(old, new)
    if crlf:
        s = s.replace("\n", "\r\n")
    p.write_bytes(s.encode("utf-8"))


edit(C,
     "            constexpr Real64 kappa = 0.6, lagH = 0.5, e0 = 0.08, e1 = 0.125, fRe = 0.45;\n",
     "            // sky emissivity e0 + e1*tau (cap 0.6) and dust re-emission fRe, calibrated to the MEDA/TIRS clear-season\n"
     "            // mean (~30 W/m2) and the 2018 storm (sol-mean air -4 K): ExoBEM studies/calibrate_mars_storm_ir.py\n"
     "            constexpr Real64 kappa = 0.6, lagH = 0.5, e0 = 0.12, e1 = 0.10, fRe = 0.20;\n",
     "e0 = 0.12, e1 = 0.10, fRe = 0.20")
print("M2c applied")
