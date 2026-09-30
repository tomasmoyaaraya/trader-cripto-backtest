"""Etapa 1 - Descarga de velas desde la API pública del exchange."""
import time

import ccxt
import pandas as pd


def crear_exchange(nombre: str):
    return getattr(ccxt, nombre)({"enableRateLimit": True})


def descargar_velas(exchange, par: str, timeframe: str, n: int) -> pd.DataFrame:
    """Devuelve solo velas CERRADAS (la vela en curso se descarta)."""
    raw = exchange.fetch_ohlcv(par, timeframe=timeframe, limit=n + 1)
    df = pd.DataFrame(raw, columns=["ts", "open", "high", "low", "close", "volume"])

    duracion_ms = exchange.parse_timeframe(timeframe) * 1000
    ahora_ms = int(time.time() * 1000)
    df = df[df["ts"] + duracion_ms <= ahora_ms]

    df["fecha"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    return df.set_index("fecha").drop(columns="ts").tail(n)
