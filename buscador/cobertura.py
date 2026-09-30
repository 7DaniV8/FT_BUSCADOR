"""
buscador/cobertura.py — ¿Qué parte de los partidos EN JUEGO de FullTenis
encuentra cada casa? (30/09/2026)

Cada 10 minutos cruza la lista en juego de FullTenis (la que ya lee sync) con
la lista que el BOT ya tiene de cada casa. NO hace peticiones nuevas a nadie.
Para cada casa: partidos, encontrados, dudosos y "casi-coincidencias": la casa
tiene a UNO de los dos jugadores pero el partido no se emparejó (señal de nombres
escritos distinto). Se publica en /salud → "cobertura".
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import sync
from .claves import apellidos
from .providers.fuentes import FUENTES, _tokens, emparejar
from .resolver import AMBIGUO, ENCONTRADO, Partido

log = logging.getLogger("buscador.cobertura")
CASAS_DE = {"kambi": "BetPlay + Rushbet", "fanduel": "FanDuel", "draftkings": "DraftKings",
            "caesars": "Caesars", "kalshi": "Kalshi", "betmgm": "BetMGM + Bwin",
            "polymarket": "Polymarket", "betano": "Betano", "wplay": "Wplay"}
COBERTURA: dict = {}


def _partidos(conn) -> tuple[list[dict], str]:
    if sync.EN_VIVO:
        return list(sync.EN_VIVO), "en juego según FullTenis"
    # Sin lista en vivo: los que empezaron en las últimas 3 horas.
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(hours=3)).isoformat()[:19]
    filas = conn.execute("SELECT jugador1, jugador2, torneo, fecha FROM fixtures_cache "
                         "WHERE hora_conocida=1 AND fecha BETWEEN ? AND ? LIMIT 300",
                         (desde, ahora.isoformat()[:19])).fetchall()
    return ([{"j1": f["jugador1"], "j2": f["jugador2"], "liga": f["torneo"], "fecha": f["fecha"]}
             for f in filas], "empezados en las últimas 3 h")


def calcular(conn) -> dict:
    partidos, base = _partidos(conn)
    partidos = [p for p in partidos if "/" not in f"{p['j1']}{p['j2']}"]   # sin dobles
    por_casa = {}
    for metodo, f in FUENTES.items():
        if not f.configurada():
            continue
        evs = f._eventos
        enc = amb = 0
        casi = []
        for p in partidos:
            est, _, _ = emparejar(Partido("", p["j1"], p["j2"], p["fecha"] or "", False), evs)
            if est == ENCONTRADO:
                enc += 1
                continue
            if est == AMBIGUO:
                amb += 1
                continue
            a1, a2 = apellidos(p["j1"]), apellidos(p["j2"])
            for e in evs:
                t = _tokens(e["j1"]) | _tokens(e["j2"])
                if (a1 & t) or (a2 & t):
                    casi.append(f"FullTenis «{p['j1']} vs {p['j2']}» ≈ casa «{e['j1']} vs {e['j2']}»")
                    break
        n = len(partidos)
        por_casa[metodo] = {"casas": CASAS_DE.get(metodo, metodo), "partidos": n, "encontrados": enc,
                            "pct": round(100 * enc / n) if n else None, "dudosos": amb,
                            "casi": len(casi), "ejemplos_casi": casi[:5],
                            "lista_casa": len(evs), "error_casa": f._error}
    COBERTURA.clear()
    COBERTURA.update({"cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "base": base, "partidos": len(partidos), "por_casa": por_casa})
    return COBERTURA


async def bucle(conectar, cada_s: int = 600) -> None:
    await asyncio.sleep(90)               # deja que sync y las casas carguen primero
    while True:
        conn = conectar()
        try:
            calcular(conn)
        except Exception as e:
            log.warning(f"[cobertura] {type(e).__name__}: {e}")
        finally:
            conn.close()
        await asyncio.sleep(cada_s)
