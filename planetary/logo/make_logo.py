"""Draw the Thermonaut logo and icon (SVG + PNG).

    python planetary/logo/make_logo.py

Design: a gear (the engine) around a planet whose disc runs from the cold night side (blue) to the hot day side
(orange) across the terminator, crossed by an orbit; the wordmark follows.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Circle, Ellipse, Polygon  # noqa: E402
import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
INK, MUTED = "#13233a", "#5b6475"
COLD, MID, HOT = "#1f4e8c", "#e9eef5", "#eb6834"
THERMAL = LinearSegmentedColormap.from_list("thermal", ["#16365f", COLD, "#7fa7d6", MID, "#f6b26b", HOT, "#c4421c"])


def gear(ax, cx, cy, r_in, r_out, teeth=12, color=INK):
    pts = []
    n = teeth * 4
    for k in range(n):
        a = 2 * np.pi * k / n
        rr = r_out if (k % 4) in (1, 2) else r_in
        pts.append((cx + rr * np.cos(a + np.pi / teeth / 2), cy + rr * np.sin(a + np.pi / teeth / 2)))
    ax.add_patch(Polygon(pts, closed=True, color=color, zorder=1))


def emblem(ax, cx=0.0, cy=0.0, r=1.0):
    gear(ax, cx, cy, 1.02 * r, 1.22 * r)
    ax.add_patch(Circle((cx, cy), 1.0 * r, color="white", zorder=2))
    # planet: diagonal day/night gradient, clipped to the disc
    n = 400
    x = np.linspace(-1, 1, n)
    X, Y = np.meshgrid(x, x)
    t = np.clip(0.5 + 0.9 * (X * 0.8 + Y * 0.6) / 1.4, 0, 1)
    im = ax.imshow(t, cmap=THERMAL, extent=(cx - 0.78 * r, cx + 0.78 * r, cy - 0.78 * r, cy + 0.78 * r), origin="lower",
                   zorder=3, interpolation="bilinear")
    disc = Circle((cx, cy), 0.78 * r, transform=ax.transData)
    im.set_clip_path(disc)
    ax.add_patch(Circle((cx, cy), 0.78 * r, fill=False, ec=INK, lw=1.6, zorder=4))
    # terminator highlight and two craters
    for (dx, dy, rr, c) in ((-0.30, -0.22, 0.10, "#173f72"), (0.32, 0.26, 0.08, "#d9572a"), (0.05, -0.42, 0.06, "#2b5c99")):
        ax.add_patch(Circle((cx + dx * r, cy + dy * r), rr * r, color=c, alpha=0.75, zorder=4))
    # orbit and satellite-habitat
    ax.add_patch(Ellipse((cx, cy), 2.05 * r, 0.62 * r, angle=-22, fill=False, ec=INK, lw=1.6, zorder=5))
    a = np.radians(28)
    ex, ey = 1.025 * r * np.cos(a), 0.31 * r * np.sin(a)
    rot = np.radians(-22)
    hx, hy = cx + ex * np.cos(rot) - ey * np.sin(rot), cy + ex * np.sin(rot) + ey * np.cos(rot)
    ax.add_patch(Circle((hx, hy), 0.075 * r, color=HOT, ec=INK, lw=1.2, zorder=6))


def draw(name, word, sub, square=False):
    if square:
        fig, ax = plt.subplots(figsize=(2.4, 2.4))
        emblem(ax)
        ax.set_xlim(-1.32, 1.32)
        ax.set_ylim(-1.32, 1.32)
    else:
        fig, ax = plt.subplots(figsize=(8.0, 2.2))
        emblem(ax)
        ax.text(1.55, 0.20, word, fontsize=40, fontweight="bold", color=INK, va="center", family="DejaVu Sans")
        ax.text(1.60, -0.58, sub, fontsize=11, color=MUTED, va="center", family="DejaVu Sans")
        ax.set_xlim(-1.32, 8.2)
        ax.set_ylim(-1.32, 1.32)
    ax.set_aspect("equal")
    ax.axis("off")
    for ext in ("svg", "png"):
        fig.savefig(HERE / f"{name}.{ext}", dpi=300, transparent=True, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("wrote", name)


if __name__ == "__main__":
    draw("thermonaut_logo", "Thermonaut", "Planetary building energy engine · an EnergyPlus fork")
    draw("thermonaut_icon", "", "", square=True)
