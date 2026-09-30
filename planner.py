"""Etapa 3 - Plan de trading: entrada, stop, objetivo, invalidación y R:B."""
import pandas as pd


def resistencia_cercana(df: pd.DataFrame, sobre: float, velas: int, k: int = 3):
    """Menor máximo pivote (k velas a cada lado) que esté sobre `sobre`."""
    h = df["high"].iloc[-velas:]
    pivotes = h[(h == h.rolling(2 * k + 1, center=True).max())]
    candidatos = pivotes[pivotes > sobre]
    return candidatos.min() if not candidatos.empty else None


def armar_plan(df: pd.DataFrame, ctx: dict, cfg: dict) -> dict:
    cp = cfg["plan"]
    a = ctx["atr"]
    entrada = ctx["precio"]

    # Stop estructural bajo el mínimo reciente, acotado entre min y max ATR
    swing_low = df["low"].iloc[-cp["velas_swing"]:].min()
    dist = entrada - (swing_low - cp["buffer_stop_atr"] * a)
    dist = min(max(dist, cp["stop_min_atr"] * a), cp["stop_max_atr"] * a)
    stop = entrada - dist
    invalidacion = stop + cp["buffer_stop_atr"] * a

    # Objetivo: primera resistencia real; si no hay, proyección en R
    res = resistencia_cercana(df, entrada + 0.5 * a, cp["velas_resistencia"])
    if res is not None:
        objetivo, tipo_obj = res - 0.1 * a, "resistencia"
    else:
        objetivo, tipo_obj = entrada + cp["proyeccion_r"] * dist, f"proyección {cp['proyeccion_r']:g}R"

    return {
        "entrada": entrada,
        "zona_entrada": (entrada - 0.25 * a, entrada + 0.25 * a),
        "stop": stop,
        "invalidacion": invalidacion,
        "objetivo": objetivo,
        "tipo_objetivo": tipo_obj,
        "rr": (objetivo - entrada) / dist,
        "stop_pct": dist / entrada,
    }
