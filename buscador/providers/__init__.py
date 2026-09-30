"""
Registro de providers. El núcleo pide `obtener(metodo)`.

  kambi      BetPlay + Rushbet (datos públicos de Kambi, en vivo)
  fanduel    FanDuel · draftkings DraftKings · caesars Caesars
             (datos públicos de su web; ver providers/fuentes.py)
  oddspapi   desactivado: ninguna casa lo usa.
  opticodds  pendiente del trial: SinIntegracion.
  ninguno    casas sin vía limpia todavía: SinIntegracion.

Añadir o quitar una casa = su fila del catálogo (y, si va por OddsPapi, su
clave en providers/oddspapi.CASAS); nada más cambia.
"""
from __future__ import annotations

from .base import Provider, SinIntegracion
from .fuentes import FUENTES
from .oddspapi import OddsPapi

ODDSPAPI = OddsPapi()          # desactivado por decisión (30/09/2026); se conserva
_REGISTRO: dict[str, Provider] = {
    "oddspapi": ODDSPAPI,
    **FUENTES,                 # kambi, fanduel, draftkings, caesars
}
_SIN = SinIntegracion()


def obtener(metodo: str) -> Provider:
    """'ninguno' y 'opticodds' (sin trial todavía) caen en SinIntegracion:
    responden su estado y no bloquean a nadie."""
    return _REGISTRO.get(metodo, _SIN)
