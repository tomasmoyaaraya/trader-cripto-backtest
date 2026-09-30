"""TRADER IA - Fase 1: escanea, arma el plan y lo pasa por el motor de riesgo.

Uso:  python main.py
Solo análisis. No ejecuta órdenes ni se conecta a ninguna cuenta.
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from datos import crear_exchange, descargar_velas
from planner import armar_plan
from riesgo import evaluar_cartera, evaluar_individual
from scanner import agregar_indicadores, detectar

BASE = Path(__file__).parent
if sys.stdout:  # con pythonw (tarea programada) no hay consola
    sys.stdout.reconfigure(encoding="utf-8")


def fmt(x: float) -> str:
    return f"{x:.6g}"


def escanear(cfg: dict):
    m = cfg["mercado"]
    ex = crear_exchange(m["exchange"])
    mercado, candidatos = [], []
    try:  # referencia para la fuerza relativa
        btc = descargar_velas(ex, "BTC/USDT", m["timeframe"], m["velas"])["close"]
    except Exception:
        btc = None

    for par in m["pares"]:
        try:
            df = descargar_velas(ex, par, m["timeframe"], m["velas"])
        except Exception as e:  # par inexistente, caída de red, etc.
            print(f"  [!] {par}: {type(e).__name__} - {e}")
            continue
        df = agregar_indicadores(df, cfg, btc)
        ctx = detectar(df, cfg)
        mercado.append({
            "Par": par,
            "Precio": ctx["precio"],
            "Tendencia": ctx["tendencia"],
            "RSI": round(ctx["rsi"], 1),
            "ATR %": round(ctx["atr_pct"] * 100, 2),
            "Vol. relativo": round(ctx["vol_rel"], 2),
            "Setups": ", ".join(s["setup"] for s in ctx["senales"]) or "-",
        })
        print(f"  {par:<10} {ctx['tendencia']:<8} setups: {len(ctx['senales'])}")

        if ctx["senales"]:
            candidatos.append(construir_candidato(par, df, ctx, cfg))
    return mercado, candidatos


def construir_candidato(par: str, df: pd.DataFrame, ctx: dict, cfg: dict) -> dict:
    """Un plan por par: el setup de mayor puntaje; el resto como respaldo."""
    senales = sorted(ctx["senales"], key=lambda s: -s["puntaje"])
    mejor = senales[0]
    return {
        "par": par,
        "setup": mejor["setup"],
        "otros_setups": ", ".join(s["setup"] for s in senales[1:]),
        "puntaje": mejor["puntaje"],
        "motivo": mejor["motivo"],
        "tendencia": ctx["tendencia"],
        "atr_pct": ctx["atr_pct"],
        "rs": ctx["rs"],
        "vela": ctx["vela"],
        "plan": armar_plan(df, ctx, cfg),
    }


def a_tabla(evaluados: list) -> pd.DataFrame:
    orden = {"APROBADO": 0, "WATCHLIST": 1, "RECHAZADO": 2}
    filas = []
    for e in sorted(evaluados, key=lambda x: (orden[x["veredicto"]], -x["puntaje"])):
        p = e["plan"]
        filas.append({
            "Veredicto": e["veredicto"],
            "Par": e["par"],
            "Setup": e["setup"],
            "Puntaje": e["puntaje"],
            "Tendencia": e["tendencia"],
            "Entrada": fmt(p["entrada"]),
            "Zona entrada": f"{fmt(p['zona_entrada'][0])} - {fmt(p['zona_entrada'][1])}",
            "Stop": fmt(p["stop"]),
            "Invalidación (cierre bajo)": fmt(p["invalidacion"]),
            "Objetivo": fmt(p["objetivo"]),
            "Tipo objetivo": p["tipo_objetivo"],
            "R:B": round(p["rr"], 2),
            "Stop %": round(p["stop_pct"] * 100, 2),
            "Posición USDT": round(e["nocional"], 2),
            "Riesgo USDT": round(e["riesgo_usd"], 2),
            "Motivo señal": e["motivo"],
            "Otros setups": e["otros_setups"] or "-",
            "Checks de riesgo": " | ".join(e["checks"]),
            "Vela (UTC)": e["vela"].strftime("%Y-%m-%d %H:%M"),
        })
    return pd.DataFrame(filas)


def guardar_excel(decision: pd.DataFrame, mercado: pd.DataFrame, cfg: dict) -> Path:
    carpeta = BASE / "resultados"
    carpeta.mkdir(exist_ok=True)
    ruta = carpeta / f"scan_{datetime.now():%Y%m%d_%H%M}.xlsx"
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        decision.to_excel(xw, sheet_name="Decisiones", index=False)
        mercado.to_excel(xw, sheet_name="Mercado", index=False)
        pd.DataFrame(
            [{"Parámetro": f"{sec}.{k}", "Valor": str(v)}
             for sec, d in cfg.items() for k, v in d.items()]
        ).to_excel(xw, sheet_name="Config usada", index=False)
        for ws in xw.book.worksheets:  # autoajuste de columnas
            for col in ws.columns:
                ancho = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(ancho + 2, 70)
            ws.freeze_panes = "A2"
    return ruta


def main():
    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    m = cfg["mercado"]
    print(f"\nTRADER IA · fase 1 · {m['exchange']} {m['timeframe']} · {len(m['pares'])} pares")
    print("=" * 60)

    mercado, candidatos = escanear(cfg)
    evaluados = evaluar_cartera([evaluar_individual(c, cfg) for c in candidatos], cfg)
    decision = a_tabla(evaluados)
    df_mercado = pd.DataFrame(mercado)

    print("=" * 60)
    if decision.empty:
        print("Sin setups en la última vela cerrada. Es un resultado normal: el sistema")
        print("no fuerza operaciones.")
    else:
        conteo = decision["Veredicto"].value_counts()
        print("  ".join(f"{k}: {v}" for k, v in conteo.items()))
        cols = ["Veredicto", "Par", "Setup", "Puntaje", "Entrada", "Stop", "Objetivo", "R:B", "Posición USDT"]
        print(decision[cols].to_string(index=False))

    ruta = guardar_excel(decision, df_mercado, cfg)
    print(f"\nReporte: {ruta}")
    print("Análisis automatizado con capital ficticio. No es asesoría financiera.\n")


if __name__ == "__main__":
    main()
