"""
buscador/cobertura.py — ¿Qué parte de los partidos EN JUEGO encuentra cada casa?
(30/09/2026; rehecho el 01/10/2026 con datos reales.)

Medido en producción: la lista "en vivo" de FullTenis incluye todos los partidos
vistos en el día (también los terminados) y "la casa tiene a uno de los dos
jugadores" era casi siempre OTRO partido del mismo jugador (su siguiente ronda).
Así que la medición parte de lo que LAS CASAS marcan como en juego:

  base      partidos de FullTenis que al menos una casa marca EN JUEGO (se están
            jugando de verdad y FullTenis los tiene).
  por casa  pct      → qué parte de la base encuentra esa casa
            sin_emparejar → partidos que la casa tiene EN JUEGO y no se
            emparejan con ninguno de FullTenis (nombres escritos distinto o
            partidos que FullTenis no tiene: UTR, ITF...), con ejemplos.

NO hace peticiones nuevas: usa las listas que el BOT ya tiene. Cada 10 minutos.
Se publica en /salud → "cobertura".
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from .claves import apellidos
from .providers.fuentes import FUENTES, emparejar
from .resolver import ENCONTRADO, Partido

log = logging.getLogger("buscador.cobertura")
CASAS_DE = {"kambi": "BetPlay + Rushbet", "fanduel": "FanDuel", "draftkings": "DraftKings",
            "caesars": "Caesars", "kalshi": "Kalshi", "betmgm": "BetMGM + Bwin",
            "polymarket": "Polymarket", "betano": "Betano", "wplay": "Wplay"}
COBERTURA: dict = {}


def _fulltenis(conn) -> list[dict]:
    """Partidos de FullTenis de las últimas 14 h y próximas 2 h (sin dobles)."""
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(hours=14)).date().isoformat()
    hasta = (ahora + timedelta(hours=2)).isoformat()[:19]
    filas = conn.execute("SELECT clave, jugador1, jugador2, fecha, hora_conocida FROM fixtures_cache "
                         "WHERE fecha >= ? AND fecha <= ? AND origen != 'casas'", (desde, hasta)).fetchall()
    # FullTenis tiene algunos partidos DUPLICADOS (llegan por dos vías, con horas
    # distintas): se agrupan (mismos apellidos, < 12 h) para no dar "dudoso".
    salida, vistos = [], []
    for f in filas:
        if "/" in f["jugador1"] + f["jugador2"]:
            continue
        par = frozenset((frozenset(apellidos(f["jugador1"])), frozenset(apellidos(f["jugador2"]))))
        try:
            t = datetime.fromisoformat(str(f["fecha"]).replace("Z", "+00:00")[:19]) if f["hora_conocida"] else None
        except ValueError:
            t = None
        if any(par == p and (t is None or tv is None or abs((t - tv).total_seconds()) <= 12 * 3600)
               for p, tv in vistos):
            continue
        vistos.append((par, t))
        salida.append({"id": f["clave"], "j1": f["jugador1"], "j2": f["jugador2"], "inicio": f["fecha"],
                       "hora": bool(f["hora_conocida"])})
    return salida


def calcular(conn) -> dict:
    ft = _fulltenis(conn)
    activas = {m: f for m, f in FUENTES.items() if f.configurada()}
    # 1) Partidos EN JUEGO de cada casa → ¿a qué partido de FullTenis corresponden?
    en_juego_ft: set[str] = set()
    sin_emparejar: dict[str, list[str]] = {}
    vivos_casa: dict[str, int] = {}
    for m, f in activas.items():
        vivos = [e for e in f._eventos if e.get("en_juego")]
        vivos_casa[m] = len(vivos)
        sin_emparejar[m] = []
        for e in vivos:
            est, ev, _ = emparejar(Partido("", e["j1"], e["j2"], str(e.get("inicio") or ""), False), ft)
            if est == ENCONTRADO and ev:
                en_juego_ft.add(ev["id"])
            else:
                sin_emparejar[m].append(f"{e['j1']} vs {e['j2']}" + (f" ({e['torneo']})" if e.get("torneo") else ""))
    base = [p for p in ft if p["id"] in en_juego_ft]
    # 2) De esa base, ¿cuántos encuentra cada casa (en toda su lista)?
    por_casa = {}
    for m, f in activas.items():
        enc = sum(1 for p in base
                  if emparejar(Partido("", p["j1"], p["j2"], p["inicio"], p["hora"]), f._eventos)[0] == ENCONTRADO)
        por_casa[m] = {"casas": CASAS_DE.get(m, m), "encontrados": enc,
                       "pct": round(100 * enc / len(base)) if base else None,
                       "en_juego_en_la_casa": vivos_casa[m],
                       "sin_emparejar": len(sin_emparejar[m]),
                       "ejemplos_sin_emparejar": sin_emparejar[m][:6],
                       "lista_casa": len(f._eventos), "error_casa": f._error}
    COBERTURA.clear()
    COBERTURA.update({"cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "base": "partidos de FullTenis que al menos una casa marca en juego",
                      "partidos": len(base), "por_casa": por_casa})
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
