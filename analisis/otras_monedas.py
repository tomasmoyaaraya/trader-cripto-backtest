"""Sistema vs comprar y mantener cada moneda / canasta, mismas 36 ventanas de 3 años.

Requiere correr antes analisis/ventanas_3_anos.py (lee resultados/ventanas_3_anos.csv)."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)
import pandas as pd
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

precios = {}
for f in Path("datos_historicos").glob("*_4h.csv"):
    d = pd.read_csv(f); d["fecha"] = pd.to_datetime(d.ts, unit="ms", utc=True)
    precios[f.stem.replace("_4h", "").replace("-", "/")] = d.set_index("fecha")["close"]
P = pd.DataFrame(precios).sort_index()

sistema = pd.read_csv(BASE / "resultados" / "ventanas_3_anos.csv", dtype={"Inicio": str}).set_index("Inicio")["Sistema %"].to_dict()

filas, por_moneda = [], {}
for s in pd.date_range("2020-10-01", "2023-09-01", freq="MS", tz="UTC"):
    e = s + pd.DateOffset(years=3)
    w = P[(P.index >= s) & (P.index < e)]
    disp = [c for c in w.columns if w[c].first_valid_index() is not None and w[c].first_valid_index() <= s + pd.Timedelta(days=2)]
    ret = {c: w[c].dropna().iloc[-1] / w[c].dropna().iloc[0] - 1 for c in disp}
    for c, r in ret.items(): por_moneda.setdefault(c, []).append(r * 100)
    # canasta: $1000 repartidos en partes iguales al inicio, sin rebalancear
    canasta = sum((w[c] / w[c].dropna().iloc[0]) for c in disp) / len(disp)
    canasta = canasta.dropna()
    alts = {c: r for c, r in ret.items() if c != "BTC/USDT"}
    k = s.strftime("%Y-%m")
    filas.append({"Inicio": k, "Sistema %": sistema[k], "BTC %": round(ret["BTC/USDT"] * 100, 1),
                  "Canasta %": round((canasta.iloc[-1] - 1) * 100, 1),
                  "Canasta DD %": round((canasta / canasta.cummax() - 1).min() * 100, 1),
                  "Canasta peor $": round(canasta.min() * 1000),
                  "Altcoin mediana %": round(pd.Series(alts).median() * 100, 1),
                  "Altcoins que le ganan al sistema": f"{sum(r * 100 > sistema[k] for r in alts.values())}/{len(alts)}",
                  "Altcoins en pérdida": sum(r < 0 for r in alts.values())})
t = pd.DataFrame(filas)
pd.set_option("display.width", 250)
print(t.to_string(index=False))
print()
print("Sistema gana a la canasta:", (t["Sistema %"] > t["Canasta %"]).sum(), "de", len(t))
print("Sistema gana a la altcoin mediana:", (t["Sistema %"] > t["Altcoin mediana %"]).sum(), "de", len(t))
print("Medianas -> Sistema", t["Sistema %"].median(), "| BTC", t["BTC %"].median(), "| Canasta", t["Canasta %"].median(),
      "| Altcoin mediana", t["Altcoin mediana %"].median())
print("Peor canasta:", t["Canasta %"].min(), "| peor $ en el camino canasta:", t["Canasta peor $"].min())
print()
m = pd.DataFrame({c: {"Mediana 3 años %": round(pd.Series(v).median()), "Peor %": round(min(v)), "Mejor %": round(max(v)),
                      "Ventanas": len(v), "Veces en pérdida": sum(x < 0 for x in v),
                      "Veces que le gana al sistema": ""} for c, v in por_moneda.items()}).T
# veces que cada moneda le gana al sistema
for c in m.index:
    cnt = 0; tot = 0
    for s in pd.date_range("2020-10-01", "2023-09-01", freq="MS", tz="UTC"):
        e = s + pd.DateOffset(years=3); w = P[c][(P.index >= s) & (P.index < e)].dropna()
        if len(w) and w.index[0] <= s + pd.Timedelta(days=2):
            tot += 1; cnt += (w.iloc[-1] / w.iloc[0] - 1) * 100 > sistema[s.strftime("%Y-%m")]
    m.loc[c, "Veces que le gana al sistema"] = f"{cnt}/{tot}"
print(m.sort_values("Mediana 3 años %", ascending=False).to_string())

fig, ax = plt.subplots(figsize=(14, 6.5))
x = range(len(t))
ax.plot(x, t["BTC %"], color="#999", lw=1.8, marker="o", ms=3, label="Mantener BTC")
ax.plot(x, t["Canasta %"], color="#2a7de1", lw=1.8, marker="o", ms=3, label="Mantener las 15 monedas (partes iguales)")
ax.plot(x, t["Altcoin mediana %"], color="#1e9e5a", lw=1.8, marker="o", ms=3, label="Altcoin típica (mediana)")
ax.plot(x, t["Sistema %"], color="#d9531e", lw=2.6, marker="o", ms=3, label="Sistema (riesgo 1%)")
ax.axhline(0, color="#333", lw=0.8)
ax.set_xticks(list(x)); ax.set_xticklabels(t["Inicio"], rotation=70, fontsize=8)
ax.set_ylabel("Retorno a 3 años (%)"); ax.grid(alpha=0.3); ax.legend(loc="upper left")
ax.set_title("Si hubieras invertido $1.000 en este mes y esperado 3 años", fontsize=14, weight="bold")
fig.text(0.5, 0.01, "Datos históricos de Binance. Las 15 monedas son las grandes de hoy (sesgo de supervivencia: no incluye las que colapsaron). No es asesoría financiera.",
         ha="center", fontsize=9, color="#666")
fig.tight_layout(rect=(0, 0.03, 1, 1))
out = str(BASE / "resultados" / "otras_monedas_3_anos.jpg")
fig.savefig(out, dpi=120, pil_kwargs={"quality": 92}); print(out)
