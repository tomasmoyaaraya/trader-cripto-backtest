"""Gráfico compacto para docs/informe.pdf (sistema vs BTC, 36 ventanas de 3 años).

Requiere correr antes analisis/ventanas_3_anos.py (lee resultados/ventanas_3_anos.csv).
"""
from pathlib import Path

import matplotlib
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
t = pd.read_csv(BASE / "resultados" / "ventanas_3_anos.csv", dtype={"Inicio": str})

plt.rcParams.update({"font.size": 11, "font.family": "DejaVu Sans"})
fig, ax = plt.subplots(figsize=(6.4, 4.3))
x = range(len(t))
ax.bar([i - 0.2 for i in x], t["BTC %"], width=0.4, color="#9a9a9a", label="Mantener BTC")
ax.bar([i + 0.2 for i in x], t["Sistema %"], width=0.4, color="#d9531e", label="Sistema (riesgo 1%)")
ax.axhline(0, color="#333", lw=0.8)

# Una etiqueta por semestre para que se lea
marcas = [i for i, m in enumerate(t["Inicio"]) if m[-2:] in ("01", "07") or i == 0]
ax.set_xticks(marcas)
ax.set_xticklabels([t["Inicio"][i] for i in marcas], rotation=45, ha="right", fontsize=10)
ax.set_xlabel("Mes de inicio de la inversión", fontsize=10.5)
ax.set_ylabel("Retorno a 3 años (%)", fontsize=10.5)
ax.grid(axis="y", alpha=0.3)
ax.spines[["top", "right"]].set_visible(False)
# Fondo en los meses de inicio donde el sistema le gana a BTC
for i in x:
    if t["Sistema %"][i] > t["BTC %"][i]:
        ax.axvspan(i - 0.5, i + 0.5, color="#d9531e", alpha=0.12, lw=0)
from matplotlib.patches import Patch  # noqa: E402
handles, labels = ax.get_legend_handles_labels()
handles.append(Patch(color="#d9531e", alpha=0.12))
labels.append("Meses en que gana el sistema")
ax.legend(handles, labels, loc="upper left", frameon=False, fontsize=10)

fig.tight_layout()
out = BASE / "docs" / "img" / "informe_ventanas.png"
fig.savefig(out, dpi=200)
print(out)
