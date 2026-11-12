"""Figures of the Thermonaut manuscript (reads planetary/paper/data, writes planetary/paper/figures/core_*.png).

    python planetary/paper/build_figures_thermonaut.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import FancyBboxPatch  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
FIG = HERE / "figures"

C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
INK, INK2, MUTED, GRID, AXIS = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
BLUE_RAMP = ["#0d3d7a", "#2a78d6", "#a9c8ef"]  # P0, P1, P2 (one hue, dark -> light)

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.4,
    "legend.frameon": True, "legend.facecolor": "white", "legend.edgecolor": "none", "legend.framealpha": 0.9,
    "legend.fontsize": 7.5, "savefig.dpi": 300, "figure.dpi": 110,
    "axes.titlecolor": INK, "axes.titleweight": "bold", "axes.titlelocation": "left",
})
GEN = dict(color=C[0], lw=1.6, label="generator")
PWF = dict(color=C[1], lw=1.0, ls=(0, (3, 1.5)), label="weather file")
CASES = HERE.parent / "cases"


def save(fig, name):
    fig.savefig(FIG / name, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("wrote", name)


def load(case):
    with open(DATA / f"core_{case}_hourly.csv") as fh:
        rows = list(csv.reader(fh))
    head, vals = rows[0], np.array(rows[1:], float)
    return {h: vals[:, i] for i, h in enumerate(head)}


def window(case, n):
    skip = (n // 48) * 24  # same rule as planetary/cases/roundtrip_check.py
    return skip, n


# --------------------------------------------------------------------------- hook map
def fig_hooks():
    fig, ax = plt.subplots(figsize=(7.4, 4.3))
    ax.set_axis_off()
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 60)

    def box(x, y, w, h, title, body, color, fc="white", tsize=7.2, bsize=5.8):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35,rounding_size=1.0", fc=fc, ec=color, lw=1.3))
        ax.text(x + w / 2, y + h - 1.4, title, ha="center", va="top", fontsize=tsize, weight="bold", color=INK)
        if body:
            ax.text(x + w / 2, y + h - 4.6, body, ha="center", va="top", fontsize=bsize, color=INK2, linespacing=1.3)

    # EnergyPlus engine column (reused code in grey, hook text in orange)
    ax.text(30, 59.3, "EnergyPlus v26.2 engine (reused)", ha="center", va="top", fontsize=7.6, weight="bold", color=INK2)
    steps = [
        ("Input processing", "SimulationManager.cc", "read Site:PlanetaryBody;\nvalidator refuses outdoor-air objects"),
        ("Weather manager", "WeatherManager.cc", "overwrite tomorrow's weather;\nhour-angle rate; cabin pressure"),
        ("Solar and shading", "SolarShading.cc", "daily sun fit, rate·(12−t−EoT);\nisotropic sky, no Perez"),
        ("Outside surface balance", "ConvectionCoefficients.cc", "h = 0 (Moon) / CO2 mixed (Mars);\nall sky LW to sky; ground = regolith"),
        ("Conduction (CTF / CondFD)", "HeatBalFiniteDiffManager.cc", "−270 °C limit; steady k(T) start-up\nprofile + warm-up-aware correction"),
        ("Inside balance, zone air", "HeatBalanceSurfaceManager.cc", "cabin-gas convection at cabin\npressure and body gravity"),
    ]
    y0, hgt, gap = 50.5, 6.9, 1.35
    ys = []
    for i, (t, fn, hook) in enumerate(steps):
        y = y0 - i * (hgt + gap)
        ys.append(y)
        ax.add_patch(FancyBboxPatch((3, y), 54, hgt, boxstyle="round,pad=0.3,rounding_size=0.8", fc="#f6f5f1", ec=AXIS, lw=1.0))
        ax.text(4.2, y + hgt - 1.1, t, ha="left", va="top", fontsize=7.0, weight="bold", color=INK)
        ax.text(4.2, y + 1.3, fn, ha="left", va="bottom", fontsize=5.4, color=MUTED, family="DejaVu Sans Mono")
        ax.text(33.0, y + hgt / 2, hook, ha="left", va="center", fontsize=5.6, color=C[1], linespacing=1.25)
        if i < len(steps) - 1:
            ax.annotate("", (30, y - gap + 0.15), (30, y - 0.15),
                        arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=0.9, mutation_scale=7))
    # loop arrow
    ax.annotate("", (1.6, ys[1] + hgt / 2), (1.6, ys[-1] + hgt / 2),
                arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=0.9, mutation_scale=7, connectionstyle="arc3,rad=-0.0"))
    ax.text(0.4, (ys[1] + ys[-1]) / 2 + hgt / 2, "time-step loop", rotation=90, ha="center", va="center", fontsize=5.6, color=MUTED)

    # planetary module
    box(64, 22.5, 34, 34.5, "PlanetaryBody module (new)",
        "Ephemerides: Mars24; lunar subsolar point\n\nEnvironment generator (whole run period):\n"
        "Moon: vacuum, 2.725 K sky\nMars: delta-Eddington dust two-stream,\nτ(Ls), P(Ls), sky IR, air surrogate, wind\n\n"
        "Regolith column (Hayne 2017 / thermal\ninertia) in periodic equilibrium\n\n"
        "Gas properties: cabin N2/O2, Mars CO2\nPhysical mixed convection (g, p, gas)", C[1], bsize=5.7)
    box(64, 3.5, 34, 15.5, "Earth (no Site:PlanetaryBody)",
        "every hook is gated on planet.active or\nreplaces a literal by a variable with the\nsame Earth value → results bit-for-bit\nidentical to v26.2.0 (14 example files)",
        C[0], bsize=5.7)
    for y in ys:
        ax.annotate("", (57.6, y + hgt / 2), (63.4, 39.5),
                    arrowprops=dict(arrowstyle="-|>", color=C[1], lw=0.7, mutation_scale=6, alpha=0.75,
                                    shrinkA=0, shrinkB=1))
    save(fig, "core_fig1_hooks.png")


# --------------------------------------------------------------------------- audit
def fig_audit():
    facts = json.loads((DATA / "core_facts.json").read_text(encoding="utf-8-sig"))
    areas = facts["audit"]["areas"][::-1]
    labels = [a["label"] for a in areas]
    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    left = np.zeros(len(areas))
    names = {"P0": "P0: first habitat run", "P1": "P1: windows, HVAC, plant, PV", "P2": "P2: fence off"}
    for k, col in zip(("P0", "P1", "P2"), BLUE_RAMP):
        v = np.array([a[k] for a in areas], float)
        ax.barh(labels, v, left=left, color=col, edgecolor="white", linewidth=1.6, height=0.62, label=names[k])
        for i, (l0, vi) in enumerate(zip(left, v)):
            if vi >= 4:
                ax.text(l0 + vi / 2, i, f"{vi:.0f}", ha="center", va="center", fontsize=6.6,
                        color="white" if k != "P2" else INK)
        left += v
    for i, tot in enumerate(left):
        ax.text(tot + 0.8, i, f"{tot:.0f}", va="center", fontsize=7, color=INK2)
    ax.set_xlabel("Findings (each with file and line in EnergyPlus v26.2.0)")
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, max(left) * 1.12)
    ax.legend(loc="lower center", bbox_to_anchor=(0.45, 1.0), ncol=3, fontsize=6.8)
    ax.tick_params(axis="y", labelsize=7.2, colors=INK2, length=0)
    save(fig, "core_fig2_audit.png")


# --------------------------------------------------------------------------- environment
def fig_environment():
    mo, ma = load("moon_equator"), load("mars_jezero")
    fig, axs = plt.subplots(3, 2, figsize=(7.4, 5.6), sharex="col")
    tm = mo["hour"] / 24
    sl = slice(16 * 24, 19 * 24)  # three Earth days on Mars
    ta = ma["hour"][sl] / 24
    # (a, b) solar altitude with JPL Horizons
    for ax, t, d, s_, step in ((axs[0, 0], tm, mo, slice(None), 24), (axs[0, 1], ta, ma, sl, 1)):
        ax.plot(t, d["alt"][s_], color=C[0], lw=1.4, label="Thermonaut")
        ax.plot(t[::step], d["hz_alt"][s_][::step], ls="none", marker="o", ms=2.6, color=C[1], label="JPL Horizons")
        ax.axhline(0, color=AXIS, lw=0.8)
    axs[0, 0].set_ylabel("Solar altitude (°)")
    axs[0, 0].set_title("(a) Moon, equator: solar altitude")
    axs[0, 1].set_title("(b) Mars, Jezero: solar altitude")
    axs[0, 0].legend(loc="lower right", fontsize=6.8)
    # (c, d) irradiance
    axs[1, 0].plot(tm, mo["beam"], color=C[0], lw=1.4, label="direct normal")
    axs[1, 0].set_ylabel("Irradiance (W/m²)")
    axs[1, 0].set_title("(c) Direct normal irradiance (no diffuse)")
    axs[1, 0].set_ylim(-60, 1950)
    axs[1, 1].plot(ta, ma["beam"][sl], color=C[0], lw=1.4, label="direct normal")
    axs[1, 1].plot(ta, ma["dif"][sl], color=C[2], lw=1.4, label="diffuse horizontal")
    axs[1, 1].set_title("(d) Direct normal and diffuse irradiance")
    axs[1, 1].set_ylim(-10, 560)
    axs[1, 1].legend(loc="upper center", ncol=2, fontsize=6.4)
    # (e, f) regolith and sky temperatures; Diviner equatorial noon and pre-dawn range on the Moon
    axs[2, 0].axhspan(385 - 273.15, 390 - 273.15, color="#e8e5da", lw=0, zorder=0)
    axs[2, 0].axhspan(92 - 273.15, 98 - 273.15, color="#e8e5da", lw=0, zorder=0)
    axs[2, 0].plot(tm, mo["Tg"], color=C[0], lw=1.4, label="regolith surface")
    axs[2, 0].text(30.5, 390 - 273.15 + 4, "Diviner noon", fontsize=6.3, color=INK2, ha="center", va="bottom")
    axs[2, 0].text(30.5, 92 - 273.15 - 4, "Diviner pre-dawn", fontsize=6.3, color=INK2, ha="center", va="top")
    axs[2, 0].set_ylim(-205, 140)
    axs[2, 0].set_ylabel("Temperature (°C)")
    axs[2, 0].set_title("(e) Regolith surface temperature")
    axs[2, 1].plot(ta, ma["Tg"][sl], color=C[0], lw=1.4, label="regolith surface")
    axs[2, 1].plot(ta, ma["Tsky"][sl], color=C[2], lw=1.4, label="effective sky")
    axs[2, 1].set_title("(f) Regolith surface and sky temperature")
    axs[2, 1].set_ylim(-165, 5)
    axs[2, 1].legend(loc="lower center", ncol=2, fontsize=6.4)
    axs[2, 0].set_xlabel("Elapsed time (Earth days)")
    axs[2, 1].set_xlabel("Elapsed time (Earth days)")
    fig.tight_layout(h_pad=0.8)
    save(fig, "core_fig3_environment.png")


# --------------------------------------------------------------------------- habitat response
def fig_response():
    mo, ma = load("moon_equator"), load("mars_jezero")
    S = json.loads((DATA / "core_summary.json").read_text(encoding="utf-8-sig"))
    fig, axs = plt.subplots(3, 2, figsize=(7.4, 5.8), sharex="col")
    for j, (d, case, title) in enumerate(((mo, "moon_equator", "Moon, equator"), (ma, "mars_jezero", "Mars, Jezero"))):
        t = d["hour"] / 24
        a, b = window(case, len(t))
        r = S[case]["round_trip"]
        for i, (k, lab, sc) in enumerate((("Qc", "Sensible cooling (kW)", 1e-3), ("top", "Top facet outer face (°C)", 1),
                                          ("tin", "Top facet inner face (°C)", 1))):
            ax = axs[i, j]
            ax.axvspan(t[a], t[b - 1], color="#f1efe8", lw=0, zorder=0)
            ax.plot(t, d[k] * sc, **GEN)
            ax.plot(t, d[f"pwf_{k}"] * sc, **PWF)
            ax.set_ylabel(lab)
        axs[0, j].set_title(f"({'ab'[j]}) {title}: sensible cooling")
        axs[1, j].set_title(f"({'cd'[j]}) Outer face of the top facet")
        axs[2, j].set_title(f"({'ef'[j]}) Inner face of the top facet")
        axs[0, j].text(t[a] + 0.4, axs[0, j].get_ylim()[1], "comparison window" + chr(10) + f"{r['cooling_gen_kWh']:.1f} vs "
                       f"{r['cooling_pwf_kWh']:.1f} kWh ({r['cooling_diff_pct']:+.2f} %)", fontsize=6.3, color=INK2, va="top")
        axs[2, j].set_xlabel("Elapsed time (Earth days)")
    for i, (k, sc, minspan) in ((0, ("Qc", 1e-3, 0.5)), (2, ("tin", 1, 1.0))):
        for j, d in enumerate((mo, ma)):
            v = np.concatenate([d[k], d[f"pwf_{k}"]]) * sc
            lo, hi = float(np.nanmin(v)), float(np.nanmax(v))
            span = max(hi - lo, minspan)
            axs[i, j].set_ylim(lo - 0.25 * span, hi + (0.9 if i == 0 else 0.3) * span)
    for j in range(2):
        for txt in list(axs[0, j].texts):
            txt.set_y(axs[0, j].get_ylim()[1])
    axs[1, 0].set_ylim(top=210)
    axs[1, 0].legend(loc="upper left", ncol=2, fontsize=6.8)
    fig.tight_layout(h_pad=0.8)
    save(fig, "core_fig4_response.png")


def idf_surfaces(path):
    """(name, type, outside boundary, vertices) of every BuildingSurface:Detailed in a one-object-per-line IDF."""
    out = []
    for line in path.read_text().splitlines():
        if not line.startswith("BuildingSurface:Detailed,"):
            continue
        f = line.strip().rstrip(";").split(",")
        n = int(f[11])
        xyz = np.array([float(v) for v in f[12:12 + 3 * n]]).reshape(n, 3)
        out.append((f[1], f[2], f[5], xyz))
    return out


def plot_geometry(ax, surfaces, title, elev, azim):
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    colour = {"Wall": "#c9d9ef", "Roof": "#a9c8ef", "Floor": "#d8d5c8", "Ceiling": "#a9c8ef"}
    for name, typ, bc, xyz in surfaces:
        pc = Poly3DCollection([xyz], facecolor=colour.get(typ, "#c9d9ef"), edgecolor="#52514e", linewidths=0.4, alpha=0.95)
        ax.add_collection3d(pc)
    allv = np.vstack([v for *_, v in surfaces])
    lo, hi = allv.min(axis=0), allv.max(axis=0)
    c, r = (lo + hi) / 2, (hi - lo).max() / 2
    ax.set_xlim(c[0] - r, c[0] + r)
    ax.set_ylim(c[1] - r, c[1] + r)
    ax.set_zlim(c[2] - r, c[2] + r)
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()
    ax.set_title(title, loc="left")


def fig_habitats():
    """Geometry of the two verification habitats (from the input files) and the NASA-informed habitat's response."""
    h = load("lunar_habitat")
    fig = plt.figure(figsize=(7.4, 6.0))
    ax1 = fig.add_subplot(2, 2, 1, projection="3d")
    ax2 = fig.add_subplot(2, 2, 2, projection="3d")
    plot_geometry(ax1, idf_surfaces(CASES / "moon_equator" / "moon_equator.idf"), "(a) Regolith-shielded module", 24, -60)
    plot_geometry(ax2, idf_surfaces(CASES / "lunar_habitat" / "lunar_habitat.idf"), "(b) NASA-informed lunar habitat", 22, -58)
    ax1.text2D(0.5, 0.95, "r 3 m, L 10 m, 1 m regolith over MLI;" + chr(10) + "bottom facets rest on the regolith",
               transform=ax1.transAxes, ha="center", va="top", fontsize=6.3, color=INK2)
    ax2.text2D(0.5, 0.95, "D 6.5 m, H 5.25 m, 174 m³, on legs;" + chr(10) + "beta cloth / MLI / aluminium",
               transform=ax2.transAxes, ha="center", va="top", fontsize=6.3, color=INK2)
    t = h["hour"] / 24
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.plot(t, h["Qc"] / 1000, color=C[0], lw=1.4, label="sensible")
    ax3.plot(t, h["Ql"] / 1000, color=C[2], lw=1.4, label="latent")
    ax3.set_ylabel("Cooling load (kW)")
    ax3.set_xlabel("Elapsed time (Earth days)")
    ax3.set_title("(c) Habitat (b): sensible and latent cooling")
    ax3.set_ylim(0, 9.8)
    ax3.legend(fontsize=6.4, ncol=2, loc="upper left", frameon=True, framealpha=0.95)
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.plot(t, h["To_s"], color=C[0], lw=1.4, label="south wall")
    ax4.plot(t, h["To_r"], color=C[3], lw=1.4, label="roof")
    ax4.plot(t, h["To_f"], color=C[2], lw=1.4, label="floor")
    ax4.set_ylabel("Outer face (°C)")
    ax4.set_xlabel("Elapsed time (Earth days)")
    ax4.set_title("(d) Habitat (b): outer-face temperatures")
    ax4.set_ylim(-170, 230)
    ax4.legend(fontsize=6.4, loc="upper left", ncol=3, frameon=True, framealpha=0.95)
    fig.tight_layout(h_pad=1.0)
    save(fig, "core_fig5_habitats.png")


def fig_startup():
    """Start-up of a regolith-covered wall (lunar regolith-module shell), computed with the equations of the engine:
    steady k-constant profile, the implicit node-network response g to a unit inside step over the warm-up period, and
    the states produced by the default start, the full correction (M2c) and the warm-up-aware correction (M2d)."""
    # shell of the lunar regolith module, outside -> inside (moon_equator.idf): regolith 1 m, beta cloth 1 mm,
    # MLI (R 15 m2K/W, no mass), interior panel with the aluminium heat capacity lumped (10 mm)
    layers = [("regolith", 1.0, 0.0034, 1800.0 * 205.107, 60), ("beta cloth", 0.001, 0.15, 1400.0 * 900.0, 2),
              ("MLI", None, 15.0, 0.0, 1), ("panel", 0.01, 0.2, 2017.92 * 1200.0, 4)]
    x, G, Cn, Rcum = [0.0], [], [0.0], [0.0]
    for name, th, k, rc, n in layers:
        for _ in range(n):
            if th is None:                    # no-mass layer: one resistance, negligible capacity
                g, c, dx = 1.0 / k, 1e-5, 0.0
            else:
                dx = th / n
                g, c = k / dx, rc * dx
            G.append(g)
            Cn[-1] += 0.5 * c
            Cn.append(0.5 * c)
            Rcum.append(Rcum[-1] + 1.0 / g)
            x.append(x[-1] + dx)
    x, G, Cn, R = np.array(x), np.array(G), np.array(Cn), np.array(Rcum)
    depth = x[-1] - x                          # distance from the inside face
    To, Tin0, Tin = -25.0, 23.0, 31.2          # mean outer face; initial and real inside-face temperature (Moon case)
    p_old = To + (Tin0 - To) * R / R[-1]
    p_new = To + (Tin - To) * R / R[-1]
    # unit step at the inside face, outer node fixed, implicit Euler hourly over 6 warm-up days
    N = len(x)
    g = np.zeros(N)
    g[-1] = 1.0
    dt, steps = 3600.0, 6 * 24
    A = np.zeros((N - 2, N - 2))
    for i in range(1, N - 1):
        A[i - 1, i - 1] = Cn[i] / dt + G[i - 1] + G[i]
        if i > 1:
            A[i - 1, i - 2] = -G[i - 1]
        if i < N - 2:
            A[i - 1, i] = -G[i]
    for _ in range(steps):
        b = Cn[1:-1] / dt * g[1:-1]
        b[-1] += G[N - 2] * g[-1]
        g[1:-1] = np.linalg.solve(A, b)
    d = p_new - p_old
    after_warmup = p_old + d * g
    states = [("EnergyPlus default (23 °C)", np.full(N, Tin0), MUTED, (0, (1, 1.5))),
              ("steady profile, initial inside T", p_old, C[0], (0, (4, 2))),
              ("after warm-up", after_warmup, C[3], "-"),
              ("full correction (M2c)", after_warmup + d, C[7], "-"),
              ("warm-up-aware correction (M2d)", after_warmup + d * (1 - g), C[2], "-")]
    fig, axs = plt.subplots(1, 2, figsize=(7.4, 2.9))
    ax = axs[0]
    for lab, T, c, ls in states:
        ax.plot(depth * 100, T, color=c, ls=ls, lw=1.5, label=lab)
    ax.set_xscale("symlog", linthresh=1.0)
    ax.set_xlim(0, 102)
    ax.set_xlabel("Distance from the inside face (cm)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("(a) Profiles through the shell")
    ax.legend(fontsize=6.2, loc="lower left")
    ax = axs[1]
    for lab, T, c, ls in states[1:]:
        ax.plot(depth * 100, T - p_new, color=c, ls=ls, lw=1.5)
    ax.axhline(0, color=INK2, lw=0.8)
    ax.set_xscale("symlog", linthresh=1.0)
    ax.set_xlim(0, 102)
    ax.set_xlabel("Distance from the inside face (cm)")
    ax.set_ylabel("Departure from the target profile (K)")
    ax.set_title("(b) Departure from the steady target")
    for a in axs:
        a.axvline(1.0, color=MUTED, lw=0.8, ls=":")
        a.text(1.08, 0.5, "MLI", transform=a.get_xaxis_transform(), fontsize=6.5, color=INK2, rotation=90, va="center")
    axs[1].text(0.25, -3.6, "panel", fontsize=6.5, color=INK2, ha="center")
    axs[1].text(40, 2.0, "regolith", fontsize=6.5, color=INK2, ha="center")
    fig.tight_layout()
    save(fig, "core_fig6_startup.png")


if __name__ == "__main__":
    fig_startup()
    fig_habitats()
    fig_hooks()
    fig_audit()
    fig_environment()
    fig_response()
