"""Stop dinámico y fuerza relativa vs la versión actual, en 2020-23 y 2023-26."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)
import copy
import pandas as pd, yaml
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import backtest as bt
from datos import crear_exchange

base = yaml.safe_load(open("config.yaml", encoding="utf-8"))
ex = crear_exchange("binance"); paso = ex.parse_timeframe("4h") * 1000
ahora = pd.Timestamp.now(tz="UTC").as_unit("ms")
periodos = {
    "2020-23": (pd.Timestamp("2020-09-29", tz="UTC").as_unit("ms"), pd.Timestamp("2023-09-29", tz="UTC").as_unit("ms")),
    "2023-26": (pd.Timestamp("2023-09-29", tz="UTC").as_unit("ms"), ahora),
}
combos = {
    "Actual":                 dict(salida="objetivo", rs=False),
    "A: stop dinámico":       dict(salida="trailing", rs=False),
    "Fuerza relativa":        dict(salida="objetivo", rs=True),
    "A + fuerza relativa":    dict(salida="trailing", rs=True),
}
filas, curvas, btcs = [], {}, {}
for pnom, (ini, fin) in periodos.items():
    desde = int(ini.timestamp() * 1000) - bt.CALENTAMIENTO * paso
    velas, sen, btc = bt.cargar(base, ex, desde, ini, fin, verbose=False)
    b = btc[btc.index >= ini]; btcs[pnom] = b / b.iloc[0] * 1000
    for cnom, c in combos.items():
        cfg = copy.deepcopy(base)
        cfg["plan"]["salida"] = c["salida"]; cfg["senales"]["fuerza_relativa_activa"] = c["rs"]
        ops, curva, st = bt.simular(cfg, velas, sen, ini)
        m = bt.metricas(ops, curva)
        curvas[(pnom, cnom)] = curva
        filas.append({"Periodo": pnom, "Versión": cnom, "Ops": m["Operaciones"], "Win %": m["Win rate %"],
                      "Expect. R": m["Expectativa (R)"], "Gan. prom R": m["Ganancia prom. (R)"],
                      "PF": m["Profit factor"], "Retorno %": m["Retorno %"], "DD %": m["Drawdown máx. %"],
                      "Ret/DD": round(m["Retorno %"] / -m["Drawdown máx. %"], 2),
                      "Mejor op R": ops["R"].max(), "Velas prom": m["Velas prom. abierta"]})
t = pd.DataFrame(filas)
print(t.to_string(index=False))

estilos = {"Actual": ("#d9531e", 2.2, "-"), "A: stop dinámico": ("#2a7de1", 1.8, "-"),
           "Fuerza relativa": ("#1e9e5a", 1.8, "-"), "A + fuerza relativa": ("#7b4fd6", 2.2, "-")}
fig, axes = plt.subplots(1, 2, figsize=(16, 7.5))
for ax, pnom in zip(axes, periodos):
    tp = t[t.Periodo == pnom].set_index("Versión")
    for cnom, (col, lw, ls) in estilos.items():
        c = curvas[(pnom, cnom)]; f = tp.loc[cnom]
        ax.plot(c.index, c.values, color=col, lw=lw, ls=ls,
                label=f"{cnom}: {f['Retorno %']:+.0f}% · caída máx {f['DD %']:.0f}% · {f['Expect. R']:+.2f}R")
    bb = btcs[pnom]
    ax.plot(bb.index, bb.values, color="#999", lw=1.2,
            label=f"BTC mantener: {(bb.iloc[-1]/1000-1)*100:+.0f}%")
    ax.axhline(1000, color="#bbb", lw=0.8)
    ax.set_title(f"{pnom}  ·  $1.000 iniciales · riesgo 1% por operación", fontsize=12, weight="bold")
    ax.grid(alpha=0.3); ax.legend(fontsize=9, loc="upper left"); ax.set_ylabel("Capital (USDT ficticios)")
fig.suptitle("TRADER IA · Stop dinámico (A) y fuerza relativa vs BTC", fontsize=15, weight="bold")
fig.text(0.5, 0.01, "Simulación con capital ficticio sobre datos históricos de Binance (4H, 15 pares). "
         "Resultados pasados no garantizan resultados futuros. No es asesoría financiera.",
         ha="center", fontsize=9, color="#666")
fig.tight_layout(rect=(0, 0.03, 1, 0.96))
out = str(BASE / "resultados" / "comparacion_A_fuerza_relativa.jpg")
fig.savefig(out, dpi=120, pil_kwargs={"quality": 92})
print(out)
