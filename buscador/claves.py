"""
buscador/claves.py — Identidad de partido y normalización de nombres.

CLAVE COMPUESTA (regla acordada): fixture_id + fecha + jugador1 + jugador2.
El fixture_id de FullTenis sale de un CRC32 del bot y puede chocar (el propio
RankingFTR lo registra como "CHOQUE de fixture_id"), así que nunca se usa solo.
Los jugadores entran ordenados: el mismo partido con los nombres al revés da
la misma clave. De la fecha solo cuenta el DÍA: los ITF llegan sin hora.

Esto es lógica PROPIA del buscador. No se importa nada de RankingFTR.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

_NO_LETRA = re.compile(r"[^a-z0-9 ]+")


def normalizar(nombre: str) -> str:
    """'Martín DAMM-Jr.' -> 'martin damm jr'"""
    s = unicodedata.normalize("NFKD", str(nombre or "")).encode("ascii", "ignore").decode()
    s = s.lower().replace("-", " ").replace(",", " ")
    s = _NO_LETRA.sub(" ", s)
    return " ".join(s.split())


def tokens_nombre(nombre: str) -> set[str]:
    """Palabras significativas del nombre: sin iniciales sueltas ('m', 'a')."""
    return {t for t in normalizar(nombre).split() if len(t) > 1}


def apellidos(nombre: str) -> set[str]:
    """Palabras del APELLIDO, según el formato en que llega el nombre:
        'Martin Damm'        -> {'damm'}            (nombre apellido)
        'Damm M.'            -> {'damm'}            (apellido + inicial)
        'Fita Boluda A.'     -> {'fita', 'boluda'}  (apellido compuesto + inicial)
        'Damm, Martin'       -> {'damm'}            (apellido, nombre)
    Basta con que UNA de ellas aparezca en el título del evento."""
    crudo = str(nombre or "")
    if "," in crudo:
        return {t for t in normalizar(crudo.split(",")[0]).split() if len(t) > 1}
    toks = normalizar(crudo).split()
    if not toks:
        return set()
    if len(toks) > 1 and len(toks[-1]) == 1:          # termina en inicial
        return {t for t in toks if len(t) > 1}
    return {toks[-1]} if len(toks[-1]) > 1 else set()


def dia(fecha: str) -> str:
    """'2026-09-28T14:00:00Z' -> '2026-09-28'; '2026-09-28' -> '2026-09-28'"""
    return str(fecha or "")[:10]


def tiene_hora(fecha: str) -> bool:
    """Los fixtures ITF llegan con la fecha sola. Eso NO es medianoche: es
    'hora desconocida', y así se trata (menos confianza, nunca hora inventada)."""
    f = str(fecha or "")
    return len(f) > 10 and any(c.isdigit() for c in f[11:16])


def clave_partido(fixture_id, fecha: str, jugador1: str, jugador2: str) -> str:
    j = sorted([normalizar(jugador1), normalizar(jugador2)])
    base = f"{str(fixture_id or '').strip()}|{dia(fecha)}|{j[0]}|{j[1]}"
    return hashlib.sha1(base.encode()).hexdigest()[:20]
