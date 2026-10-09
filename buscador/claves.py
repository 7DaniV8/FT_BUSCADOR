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


_PARTICULAS = {"de", "del", "da", "do", "dos", "das", "la", "le", "van", "von", "der", "den", "di", "du", "el", "al", "jr", "sr"}


def apellidos(nombre: str) -> set[str]:
    """Palabras del APELLIDO, según el formato en que llega el nombre:
        'Martin Damm'          -> {'damm'}             (nombre apellido)
        'Damm M.'              -> {'damm'}             (apellido + inicial)
        'Fita Boluda A.'       -> {'fita', 'boluda'}   (apellido compuesto + inicial)
        'Damm, Martin'         -> {'damm'}             (apellido, nombre)
        'Carlos Alcaraz Garfia'-> {'alcaraz', 'garfia'} (nombre + dos apellidos: 08/10/2026,
                                   antes solo 'garfia' y la casa muestra 'Alcaraz')
        'Zhizhen Zhang'        -> {'zhang'}; 'Zhang Zhizhen' en la casa también casa (ambos lados)
    Las partículas ('de', 'la', 'van', 'jr'...) no cuentan. Basta con que UNA de
    ellas aparezca en el título del evento."""
    crudo = str(nombre or "")
    if "," in crudo:
        return {t for t in normalizar(crudo.split(",")[0]).split() if len(t) > 1 and t not in _PARTICULAS}
    toks = normalizar(crudo).split()
    if not toks:
        return set()
    if len(toks) > 1 and len(toks[-1]) == 1:          # termina en inicial: todo lo demás es apellido
        return {t for t in toks if len(t) > 1 and t not in _PARTICULAS}
    if len(toks) == 1:
        return {toks[0]} if len(toks[0]) > 1 else set()
    # 'nombre apellido' o 'nombre apellido1 apellido2': todo menos el primero
    resto = [t for t in toks[1:] if len(t) > 1 and t not in _PARTICULAS]
    return set(resto) if resto else ({toks[-1]} if len(toks[-1]) > 1 else set())


def parecidos(a: str, b: str) -> bool:
    """Dos apellidos 'iguales' aunque la casa los escriba un poco distinto
    (08/10/2026): 'schwartzman'/'schwarzman', 'kecmanovic'/'kecmanovich',
    'mpetshi'/'mpetschi'. Solo para palabras de 5+ letras y parecido ≥ 0,85;
    las cortas tienen que ser exactas (si no, 'lee' casaría con 'lei')."""
    if a == b:
        return True
    if len(a) < 5 or len(b) < 5 or a[0] != b[0]:
        return False
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio() >= 0.85


def apellido_en(apellidos_jugador: set[str], tokens_evento: set[str]) -> bool:
    """¿Alguno de los apellidos aparece (exacto o parecido) entre los tokens?"""
    if apellidos_jugador & tokens_evento:
        return True
    return any(parecidos(a, t) for a in apellidos_jugador for t in tokens_evento)


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
