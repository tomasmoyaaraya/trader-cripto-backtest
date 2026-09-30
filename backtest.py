"""TRADER IA - Backtest de las reglas sobre historia real.

Uso:  python backtest.py
      python backtest.py --desde 2020-09-29 --hasta 2023-09-29   (periodo a elección)
Reutiliza scanner.py, planner.py y riesgo.py sin cambios: se prueba exactamente
el mismo sistema que corre en vivo. En cada vela solo se usa información pasada.
"""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
import pandas as pd
import yaml

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from openpyxl.drawing.image import Image as XLImage  # noqa: E402

from cartera import Cartera  # noqa: E402
from datos import crear_exchange  # noqa: E402
from main import construir_candidato  # noqa: E402
from scanner import agregar_indicadores, detectar  # noqa: E402

BASE = Path(__file__).parent
CACHE = BASE / "datos_historicos"
CALENTAMIENTO = 300  # velas previas al inicio, para que la EMA200 esté estable
if sys.stdout:
    sys.stdout.reconfigure(encoding="utf-8")


# ============================================================
#  1. Historia (descarga paginada + caché local)
# ============================================================
def _bajar(ex, par, tf, desde_ms, hasta_ms=None) -> list:
    paso = ex.parse_timeframe(tf) * 1000
    filas = []
    while True:
        lote = ex.fetch_ohlcv(par, timeframe=tf, since=desde_ms, limit=1000)
        if not lote:
            break
        filas += lote
        desde_ms = lote[-1][0] + paso
        if len(lote) < 1000 or (hasta_ms and desde_ms >= hasta_ms):
            break
    return filas


def historia(ex, par: str, tf: str, desde_ms: int) -> pd.DataFrame:
    CACHE.mkdir(exist_ok=True)
    archivo = CACHE / f"{par.replace('/', '-')}_{tf}.csv"
    cols = ["ts", "open", "high", "low", "close", "volume"]
    df = pd.read_csv(archivo) if archivo.exists() else pd.DataFrame(columns=cols)
    paso = ex.parse_timeframe(tf) * 1000

    nuevas = []
    if df.empty:
        nuevas = _bajar(ex, par, tf, desde_ms)
    else:
        if df["ts"].iloc[0] > desde_ms + paso:  # falta historia antigua
            nuevas += _bajar(ex, par, tf, desde_ms, hasta_ms=int(df["ts"].iloc[0]))
        nuevas += _bajar(ex, par, tf, int(df["ts"].iloc[-1]) + paso)  # lo más reciente

    if nuevas:
        nuevas = pd.DataFrame(nuevas, columns=cols)
        df = nuevas if df.empty else pd.concat([df, nuevas])
    df = df.astype({"ts": "int64"})
    ahora = int(time.time() * 1000)
    df = (df.drop_duplicates("ts").sort_values("ts")
            .query("ts + @paso <= @ahora"))  # solo velas cerradas
    df.to_csv(archivo, index=False)

    df = df[df["ts"] >= desde_ms].copy()
    df["fecha"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("fecha").drop(columns="ts").astype(float)


# ============================================================
#  2. Preparación y señales históricas (misma lógica que en vivo)
# ============================================================
def preparar(df: pd.DataFrame, cfg: dict, btc_close: pd.Series | None) -> pd.DataFrame:
    """Indicadores causales (EMA, RSI, ATR, volumen, fuerza relativa): calcularlos
    una vez sobre toda la serie no filtra información futura."""
    return agregar_indicadores(df, cfg, btc_close)


def a_velas(df: pd.DataFrame) -> dict:
    return {T: (b.open, b.high, b.low, b.close, b.atr) for T, b in df.iterrows()}


def senales_historicas(par: str, df: pd.DataFrame, cfg: dict, inicio) -> dict:
    """{fecha_de_cierre: candidato}. Cada vela ve solo df hasta ella misma."""
    out = {}
    desde = max(df.index.searchsorted(inicio), cfg["indicadores"]["ema_lenta"] + 50)
    for t in range(desde, len(df)):
        vista = df.iloc[: t + 1]
        ctx = detectar(vista, cfg)
        if ctx["senales"]:
            out[df.index[t]] = construir_candidato(par, vista, ctx, cfg)
    return out


def cargar(cfg: dict, ex, desde_ms: int, inicio, fin, verbose: bool = True) -> tuple:
    """Descarga/lee la historia de todos los pares y calcula sus señales."""
    m = cfg["mercado"]
    crudos = {}
    for par in m["pares"]:
        try:
            df = historia(ex, par, m["timeframe"], desde_ms)
            df = df[df.index < fin]
        except Exception as e:
            print(f"  [!] {par}: {type(e).__name__} - {e}")
            continue
        if len(df) < cfg["indicadores"]["ema_lenta"] + 50:
            print(f"  [!] {par}: sin historia suficiente en el periodo (listado después)")
            continue
        crudos[par] = df

    btc = crudos["BTC/USDT"]["close"] if "BTC/USDT" in crudos else None
    velas, senales = {}, {}
    for par, df in crudos.items():
        t0 = time.time()
        df = preparar(df, cfg, btc)
        senales[par] = senales_historicas(par, df, cfg, inicio)
        velas[par] = a_velas(df)
        if verbose:
            print(f"  {par:<10} {len(df):>5} velas · {len(senales[par]):>4} señales · {time.time() - t0:.1f}s")
    return velas, senales, btc


# ============================================================
#  3. Simulación de cartera (motor compartido con paper.py)
# ============================================================
def simular(cfg: dict, velas: dict, senales: dict, inicio) -> tuple:
    cart = Cartera(cfg)
    tiempos = sorted({T for v in velas.values() for T in v if T >= inicio})
    for T in tiempos:
        cart.procesar(T, velas, [s[T] for s in senales.values() if T in s])
    cart.cerrar_todo(velas)
    curva = pd.Series(dict(cart.curva), name="Sistema")
    return pd.DataFrame(cart.operaciones), curva, cart.stats


# ============================================================
#  4. Métricas
# ============================================================
def drawdown_max(curva: pd.Series) -> float:
    return (curva / curva.cummax() - 1).min() if len(curva) else 0.0


def metricas(ops: pd.DataFrame, curva: pd.Series) -> dict:
    if ops.empty:
        return {"Operaciones": 0}
    gan, per = ops[ops["PnL USDT"] > 0], ops[ops["PnL USDT"] <= 0]
    pf = gan["PnL USDT"].sum() / abs(per["PnL USDT"].sum()) if len(per) else float("inf")
    return {
        "Operaciones": len(ops),
        "Win rate %": round(len(gan) / len(ops) * 100, 1),
        "Expectativa (R)": round(ops["R"].mean(), 3),
        "Ganancia prom. (R)": round(gan["R"].mean(), 2) if len(gan) else 0,
        "Pérdida prom. (R)": round(per["R"].mean(), 2) if len(per) else 0,
        "Profit factor": round(pf, 2),
        "PnL USDT": round(ops["PnL USDT"].sum(), 2),
        "Retorno %": round((curva.iloc[-1] / curva.iloc[0] - 1) * 100, 1) if len(curva) else None,
        "Drawdown máx. %": round(drawdown_max(curva) * 100, 1),
        "Costos USDT": round(ops["Costos USDT"].sum(), 2),
        "Velas prom. abierta": round(ops["Velas"].mean(), 1),
    }


def desglose(ops: pd.DataFrame, col: str) -> pd.DataFrame:
    if ops.empty:
        return pd.DataFrame()
    g = ops.groupby(col)
    return pd.DataFrame({
        "Operaciones": g.size(),
        "Win rate %": (g["PnL USDT"].apply(lambda s: (s > 0).mean()) * 100).round(1),
        "Expectativa (R)": g["R"].mean().round(3),
        "Profit factor": g["PnL USDT"].apply(
            lambda s: round(s[s > 0].sum() / abs(s[s <= 0].sum()), 2) if (s <= 0).any() else float("inf")),
        "PnL USDT": g["PnL USDT"].sum().round(2),
    }).sort_values("Expectativa (R)", ascending=False).reset_index()


# ============================================================
#  5. Reporte
# ============================================================
def grafico(curva: pd.Series, btc: pd.Series | None, corte, ruta: Path):
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(curva.index, curva.values, label="Sistema", color="#d9531e", lw=1.8)
    if btc is not None:
        ax.plot(btc.index, btc.values, label="Comprar y mantener BTC", color="#888", lw=1.2)
    if corte is not None:
        ax.axvline(corte, color="#333", ls="--", lw=1)
        ax.text(corte, ax.get_ylim()[1], "  validación →", va="top", fontsize=9)
    ax.set_title("Curva de capital (USDT ficticios)")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(ruta, dpi=110)
    plt.close(fig)


def guardar(resumen, por_setup, por_par, por_anio, ops, curvas, stats, cfg, png) -> Path:
    ruta = BASE / "resultados" / f"backtest_{datetime.now():%Y%m%d_%H%M}.xlsx"
    ruta.parent.mkdir(exist_ok=True)
    with pd.ExcelWriter(ruta, engine="openpyxl") as xw:
        resumen.to_excel(xw, sheet_name="Resumen")
        pd.DataFrame(stats.items(), columns=["Embudo", "Cantidad"]).to_excel(
            xw, sheet_name="Resumen", startrow=len(resumen) + 3, index=False)
        por_setup.to_excel(xw, sheet_name="Por setup", index=False)
        por_par.to_excel(xw, sheet_name="Por par", index=False)
        por_anio.to_excel(xw, sheet_name="Por año", index=False)
        ops.to_excel(xw, sheet_name="Operaciones", index=False)
        curvas.to_excel(xw, sheet_name="Curva de capital")
        pd.DataFrame(
            [{"Parámetro": f"{sec}.{k}", "Valor": str(v)}
             for sec, d in cfg.items() for k, v in d.items()]
        ).to_excel(xw, sheet_name="Config usada", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ancho = max(len(str(c.value or "")) for c in col)
                ws.column_dimensions[col[0].column_letter].width = min(ancho + 2, 45)
        xw.book["Resumen"].add_image(XLImage(png), "H2")
    return ruta


# ============================================================
def main():
    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    m, bt = cfg["mercado"], cfg["backtest"]
    ex = crear_exchange(m["exchange"])
    paso_ms = ex.parse_timeframe(m["timeframe"]) * 1000

    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="AAAA-MM-DD (por defecto: hace `anos` años)")
    ap.add_argument("--hasta", help="AAAA-MM-DD (por defecto: hoy)")
    args = ap.parse_args()

    fin = (pd.Timestamp(args.hasta, tz="UTC") if args.hasta
           else pd.Timestamp(datetime.now(timezone.utc)))
    inicio = (pd.Timestamp(args.desde, tz="UTC") if args.desde
              else (fin - pd.DateOffset(years=bt["anos"])).floor("D"))
    inicio, fin = inicio.as_unit("ms"), fin.as_unit("ms")
    corte = pd.Timestamp(bt["fecha_corte"], tz="UTC")
    con_tramos = inicio < corte < fin
    desde_ms = int(inicio.timestamp() * 1000) - CALENTAMIENTO * paso_ms

    print(f"\nTRADER IA · BACKTEST · {m['timeframe']} · {inicio:%Y-%m-%d} → {fin:%Y-%m-%d}")
    print(f"Entrenamiento hasta {corte:%Y-%m-%d} · validación después" if con_tramos
          else "Periodo completo fuera de entrenamiento/validación (datos nunca vistos)")
    print("=" * 66)

    velas, senales, btc = cargar(cfg, ex, desde_ms, inicio, fin)
    if not velas:
        sys.exit("No se pudo descargar ningún par.")
    ops, curva, stats = simular(cfg, velas, senales, inicio)
    capital0 = cfg["riesgo"]["capital"]

    btc_bh = None
    if btc is not None:
        b = btc[btc.index >= inicio]
        btc_bh = (b / b.iloc[0] * capital0).rename("BTC comprar y mantener")

    # Métricas por tramo (las operaciones se asignan por fecha de entrada)
    corte_naive = corte.tz_localize(None)
    tramos = {"TOTAL": (ops, curva)}
    if con_tramos:
        tramos["Entrenamiento"] = (ops[ops["Entrada fecha"] < corte_naive] if len(ops) else ops,
                                   curva[curva.index < corte])
        tramos["Validación"] = (ops[ops["Entrada fecha"] >= corte_naive] if len(ops) else ops,
                                curva[curva.index >= corte])
    resumen = pd.DataFrame({k: metricas(o, c) for k, (o, c) in tramos.items()})
    if btc_bh is not None:
        resumen["BTC comprar y mantener"] = pd.Series({
            "Retorno %": round((btc_bh.iloc[-1] / btc_bh.iloc[0] - 1) * 100, 1),
            "Drawdown máx. %": round(drawdown_max(btc_bh) * 100, 1),
        })

    por_setup, por_par = desglose(ops, "Setup"), desglose(ops, "Par")
    por_anio = pd.DataFrame()
    if not ops.empty:
        ops["Año"] = ops["Entrada fecha"].dt.year
        por_anio = desglose(ops, "Año").sort_values("Año")
        por_motivo = ops["Motivo salida"].value_counts()
        stats.update({f"salidas por {k}": v for k, v in por_motivo.items()})

    print("=" * 66)
    print(resumen.fillna("").to_string())
    print("\nPor setup:")
    print(por_setup.to_string(index=False) if len(por_setup) else "  (sin operaciones)")
    print("\nPor año:")
    print(por_anio.to_string(index=False) if len(por_anio) else "  (sin operaciones)")
    print("\nEmbudo:", " · ".join(f"{k}: {v}" for k, v in stats.items()))

    curvas = pd.concat([curva, btc_bh], axis=1) if btc_bh is not None else curva.to_frame()
    curvas.index = curvas.index.tz_localize(None)
    png = BASE / "resultados" / f"curva_{datetime.now():%Y%m%d_%H%M}.png"
    png.parent.mkdir(exist_ok=True)
    grafico(curva, btc_bh, corte if con_tramos else None, png)
    ruta = guardar(resumen, por_setup, por_par, por_anio, ops, curvas, stats, cfg, png)
    print(f"\nReporte: {ruta}\nGráfico: {png}")
    print("Simulación con capital ficticio. Resultados pasados no garantizan resultados futuros.\n")


if __name__ == "__main__":
    main()
