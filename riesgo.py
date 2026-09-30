"""Etapa 4 - Motor de riesgo. Tiene veto: si un check falla, no se aprueba.

Veredictos: APROBADO / WATCHLIST / RECHAZADO
"""


def evaluar_individual(c: dict, cfg: dict) -> dict:
    """Checks por operación: R:B, volatilidad, puntaje y tamaño de posición."""
    r, cs = cfg["riesgo"], cfg["senales"]
    p = c["plan"]
    checks, veredicto = [], "APROBADO"

    def degradar(a: str):
        nonlocal veredicto
        orden = ["APROBADO", "WATCHLIST", "RECHAZADO"]
        if orden.index(a) > orden.index(veredicto):
            veredicto = a

    # R:B
    if p["rr"] >= r["rr_minimo"]:
        checks.append(f"R:B {p['rr']:.2f} OK")
    elif p["rr"] >= r["rr_watchlist"]:
        checks.append(f"R:B {p['rr']:.2f} bajo {r['rr_minimo']}")
        degradar("WATCHLIST")
    else:
        checks.append(f"R:B {p['rr']:.2f} insuficiente")
        degradar("RECHAZADO")

    # Volatilidad
    if c["atr_pct"] > r["atr_pct_maximo"]:
        checks.append(f"volatilidad {c['atr_pct']:.1%} excesiva")
        degradar("RECHAZADO")
    else:
        checks.append(f"volatilidad {c['atr_pct']:.1%} OK")

    # Filtro de tendencia
    permitidas = cs.get("tendencias_permitidas")
    if permitidas and c["tendencia"] not in permitidas:
        checks.append(f"tendencia {c['tendencia']} no permitida")
        degradar("RECHAZADO")

    # Fuerza relativa vs BTC
    if cs.get("fuerza_relativa_activa") and c.get("rs") is not None:
        if c["rs"] < cs["fuerza_relativa_minima"]:
            checks.append(f"fuerza relativa {c['rs']:+.1%} vs BTC")
            degradar("RECHAZADO")
        else:
            checks.append(f"fuerza relativa {c['rs']:+.1%} OK")

    # Puntaje de la señal
    if c["puntaje"] < cs["puntaje_minimo"]:
        checks.append(f"puntaje {c['puntaje']} bajo {cs['puntaje_minimo']}")
        degradar("WATCHLIST")

    # Tamaño de posición: arriesgar X% del capital hasta el stop
    riesgo_usd = r["capital"] * r["riesgo_por_trade"]
    nocional = riesgo_usd / p["stop_pct"]
    tope = r["capital"] * r["posicion_max_pct"]
    if nocional > tope:
        nocional = tope
        riesgo_usd = nocional * p["stop_pct"]
        checks.append(f"posición acotada a {r['posicion_max_pct']:.0%} del capital")

    return {
        **c,
        "veredicto": veredicto,
        "checks": checks,
        "nocional": nocional,
        "cantidad": nocional / p["entrada"],
        "riesgo_usd": riesgo_usd,
    }


def evaluar_cartera(evaluados: list, cfg: dict, n: int = 0,
                    exposicion: float = 0.0, perdida: float = 0.0) -> list:
    """Checks globales: drawdown, n° de posiciones, exposición y pérdida máxima.

    n / exposicion / perdida: lo que ya está abierto (el backtest lo informa).
    """
    r = cfg["riesgo"]
    bloqueo_dd = r["drawdown_actual"] >= r["drawdown_maximo"]
    for e in sorted(evaluados, key=lambda x: -x["puntaje"]):
        if e["veredicto"] != "APROBADO":
            continue
        motivo = None
        if bloqueo_dd:
            motivo = f"drawdown {r['drawdown_actual']:.0%} >= máximo {r['drawdown_maximo']:.0%}"
        elif n + 1 > r["max_posiciones"]:
            motivo = f"máximo {r['max_posiciones']} posiciones"
        elif exposicion + e["nocional"] > r["capital"] * r["exposicion_max_pct"]:
            motivo = f"exposición total superaría {r['exposicion_max_pct']:.0%}"
        elif perdida + e["riesgo_usd"] > r["capital"] * r["perdida_max_total"]:
            motivo = f"pérdida máx. total superaría {r['perdida_max_total']:.0%}"

        if motivo:
            e["veredicto"] = "WATCHLIST"
            e["checks"].append(motivo)
        else:
            n += 1
            exposicion += e["nocional"]
            perdida += e["riesgo_usd"]
            e["checks"].append("límites de cartera OK")
    return evaluados
