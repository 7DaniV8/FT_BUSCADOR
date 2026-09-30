"""
buscador/resolver.py — ¿Este evento externo es el partido de FullTenis?

Reglas:
  * AMBOS jugadores son obligatorios. Si falta uno, confianza 0: no es él.
  * Suman: mismo día, misma hora (solo si FullTenis la conoce), torneo y
    categoría.
  * ITF sin hora: NO se inventa una hora. Simplemente no suma por hora, así
    que su confianza máxima es menor y se apoya en jugadores, fecha, torneo y
    categoría.
  * Si dos candidatos quedan casi empatados: AMBIGUO. Mejor no abrir nada que
    abrir el partido equivocado.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .claves import apellidos, dia, normalizar

UMBRAL_CONFIRMADO = 0.80
UMBRAL_AMBIGUO = 0.50
EMPATE = 0.10

ENCONTRADO = "ENCONTRADO"
NO_ENCONTRADO = "NO_ENCONTRADO"
AMBIGUO = "AMBIGUO"


@dataclass
class Partido:
    clave: str
    jugador1: str
    jugador2: str
    fecha: str
    hora_conocida: bool
    torneo: str = ""
    categoria: str = ""


@dataclass
class Candidato:
    id_externo: str
    titulo: str
    url: str
    inicio: str | None = None          # ISO, si la fuente lo da
    texto_extra: str = ""               # torneo, serie, descripción...
    datos: dict = field(default_factory=dict)


def _apellido_presente(jugador: str, texto_tokens: set[str]) -> bool:
    ap = apellidos(jugador)
    return bool(ap) and bool(ap & texto_tokens)


def _fecha(iso: str | None):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def confianza(p: Partido, c: Candidato) -> float:
    texto = set(normalizar(f"{c.titulo} {c.texto_extra}").split())
    if not (_apellido_presente(p.jugador1, texto) and _apellido_presente(p.jugador2, texto)):
        return 0.0
    puntos = 0.5
    fc = _fecha(c.inicio)
    if fc is not None:
        try:
            dias = abs((fc.date() - datetime.fromisoformat(dia(p.fecha)).date()).days)
        except ValueError:
            dias = None                    # fecha de FullTenis ilegible: no suma ni resta
        if dias is None:
            pass
        elif dias == 0:
            puntos += 0.2
        elif dias == 1:
            puntos += 0.1               # husos horarios
        else:
            puntos -= 0.3               # los mismos dos jugadores, otro día: otro partido
        if p.hora_conocida:
            fp = _fecha(p.fecha)
            if fp is not None and fp.tzinfo is not None and fc.tzinfo is not None:
                if abs((fc - fp).total_seconds()) <= 3 * 3600:
                    puntos += 0.1
    toks_torneo = {t for t in normalizar(p.torneo).split() if len(t) > 3}
    if toks_torneo and toks_torneo & texto:
        puntos += 0.1
    cat = (p.categoria or "").lower()
    if cat and (cat in texto or cat.replace("_m", "").replace("_w", "") in texto):
        puntos += 0.1
    return round(max(0.0, min(1.0, puntos)), 3)


def elegir(p: Partido, candidatos: list[Candidato]):
    """Devuelve (estado, candidato|None, confianza)."""
    puntuados = sorted(((confianza(p, c), c) for c in candidatos),
                       key=lambda x: x[0], reverse=True)
    puntuados = [x for x in puntuados if x[0] > 0]
    if not puntuados:
        return NO_ENCONTRADO, None, 0.0
    mejor_conf, mejor = puntuados[0]
    if len(puntuados) > 1 and mejor_conf - puntuados[1][0] < EMPATE \
            and puntuados[1][1].url != mejor.url:
        return AMBIGUO, None, mejor_conf
    if mejor_conf >= UMBRAL_CONFIRMADO:
        return ENCONTRADO, mejor, mejor_conf
    if mejor_conf >= UMBRAL_AMBIGUO:
        return AMBIGUO, mejor, mejor_conf
    return NO_ENCONTRADO, None, mejor_conf
