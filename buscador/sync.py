"""
buscador/sync.py — Trae los partidos de FullTenis a la caché propia.

REGLAS DEFINITIVAS
  * Solo GET /ft-intel/fixtures y GET /ft-intel/en-vivo, con la cabecera
    X-FTR-Lectura-Secret (FTR_LECTURA_SECRET). Nada más: RankingFTR rechaza con
    403 esa credencial en cualquier otra ruta o método.
  * Cada SYNC_MINUTOS (5-10). Si FullTenis no responde, se espacia el
    siguiente intento (hasta 30 min) en vez de insistir: el buscador nunca se
    convierte en carga para FullTenis.
  * Corre DENTRO de BOT_BUSCADOR, nunca dentro de RankingFTR.
  * Después, todas las búsquedas se hacen contra esta caché, no contra FTR.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx

from . import categoria, config
from .claves import clave_partido, dia, normalizar, tiene_hora

log = logging.getLogger("buscador.sync")
CABECERA = "X-FTR-Lectura-Secret"
DIAS_RETENCION = 3


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _estado(conn, clave, valor):
    conn.execute("INSERT OR REPLACE INTO sync_estado (clave, valor) VALUES (?,?)",
                 (clave, str(valor)))


def guardar_fixture(conn: sqlite3.Connection, f: dict, origen: str) -> bool:
    j1, j2 = str(f.get("jugador1") or "").strip(), str(f.get("jugador2") or "").strip()
    fecha = str(f.get("fecha") or "").strip()
    if not (j1 and j2 and len(fecha) >= 10):
        return False
    torneo = str(f.get("torneo") or "")
    genero = str(f.get("genero") or "")
    clave = clave_partido(f.get("fixture_id"), fecha, j1, j2)
    conn.execute(
        "INSERT INTO fixtures_cache (clave, fixture_id, fecha, hora_conocida, jugador1, "
        "jugador2, torneo, categoria, genero, superficie, origen, actualizado_en) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(clave) DO UPDATE SET fecha=excluded.fecha, "
        "hora_conocida=excluded.hora_conocida, torneo=excluded.torneo, "
        "categoria=excluded.categoria, genero=excluded.genero, "
        "superficie=excluded.superficie, actualizado_en=excluded.actualizado_en",
        (clave, str(f.get("fixture_id") or ""), fecha, 1 if tiene_hora(fecha) else 0,
         j1, j2, torneo, categoria.deducir(torneo, genero), genero,
         str(f.get("superficie") or ""), origen, _ahora()))
    return True


def _ya_existe_par(conn, dia_: str, j1: str, j2: str) -> bool:
    """El mismo partido puede llegar por fixtures y por en-vivo, con ids
    distintos. Si ya está ese par de jugadores ese día, no se duplica."""
    par = sorted([normalizar(j1), normalizar(j2)])
    for f in conn.execute("SELECT jugador1, jugador2 FROM fixtures_cache WHERE substr(fecha,1,10)=?",
                          (dia_,)):
        if sorted([normalizar(f["jugador1"]), normalizar(f["jugador2"])]) == par:
            return True
    return False


async def sincronizar_una_vez(conn: sqlite3.Connection, cliente: httpx.AsyncClient) -> dict:
    if not (config.FTR_SERVICE_URL and config.FTR_LECTURA_SECRET):
        raise RuntimeError("faltan FTR_SERVICE_URL o FTR_LECTURA_SECRET")
    cab = {CABECERA: config.FTR_LECTURA_SECRET}
    n_fix, offset = 0, 0
    while True:
        r = await cliente.get(f"{config.FTR_SERVICE_URL}/ft-intel/fixtures", headers=cab,
                              params={"horas_atras": config.SYNC_HORAS_ATRAS,
                                      "horas_adelante": config.SYNC_HORAS_ADELANTE,
                                      "limite": 500, "offset": offset})
        r.raise_for_status()
        j = r.json()
        for f in j.get("fixtures") or []:
            n_fix += guardar_fixture(conn, f, "fixtures")
        if not j.get("hay_mas"):
            break
        offset += 500
        if offset > 20000:          # tope de seguridad
            break
    r = await cliente.get(f"{config.FTR_SERVICE_URL}/ft-intel/en-vivo", headers=cab)
    r.raise_for_status()
    n_vivo = 0
    for p in r.json().get("partidos") or []:
        fecha = str(p.get("primera_vez_visto") or "")
        j1, j2 = p.get("home"), p.get("away")
        if not (j1 and j2 and len(fecha) >= 10) or _ya_existe_par(conn, dia(fecha), j1, j2):
            continue
        n_vivo += guardar_fixture(conn, {"fixture_id": f"vivo:{p.get('fid', '')}",
                                         "fecha": fecha, "jugador1": j1, "jugador2": j2,
                                         "torneo": p.get("liga") or p.get("tour") or "",
                                         "genero": p.get("genero") or ""}, "en_vivo")
    limite = (datetime.now(timezone.utc) - timedelta(days=DIAS_RETENCION)).date().isoformat()
    conn.execute("DELETE FROM fixtures_cache WHERE substr(fecha,1,10) < ?", (limite,))
    _estado(conn, "ultimo_ok", _ahora())
    _estado(conn, "ultimo_resumen", f"fixtures={n_fix} en_vivo={n_vivo}")
    conn.commit()
    return {"fixtures": n_fix, "en_vivo": n_vivo}


async def bucle(conectar) -> None:
    """Tarea de fondo del servicio del buscador."""
    espera_error = config.SYNC_MINUTOS * 60
    while True:
        conn = conectar()
        try:
            async with httpx.AsyncClient(timeout=config.TIMEOUT_FTR_S) as cli:
                res = await sincronizar_una_vez(conn, cli)
            log.info(f"[sync] {res}")
            espera = config.SYNC_MINUTOS * 60
            espera_error = espera
        except Exception as e:
            _estado(conn, "ultimo_error", f"{_ahora()} {type(e).__name__}: {e}")
            conn.commit()
            log.warning(f"[sync] FullTenis no disponible: {e}")
            espera_error = min(espera_error * 2, 30 * 60)
            espera = espera_error
        finally:
            conn.close()
        await asyncio.sleep(espera)
