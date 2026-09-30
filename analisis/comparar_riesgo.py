"""¿Qué pasa si se arriesga más por operación? (1%, 2%, 3%) vs BTC, en 2020-23 y 2023-26."""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
os.chdir(BASE)
import copy
import pandas as pd, yaml
import backtest as bt
from datos import crear_exchange
from scanner import agregar_indicadores, tendencia

base = yaml.safe_load(open("config.yaml", encoding="utf-8"))
ex = crear_exchange("binance"); paso = ex.parse_timeframe("4h") * 1000
ahora = pd.Timestamp.now(tz="UTC").floor("D").as_unit("ms")
periodos = {
    "2020-23": (pd.Timestamp("2020-09-29", tz="UTC").as_unit("ms"), pd.Timestamp("2023-09-29", tz="UTC").as_unit("ms")),
    "2023-26": (pd.Timestamp("2023-09-29", tz="UTC").as_unit("ms"), ahora),
}
variantes = {
    "Actual 1%":   dict(riesgo_por_trade=0.01, posicion_max_pct=0.30, exposicion_max_pct=0.90, max_posiciones=3, perdida_max_total=0.03),
    "2% riesgo":   dict(riesgo_por_trade=0.02, posicion_max_pct=0.34, exposicion_max_pct=1.00, max_posiciones=3, perdida_max_total=0.06),
    "2% · 5 pos":  dict(riesgo_por_trade=0.02, posicion_max_pct=0.20, exposicion_max_pct=1.00, max_posiciones=5, perdida_max_total=0.10),
    "3% riesgo":   dict(riesgo_por_trade=0.03, posicion_max_pct=0.34, exposicion_max_pct=1.00, max_posiciones=3, perdida_max_total=0.09),
}

def dd(s): return (s / s.cummax() - 1).min()

filas = []
curvas = {}
for pnom, (ini, fin) in periodos.items():
    desde = int(ini.timestamp() * 1000) - bt.CALENTAMIENTO * paso
    velas, sen, btc = {}, {}, None
    for par in base["mercado"]["pares"]:
        df = bt.historia(ex, par, "4h", desde); df = df[df.index < fin]
        if len(df) < 250: continue
        sen[par] = bt.senales_historicas(par, df, base, ini)
        velas[par] = {T: (b.open, b.high, b.low, b.close) for T, b in df.iterrows()}
        if par == "BTC/USDT": btc = df
    for vnom, v in variantes.items():
        cfg = copy.deepcopy(base); cfg["riesgo"].update(v)
        ops, curva, _ = bt.simular(cfg, velas, sen, ini)
        # exposición promedio (fracción del capital invertida en el tiempo)
        idx = curva.index.tz_localize(None)
        inv = pd.Series(0.0, index=idx)
        for _, o in ops.iterrows():
            inv[(idx >= o["Entrada fecha"]) & (idx <= o["Salida fecha"])] += o["Posición USDT"]
        expo = (inv / curva.values).mean()
        ret = curva.iloc[-1] / curva.iloc[0] - 1
        curvas[(pnom, vnom)] = curva / curva.iloc[0] * 1000
        filas.append({"Periodo": pnom, "Estrategia": vnom, "Retorno %": round(ret*100, 1),
                      "DD máx %": round(dd(curva)*100, 1), "Retorno/DD": round(ret / -dd(curva), 2),
                      "Exposición prom. %": round(expo*100, 1), "Ops": len(ops)})
    # BTC comprar y mantener
    b = btc[btc.index >= ini]["close"]
    r = b.iloc[-1]/b.iloc[0]-1
    curvas[(pnom, 'BTC mantener')] = b / b.iloc[0] * 1000
    filas.append({"Periodo": pnom, "Estrategia": "BTC mantener", "Retorno %": round(r*100,1),
                  "DD máx %": round(dd(b)*100,1), "Retorno/DD": round(r/-dd(b),2), "Exposición prom. %": 100.0, "Ops": 1})
    # BTC solo en tendencia alcista (misma definición de tendencia del sistema)
    d = agregar_indicadores(btc, base)
    alc = pd.Series([tendencia(x) == "alcista" for x in d.itertuples()], index=d.index).shift(1).fillna(False)
    d = d[d.index >= ini]; alc = alc[alc.index >= ini]
    rets = d["close"].pct_change().fillna(0)
    cambios = alc.astype(int).diff().abs().fillna(0)
    eq = (1 + rets * alc - cambios * 0.0015).cumprod()
    r = eq.iloc[-1] - 1
    curvas[(pnom, 'BTC solo en tend. alcista')] = eq * 1000
    filas.append({"Periodo": pnom, "Estrategia": "BTC solo en tend. alcista", "Retorno %": round(r*100,1),
                  "DD máx %": round(dd(eq)*100,1), "Retorno/DD": round(r/-dd(eq),2),
                  "Exposición prom. %": round(alc.mean()*100,1), "Ops": int(cambios.sum()/2)})

print(pd.DataFrame(filas).to_string(index=False))

import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
estilos = {
    "Actual 1%": ("#d9531e", 2.4, "-"), "2% riesgo": ("#2a7de1", 1.8, "-"),
    "2% · 5 pos": ("#7b4fd6", 1.6, "-"), "3% riesgo": ("#1e9e5a", 1.6, "-"),
    "BTC mantener": ("#888888", 1.4, "-"), "BTC solo en tend. alcista": ("#444444", 1.2, "--"),
}
tab = pd.DataFrame(filas).set_index(["Periodo", "Estrategia"])
fig, axes = plt.subplots(1, 2, figsize=(16, 7.5))
for ax, pnom in zip(axes, periodos):
    for nom, (col, lw, ls) in estilos.items():
        c = curvas[(pnom, nom)]
        f = tab.loc[(pnom, nom)]
        ax.plot(c.index, c.values, color=col, lw=lw, ls=ls,
                label=f"{nom}: {f['Retorno %']:+.0f}% · caída máx {f['DD máx %']:.0f}%")
    ax.axhline(1000, color="#bbb", lw=0.8)
    ax.set_title(f"{pnom}  ·  $1.000 iniciales", fontsize=13, weight="bold")
    ax.grid(alpha=0.3); ax.legend(fontsize=9.5, loc="upper left")
    ax.set_ylabel("Capital (USDT ficticios)")
fig.suptitle("TRADER IA · ¿Qué pasa si se arriesga más por operación?", fontsize=15, weight="bold")
fig.text(0.5, 0.01, "Simulación con capital ficticio sobre datos históricos de Binance (4H, 15 pares). "
         "Resultados pasados no garantizan resultados futuros. No es asesoría financiera.",
         ha="center", fontsize=9, color="#666")
fig.tight_layout(rect=(0, 0.03, 1, 0.96))
out = str(BASE / "resultados" / "comparacion_riesgo.jpg")
fig.savefig(out, dpi=120, pil_kwargs={"quality": 92})
print(out)
