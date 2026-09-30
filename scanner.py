"""Etapa 2 - Indicadores y detección de los 5 setups (solo largos / spot).

Cada setup es una regla explícita: nada de caja negra.
"""
import pandas as pd


# ---------- indicadores ----------
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int) -> pd.Series:
    d = close.diff()
    ganancia = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    perdida = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + ganancia / perdida)


def atr(df: pd.DataFrame, n: int) -> pd.Series:
    prev = df["close"].shift()
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def agregar_indicadores(df: pd.DataFrame, cfg: dict, btc_close: pd.Series | None = None) -> pd.DataFrame:
    c = cfg["indicadores"]
    df = df.copy()
    if btc_close is not None:  # fuerza relativa vs BTC (causal: solo cierres pasados)
        n = cfg["senales"].get("fuerza_relativa_velas", 180)
        btc = btc_close.reindex(df.index).ffill()
        df["rs"] = df["close"].pct_change(n) - btc.pct_change(n)
    df["ema_r"] = ema(df["close"], c["ema_rapida"])
    df["ema_m"] = ema(df["close"], c["ema_media"])
    df["ema_l"] = ema(df["close"], c["ema_lenta"])
    df["rsi"] = rsi(df["close"], c["rsi"])
    df["atr"] = atr(df, c["atr"])
    df["vol_rel"] = df["volume"] / df["volume"].rolling(c["volumen_promedio"]).mean().shift()
    return df


# ---------- contexto ----------
def tendencia(v) -> str:
    if v.close > v.ema_m > v.ema_l:
        return "alcista"
    if v.close < v.ema_m < v.ema_l:
        return "bajista"
    return "lateral"


def puntaje_contexto(v, tend: str) -> int:
    p = {"alcista": 20, "lateral": 5, "bajista": 0}[tend]
    if v.vol_rel >= 1.5:
        p += 15
    elif v.vol_rel >= 1.0:
        p += 5
    if 45 <= v.rsi <= 68:
        p += 10
    elif v.rsi > 75:
        p -= 15  # sobrecompra: entrar tarde
    return p


# ---------- setups ----------
def detectar(df: pd.DataFrame, cfg: dict) -> dict:
    ci, cs = cfg["indicadores"], cfg["senales"]
    v, prev = df.iloc[-1], df.iloc[-2]
    tend = tendencia(v)
    senales = []

    # 1. Ruptura: cierra sobre el máximo de N velas previas con volumen alto
    maximo_previo = df["high"].iloc[-ci["lookback_ruptura"] - 1:-1].max()
    if v.close > maximo_previo and v.vol_rel >= cs["volumen_ruptura"]:
        senales.append(("Ruptura", 40, f"cierre sobre máx. {ci['lookback_ruptura']} velas con vol x{v.vol_rel:.1f}"))

    # 2. Pullback: tendencia alcista, toca la EMA rápida y cierra sobre ella
    if tend == "alcista" and v.low <= v.ema_r * 1.005 and v.close > v.ema_r and 40 <= v.rsi <= 60:
        senales.append(("Pullback", 40, f"retroceso a EMA{ci['ema_rapida']} en tendencia alcista"))

    # 3. Momentum: avance > 2 ATR en 3 velas, con volumen y sin sobrecompra
    avance = v.close - df["close"].iloc[-4]
    if avance > 2 * v.atr and v.vol_rel >= 1.2 and 55 <= v.rsi <= 75:
        senales.append(("Momentum", 35, f"avance de {avance / v.atr:.1f} ATR en 3 velas"))

    # 4. Continuación: tendencia alcista + pausa estrecha + cierre sobre la pausa
    k = ci["velas_consolidacion"]
    pausa = df.iloc[-k - 1:-1]
    rango = pausa["high"].max() - pausa["low"].min()
    if tend == "alcista" and rango < 2 * v.atr and v.close > pausa["high"].max() and v.vol_rel >= 1.0:
        senales.append(("Continuación", 40, f"sale de una pausa de {k} velas (rango {rango / v.atr:.1f} ATR)"))

    # 5. Reversión: RSI sale de sobreventa con vela alcista (contra-tendencia)
    if prev.rsi < 30 <= v.rsi and v.close > v.open:
        senales.append(("Reversión", 30, "RSI sale de sobreventa con vela alcista"))

    activos = cs.get("setups_activos")
    if activos is not None:
        senales = [s for s in senales if s[0] in activos]

    ctx = puntaje_contexto(v, tend)
    return {
        "precio": v.close,
        "tendencia": tend,
        "rsi": v.rsi,
        "atr": v.atr,
        "atr_pct": v.atr / v.close,
        "vol_rel": v.vol_rel,
        "rs": v.rs if "rs" in df.columns and pd.notna(v.rs) else None,
        "vela": df.index[-1],
        "senales": [
            {"setup": s, "puntaje": max(0, min(100, base + ctx)), "motivo": m}
            for s, base, m in senales
        ],
    }
