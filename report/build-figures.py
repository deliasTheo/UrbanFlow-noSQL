"""Trace la figure des temps par rapport au local, à partir des fichiers de results/.

Depuis la racine du dépôt (une installation LaTeX est nécessaire pour le texte) :
    python report/build-figures.py
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("pgf")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "report/figures/temps-par-rapport-au-local.pdf"

# Même ordre que les tableaux du rapport, de haut en bas.
E2_REQUESTS = {
    "f1_jfk_pickup_march": "F1 JFK, mars",
    "f1_parkslope_dropoff_semester": "F1 zone 181, semestre",
    "f2_several_zones_semester": "F2 cinq zones, semestre",
    "f2_brooklyn_quarter": "F2 Brooklyn, trimestre",
    "f3_brooklyn_march": "F3 Brooklyn, mars",
    "f4_jfk_midtown": "F4 JFK vers Midtown",
    "f5_brooklyn_march": "F5 Brooklyn, mars",
    "f5_city_across_april": "F5 ville, autour d'avril",
}
E3_MIXES = {"100A": "60 A / 0 B", "70A_30B": "42 A / 18 B", "30A_70B": "18 A / 42 B", "100B": "0 A / 60 B"}

# Le marqueur change aussi : la figure reste lisible imprimée en noir et blanc.
PLACEMENTS = {
    "zone": {"label": "Placement par zone", "color": "#2a78d6", "marker": "o"},
    "month": {"label": "Placement par période", "color": "#eb6834", "marker": "s"},
}
GREY = "#52514e"
LIGHT_GREY = "#d9d8d4"


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def e2_changes():
    """Écart de la médiane au local, en pourcentage, pour chaque requête de E2."""
    times = {name: read_json(f"results/experiments/e2/{name}.json")["requests"] for name in ["local", *PLACEMENTS]}
    return {
        label: {name: 100 * (times[name][key]["median"] / times["local"][key]["median"] - 1) for name in PLACEMENTS}
        for key, label in E2_REQUESTS.items()
    }


def e3_changes():
    """Écart de la durée totale au local, en pourcentage, pour chaque mélange de E3."""
    mixes = {name: read_json(f"results/experiments/e3/{name}.json")["mixes"] for name in ["local", *PLACEMENTS]}
    return {
        label: {name: 100 * (mixes[name][key]["wall_seconds"] / mixes["local"][key]["wall_seconds"] - 1) for name in PLACEMENTS}
        for key, label in E3_MIXES.items()
    }


def signed(value):
    return f"{value:+.0f}".replace("-", "−") + " %"


def draw(axis, changes, title, labelled):
    """Une ligne par requête, avec un trait partant du local pour chaque placement."""
    rows = list(changes)
    for row, label in enumerate(rows):
        # Les deux placements sont décalés : ils restent visibles quand leurs valeurs sont proches.
        for shift, (name, style) in zip((-0.19, 0.19), PLACEMENTS.items()):
            value = changes[label][name]
            axis.plot([0, value], [row + shift, row + shift], color=style["color"], linewidth=1.2, zorder=2)
            axis.scatter(value, row + shift, color=style["color"], marker=style["marker"], s=16, zorder=3)
            # Seules certaines valeurs sont écrites : les temps exacts sont dans les tableaux.
            if label in labelled:
                away = 5 if value > 0 else -5
                axis.annotate(signed(value), (value, row + shift), xytext=(away, 0), textcoords="offset points",
                              ha="left" if value > 0 else "right", va="center", fontsize=7.5, color=GREY)
    axis.axvline(0, color=GREY, linewidth=1, zorder=1)
    axis.set_yticks(range(len(rows)), rows)
    axis.set_ylim(len(rows) - 0.5, -0.5)
    axis.set_xlim(-88, 105)
    axis.set_xticks([-50, 0, 50, 100], ["−50 %", "local", "+50 %", "+100 %"])
    axis.set_title(title, loc="left", fontsize=9.5)
    axis.grid(axis="x", color=LIGHT_GREY, linewidth=0.5)
    axis.set_axisbelow(True)
    axis.tick_params(length=0, labelsize=8, colors=GREY)
    for side in axis.spines.values():
        side.set_visible(False)


def main():
    plt.rcParams.update({
        "pgf.texsystem": "pdflatex",
        "pgf.rcfonts": False,
        "pgf.preamble": "\n".join([r"\usepackage[utf8]{inputenc}", r"\usepackage[T1]{fontenc}",
                                   r"\usepackage{lmodern}", r"\usepackage{textcomp}"]),
        "font.family": "serif",
    })
    figure, (left, right) = plt.subplots(1, 2, figsize=(6.7, 2.45), width_ratios=[1, 1])
    draw(left, e2_changes(), "E2 : médiane par requête", {"F3 Brooklyn, mars", "F5 ville, autour d'avril"})
    draw(right, e3_changes(), "E3 : durée totale par mélange", set(E3_MIXES.values()))

    handles = [plt.Line2D([], [], linestyle="", marker=style["marker"], color=style["color"], markersize=6,
                          label=style["label"]) for style in PLACEMENTS.values()]
    figure.legend(handles=handles, loc="lower center", ncols=2, frameon=False, fontsize=8.5)
    figure.tight_layout(rect=(0, 0.08, 1, 1), w_pad=1.5)

    OUTPUT.parent.mkdir(exist_ok=True)
    figure.savefig(OUTPUT)
    print(f"Écrit : {OUTPUT}")


if __name__ == "__main__":
    main()
