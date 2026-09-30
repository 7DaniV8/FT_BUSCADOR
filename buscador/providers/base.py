"""
providers/base.py — Contrato común de los providers.

Un provider solo sabe una cosa: dado un partido, devolver candidatos
(eventos externos con título, URL e inicio). La decisión de si alguno es el
partido la toma resolver.py, igual para todas las casas.

Prohibido en cualquier provider: iniciar sesión, cookies, sesiones de la
casa, mercados, cuotas, betslip, cantidades, apuestas. Solo lectura pública.
"""
from __future__ import annotations

from ..resolver import Candidato, Partido


class ProviderError(Exception):
    pass


class Provider:
    """Dos formas de resolver:
      - candidatos(partido): lista de eventos externos; decide resolver.elegir.
      - resolver_directo(conn, partido, provider_id): el provider ya empareja
        con datos estructurados y devuelve (estado, url, confianza, id_externo).
        Si existe, el núcleo usa esta."""
    metodo = "base"

    async def candidatos(self, partido: Partido) -> list[Candidato]:
        raise NotImplementedError


class SinIntegracion(Provider):
    """Casas sin vía limpia todavía (PROVIDER_PENDING) o que dependen de una
    fuente aún no contratada (OpticOdds). No consultan nada."""
    metodo = "ninguno"

    async def candidatos(self, partido: Partido) -> list[Candidato]:
        return []
