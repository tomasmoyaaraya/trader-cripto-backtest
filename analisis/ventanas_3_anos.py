"""Sistema vs comprar y mantener BTC para cada mes de inicio (oct-2020 a sep-2023), plazo 3 años."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)
import pandas as pd, yaml
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import backtest as bt
from cartera import Cartera
from datos import crear_exchange

cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
ex = crear_exchange("binance"); paso = ex.parse_timeframe("4h") * 1000
ini = pd.Timestamp("2020-09-29", tz="UTC").as_unit("ms")
fin = pd.Timestamp.now(tz="UTC").as_unit("ms")
velas, sen, btc = bt.cargar(cfg, ex, int(ini.timestamp() * 1000) - bt.CALENTAMIENTO * paso, ini, fin, verbose=False)
todos = sorted({T for v in velas.values() for T in v})

def dd(s): return (s / s.cummax() - 1).min()

filas = []
for s in pd.date_range("2020-10-01", "2023-09-01", freq="MS", tz="UTC"):
    e = s + pd.DateOffset(years=3)
    cart = Cartera(cfg)
    for T in (T for T in todos if s <= T < e):
        cart.procesar(T, velas, [x[T] for x in sen.values() if T in x])
    curva = pd.Series(dict(cart.curva))
    b = btc[(btc.index >= s) & (btc.index < e)]
    peor_btc = (b / b.iloc[0]).min()  # peor momento vs lo invertido
    filas.append({"Inicio": s.strftime("%Y-%m"),
                  "Sistema %": round((curva.iloc[-1] / 1000 - 1) * 100, 1),
                  "Sistema DD %": round(dd(curva) * 100, 1),
                  "Sistema peor $": round(curva.min()),
                  "BTC %": round((b.iloc[-1] / b.iloc[0] - 1) * 100, 1),
                  "BTC DD %": round(dd(b) * 100, 1),
                  "BTC peor $": round(peor_btc * 1000)})
t = pd.DataFrame(filas)
t["Gana"] = t.apply(lambda r: "Sistema" if r["Sistema %"] > r["BTC %"] else "BTC", axis=1)
pd.set_option("display.width", 200)
print(t.to_string(index=False))
t.to_csv(BASE / "resultados" / "ventanas_3_anos.csv", index=False)
print()
print("Ventanas:", len(t), "| BTC gana:", (t.Gana == "BTC").sum(), "| Sistema gana:", (t.Gana == "Sistema").sum())
print("Retorno mediano  -> Sistema:", t["Sistema %"].median(), "| BTC:", t["BTC %"].median())
print("Peor retorno     -> Sistema:", t["Sistema %"].min(), "| BTC:", t["BTC %"].min())
print("Peor $ en el camino (de 1000) -> Sistema:", t["Sistema peor $"].min(), "| BTC:", t["BTC peor $"].min())
print("Ventanas con BTC bajo $600 en algún momento:", (t["BTC peor $"] < 600).sum())

fig, ax = plt.subplots(figsize=(14, 6.5))
x = range(len(t))
ax.bar([i - 0.2 for i in x], t["BTC %"], width=0.4, color="#999", label="BTC comprar y mantener 3 años")
ax.bar([i + 0.2 for i in x], t["Sistema %"], width=0.4, color="#d9531e", label="Sistema 3 años (riesgo 1%)")
ax.axhline(0, color="#333", lw=0.8)
ax.set_xticks(list(x)); ax.set_xticklabels(t["Inicio"], rotation=70, fontsize=8)
ax.set_ylabel("Retorno a 3 años (%)"); ax.grid(axis="y", alpha=0.3); ax.legend(loc="upper right")
ax.set_title("Si hubieras invertido $1.000 en este mes y esperado 3 años", fontsize=14, weight="bold")
fig.text(0.5, 0.01, "Simulación con datos históricos de Binance. Resultados pasados no garantizan resultados futuros. No es asesoría financiera.",
         ha="center", fontsize=9, color="#666")
fig.tight_layout(rect=(0, 0.03, 1, 1))
out = str(BASE / "resultados" / "ventanas_3_anos.jpg")
fig.savefig(out, dpi=120, pil_kwargs={"quality": 92}); print(out)
