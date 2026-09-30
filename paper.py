"""TRADER IA - Paper trading: el sistema opera en tiempo real con capital ficticio.

Uso:  python paper.py          (o lo corre la tarea programada cada hora)
      python paper.py --reset  (borra el estado y parte de cero)

Cada corrida procesa las velas de 4H cerradas desde la última vez, con el MISMO
motor del backtest (cartera.py). Si el PC estuvo apagado, se pone al día solo.
No se conecta a ninguna cuenta ni envía órdenes.

Archivos en paper/:
  ESTADO.md          resumen legible (capital, posiciones, últimas operaciones)
  estado.json        estado interno de la cartera
  operaciones.csv    historial de operaciones cerradas
  curva.csv          capital vela a vela
  log.txt            registro de cada corrida
"""
import sys
from pathlib import Path

BASE = Path(__file__).parent
DIR = BASE / "paper"
DIR.mkdir(exist_ok=True)
if sys.stdout is None:  # pythonw (tarea programada): la salida va al log
    sys.stdout = sys.stderr = open(DIR / "log.txt", "a", encoding="utf-8")

import json  # noqa: E402
import traceback  # noqa: E402
from datetime import datetime  # noqa: E402

import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from backtest import a_velas, drawdown_max, preparar  # noqa: E402
from cartera import Cartera  # noqa: E402
from datos import crear_exchange, descargar_velas  # noqa: E402
from main import construir_candidato  # noqa: E402
from scanner import detectar  # noqa: E402

ESTADO = DIR / "estado.json"
OPS = DIR / "operaciones.csv"
CURVA = DIR / "curva.csv"


def log(msg: str):
    linea = f"[{datetime.now():%Y-%m-%d %H:%M}] {msg}"
    print(linea)
    if sys.stdout.name != str(DIR / "log.txt"):
        with open(DIR / "log.txt", "a", encoding="utf-8") as f:
            f.write(linea + "\n")


def descargar(cfg: dict) -> dict:
    m = cfg["mercado"]
    ex = crear_exchange(m["exchange"])
    crudos = {}
    for par in m["pares"]:
        try:
            crudos[par] = descargar_velas(ex, par, m["timeframe"], m["velas"])
        except Exception as e:
            log(f"  [!] {par}: {type(e).__name__} - {e}")
    btc = crudos["BTC/USDT"]["close"] if "BTC/USDT" in crudos else None
    minimo = cfg["indicadores"]["ema_lenta"] + 50
    return {p: preparar(df, cfg, btc) for p, df in crudos.items() if len(df) >= minimo}


def correr(reset: bool = False):
    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    if reset:
        for f in (ESTADO, OPS, CURVA, DIR / "ESTADO.md"):
            f.unlink(missing_ok=True)

    dfs = descargar(cfg)
    if not dfs:
        log("Sin datos: ¿hay internet?")
        return
    velas = {p: a_velas(df) for p, df in dfs.items()}
    ultima_disponible = max(df.index[-1] for df in dfs.values())

    if ESTADO.exists():
        e = json.loads(ESTADO.read_text(encoding="utf-8"))
        cart = Cartera.desde_dict(cfg, e["cartera"])
        ultima, inicio = pd.Timestamp(e["ultima_vela"]), e["inicio"]
    else:  # primera corrida: parte evaluando la última vela cerrada
        cart = Cartera(cfg)
        ultima = sorted({T for df in dfs.values() for T in df.index})[-2]
        inicio = datetime.now().isoformat(timespec="minutes")
        log(f"Paper trading iniciado con {cfg['riesgo']['capital']} USDT ficticios")

    nuevas = sorted({T for df in dfs.values() for T in df.index if T > ultima})
    if not nuevas:
        log("Sin velas nuevas.")
        escribir_resumen(cfg, cart, dfs, inicio, ultima)
        return

    n_ops = len(cart.operaciones)
    for T in nuevas:
        cands = []
        for par, df in dfs.items():
            if T not in df.index:
                continue
            vista = df.loc[:T]
            ctx = detectar(vista, cfg)
            if ctx["senales"]:
                cands.append(construir_candidato(par, vista, ctx, cfg))
        cart.procesar(T, velas, cands)

    # Guardar
    nuevas_ops = pd.DataFrame(cart.operaciones[n_ops:])
    if len(nuevas_ops):
        nuevas_ops.to_csv(OPS, mode="a", header=not OPS.exists(), index=False)
    pd.DataFrame(cart.curva, columns=["fecha", "capital"]).to_csv(
        CURVA, mode="a", header=not CURVA.exists(), index=False)
    ESTADO.write_text(json.dumps({
        "inicio": inicio, "ultima_vela": ultima_disponible.isoformat(),
        "cartera": cart.a_dict(),
    }, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    for _, o in nuevas_ops.iterrows():
        log(f"  CERRADA {o['Par']} {o['Setup']} · {o['Motivo salida']} · {o['R']:+.2f}R ({o['PnL USDT']:+.2f} USDT)")
    for par, p in cart.pendientes.items():
        log(f"  NUEVA SEÑAL APROBADA {par} {p['setup']} · entra en la próxima apertura · "
            f"stop {p['plan']['stop']:.6g} · objetivo {p['plan']['objetivo']:.6g}")
    log(f"{len(nuevas)} vela(s) procesada(s) hasta {ultima_disponible:%Y-%m-%d %H:%M} UTC · "
        f"capital {cart.capital:.2f} · abiertas {len(cart.abiertas)} · pendientes {len(cart.pendientes)}")
    escribir_resumen(cfg, cart, dfs, inicio, ultima_disponible)


def escribir_resumen(cfg, cart: Cartera, dfs: dict, inicio: str, ultima):
    cap0 = cfg["riesgo"]["capital"]
    latente = sum((dfs[p]["close"].iloc[-1] - pos["entrada"]) * pos["qty"]
                  for p, pos in cart.abiertas.items() if p in dfs)
    total = cart.capital + latente
    ops = pd.read_csv(OPS) if OPS.exists() else pd.DataFrame()
    curva = pd.read_csv(CURVA)["capital"] if CURVA.exists() else pd.Series(dtype=float)

    L = [
        "# TRADER IA · Paper trading",
        "",
        f"_Actualizado {datetime.now():%Y-%m-%d %H:%M} · última vela {pd.Timestamp(ultima):%Y-%m-%d %H:%M} UTC · "
        f"iniciado {inicio}_",
        "",
        "Capital **ficticio**. No se conecta a ninguna cuenta. No es asesoría financiera.",
        "",
        "## Resumen",
        "",
        "| | |", "|---|---|",
        f"| Capital inicial | {cap0:,.2f} USDT |",
        f"| Capital realizado | {cart.capital:,.2f} USDT |",
        f"| Capital a mercado | **{total:,.2f} USDT ({(total / cap0 - 1) * 100:+.2f}%)** |",
        f"| Drawdown máx. | {drawdown_max(curva) * 100:.1f}% |" if len(curva) else "| Drawdown máx. | – |",
        f"| Operaciones cerradas | {len(ops)} |",
    ]
    if len(ops):
        L += [f"| Win rate | {(ops['R'] > 0).mean() * 100:.1f}% |",
              f"| Expectativa | {ops['R'].mean():+.3f}R (backtest: +0,20R a +0,27R) |"]

    L += ["", "## Posiciones abiertas", ""]
    if cart.abiertas:
        L += ["| Par | Setup | Desde | Entrada | Stop | Objetivo | Precio | Resultado |",
              "|---|---|---|---|---|---|---|---|"]
        for p, pos in cart.abiertas.items():
            precio = dfs[p]["close"].iloc[-1] if p in dfs else pos["entrada"]
            r = (precio - pos["entrada"]) / (pos["entrada"] - pos["stop_inicial"])
            L.append(f"| {p} | {pos['setup']} | {pd.Timestamp(pos['entrada_fecha']):%m-%d %H:%M} | "
                     f"{pos['entrada']:.6g} | {pos['stop']:.6g} | {pos['objetivo']:.6g} | "
                     f"{precio:.6g} | {r:+.2f}R |")
    else:
        L.append("_Ninguna._")

    L += ["", "## Señales aprobadas esperando entrada", ""]
    if cart.pendientes:
        for p, e in cart.pendientes.items():
            L.append(f"- **{p}** {e['setup']} (puntaje {e['puntaje']}) · stop {e['plan']['stop']:.6g} · "
                     f"objetivo {e['plan']['objetivo']:.6g} · R:B {e['plan']['rr']:.2f}")
    else:
        L.append("_Ninguna._")

    L += ["", "## Últimas operaciones", ""]
    if len(ops):
        L += ["| Par | Setup | Entrada | Salida | Motivo | R | PnL USDT |", "|---|---|---|---|---|---|---|"]
        for _, o in ops.tail(15).iloc[::-1].iterrows():
            L.append(f"| {o['Par']} | {o['Setup']} | {str(o['Entrada fecha'])[:16]} | "
                     f"{str(o['Salida fecha'])[:16]} | {o['Motivo salida']} | {o['R']:+.2f} | {o['PnL USDT']:+.2f} |")
    else:
        L.append("_Todavía no hay operaciones cerradas._")

    L += ["", "## Embudo", "", " · ".join(f"{k}: {v}" for k, v in cart.stats.items())]
    (DIR / "ESTADO.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        correr(reset="--reset" in sys.argv)
    except Exception:
        log("ERROR\n" + traceback.format_exc())
        raise
