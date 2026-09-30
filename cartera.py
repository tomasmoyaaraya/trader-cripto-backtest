"""Motor de cartera simulada: lo usan backtest.py y paper.py (misma lógica exacta).

Por cada vela cerrada T, en este orden:
  1. Entradas aprobadas en el cierre anterior -> se llenan en la apertura de T
  2. Salidas: stop / objetivo / tiempo (modo "objetivo") o stop dinámico (modo "trailing").
     Si una vela toca stop y objetivo, se asume stop (conservador)
  3. Señales al cierre de T -> motor de riesgo con el estado real de la cartera
  4. Capital a valor de mercado

velas: {par: {T: (open, high, low, close, atr)}}
"""
import copy

import pandas as pd

from riesgo import evaluar_cartera, evaluar_individual


class Cartera:
    def __init__(self, cfg: dict):
        self.cfg = copy.deepcopy(cfg)
        # El freno por drawdown se desactiva: en simulación congelaría el sistema para
        # siempre (sin operaciones no hay recuperación). El drawdown sí se mide.
        self.cfg["riesgo"]["drawdown_maximo"] = float("inf")
        self.capital = cfg["riesgo"]["capital"]
        self.abiertas, self.pendientes = {}, {}
        self.operaciones, self.curva = [], []
        self.stats = {"señales": 0, "aprobadas": 0, "watchlist": 0, "rechazadas": 0,
                      "no_ejecutadas": 0}

    # ------------------------------------------------------------
    def procesar(self, T, velas: dict, candidatos: list):
        self._entradas(T, velas)
        self._salidas(T, velas)
        self._senales(candidatos)
        latente = sum((velas[p][T][3] - pos["entrada"]) * pos["qty"]
                      for p, pos in self.abiertas.items() if T in velas[p])
        self.curva.append((T, self.capital + latente))

    def ocupados(self) -> set:
        return set(self.abiertas) | set(self.pendientes)

    # ------------------------------------------------------------
    def _entradas(self, T, velas):
        r, slip = self.cfg["riesgo"], self.cfg["backtest"]["deslizamiento"]
        for par, e in list(self.pendientes.items()):
            barra = velas.get(par, {}).get(T)
            if barra is None:
                continue
            del self.pendientes[par]
            entrada = barra[0] * (1 + slip)
            p = e["plan"]
            if entrada <= p["stop"] or entrada >= p["objetivo"]:
                self.stats["no_ejecutadas"] += 1  # el gap de apertura invalidó el plan
                continue
            riesgo_usd = self.capital * r["riesgo_por_trade"]
            nocional = min(riesgo_usd / (entrada - p["stop"]) * entrada,
                           self.capital * r["posicion_max_pct"])
            qty = nocional / entrada
            self.abiertas[par] = {
                "par": par, "setup": e["setup"], "puntaje": e["puntaje"],
                "tendencia": e["tendencia"], "entrada_fecha": T, "entrada": entrada,
                "stop": p["stop"], "stop_inicial": p["stop"], "objetivo": p["objetivo"],
                "rr_plan": p["rr"], "qty": qty, "nocional": nocional,
                "riesgo_usd": qty * (entrada - p["stop"]), "velas": 0, "max_cierre": entrada,
            }

    def _salidas(self, T, velas):
        cp, bt = self.cfg["plan"], self.cfg["backtest"]
        slip = bt["deslizamiento"]
        trailing = cp.get("salida", "objetivo") == "trailing"
        for par, pos in list(self.abiertas.items()):
            barra = velas.get(par, {}).get(T)
            if barra is None:
                continue
            o, h, l, c, atr = barra
            pos["velas"] += 1
            salida = None
            if l <= pos["stop"]:
                motivo = "stop dinámico" if pos["stop"] > pos["stop_inicial"] else "stop"
                salida = min(o, pos["stop"]) * (1 - slip)
            elif not trailing and h >= pos["objetivo"]:
                salida, motivo = max(o, pos["objetivo"]), "objetivo"
            elif not trailing and pos["velas"] >= bt["max_velas"]:
                salida, motivo = c * (1 - slip), "tiempo"

            if salida is not None:
                self._cerrar(pos, salida, motivo, T)
                del self.abiertas[par]
            elif trailing:  # sube el stop con la info de esta vela (rige desde la siguiente)
                pos["max_cierre"] = max(pos["max_cierre"], c)
                r_unit = pos["entrada"] - pos["stop_inicial"]
                if pos["max_cierre"] >= pos["entrada"] + cp["trailing_activacion_r"] * r_unit:
                    pos["stop"] = max(pos["stop"], pos["max_cierre"] - cp["trailing_atr"] * atr)

    def _senales(self, candidatos):
        cands = [c for c in candidatos if c["par"] not in self.ocupados()]
        if not cands:
            return
        self.stats["señales"] += len(cands)
        self.cfg["riesgo"]["capital"] = self.capital
        ev = [evaluar_individual(c, self.cfg) for c in cands]
        ev = evaluar_cartera(
            ev, self.cfg, n=len(self.abiertas),
            exposicion=sum(p["nocional"] for p in self.abiertas.values()),
            perdida=sum(p["riesgo_usd"] for p in self.abiertas.values()),
        )
        for e in ev:
            clave = {"APROBADO": "aprobadas", "WATCHLIST": "watchlist",
                     "RECHAZADO": "rechazadas"}[e["veredicto"]]
            self.stats[clave] += 1
            if e["veredicto"] == "APROBADO":
                self.pendientes[e["par"]] = {
                    k: e[k] for k in ("par", "setup", "puntaje", "tendencia", "checks")
                } | {"plan": {k: e["plan"][k] for k in ("stop", "objetivo", "rr", "entrada")},
                     "vela": e["vela"]}

    def _cerrar(self, pos: dict, salida: float, motivo: str, T):
        com = self.cfg["backtest"]["comision"]
        bruto = (salida - pos["entrada"]) * pos["qty"]
        costos = com * (pos["entrada"] + salida) * pos["qty"]
        pnl = bruto - costos
        self.capital += pnl
        self.operaciones.append({
            "Par": pos["par"], "Setup": pos["setup"], "Puntaje": pos["puntaje"],
            "Tendencia": pos["tendencia"],
            "Entrada fecha": pd.Timestamp(pos["entrada_fecha"]).tz_localize(None),
            "Salida fecha": pd.Timestamp(T).tz_localize(None), "Velas": pos["velas"],
            "Entrada": pos["entrada"], "Stop inicial": pos["stop_inicial"],
            "Objetivo": pos["objetivo"], "Salida": salida, "Motivo salida": motivo,
            "R:B plan": round(pos["rr_plan"], 2),
            "Posición USDT": round(pos["nocional"], 2), "Riesgo USDT": round(pos["riesgo_usd"], 2),
            "Costos USDT": round(costos, 2), "PnL USDT": round(pnl, 2),
            "R": round(pnl / pos["riesgo_usd"], 2),
        })

    def cerrar_todo(self, velas: dict):
        """Posiciones vivas al final del backtest: se cierran al último precio."""
        slip = self.cfg["backtest"]["deslizamiento"]
        for par, pos in list(self.abiertas.items()):
            T = max(velas[par])
            self._cerrar(pos, velas[par][T][3] * (1 - slip), "fin backtest", T)
        self.abiertas.clear()

    # ------------------------------------------------------------
    #  Persistencia (paper trading)
    # ------------------------------------------------------------
    def a_dict(self) -> dict:
        def ts(d):
            return {k: (v.isoformat() if isinstance(v, pd.Timestamp) else v) for k, v in d.items()}
        return {
            "capital": self.capital,
            "abiertas": {p: ts(v) for p, v in self.abiertas.items()},
            "pendientes": {p: ts(v) for p, v in self.pendientes.items()},
            "stats": self.stats,
        }

    @classmethod
    def desde_dict(cls, cfg: dict, d: dict) -> "Cartera":
        c = cls(cfg)
        c.capital, c.stats = d["capital"], d["stats"]
        for p, v in d["abiertas"].items():
            v["entrada_fecha"] = pd.Timestamp(v["entrada_fecha"])
            c.abiertas[p] = v
        for p, v in d["pendientes"].items():
            v["vela"] = pd.Timestamp(v["vela"])
            c.pendientes[p] = v
        return c
