"""
buscador/categoria.py — Categoría deducida DENTRO del buscador.

FullTenis no manda la categoría como columna. Se deduce aquí del nombre del
torneo y del género, con reglas propias y sencillas. No se importa la lógica
de RankingFTR (shared/categories.py) a propósito: el buscador tiene que poder
borrarse sin tocar nada de allí, y al revés.

Categorías (las de la matriz de cobertura):
  ATP · WTA · CHALLENGER · WTA125 · ITF_M · ITF_W · OTRA
"""
from __future__ import annotations

import re

from .claves import normalizar

ATP, WTA, CHALLENGER, WTA125, ITF_M, ITF_W, OTRA = (
    "ATP", "WTA", "CHALLENGER", "WTA125", "ITF_M", "ITF_W", "OTRA")
CATEGORIAS = (ATP, WTA, CHALLENGER, WTA125, ITF_M, ITF_W, OTRA)

_ITF = re.compile(r"\b(itf|m15|m25|w15|w35|w50|w75|w100|m[0-9]{2,3}|w[0-9]{2,3})\b")


def _es_femenino(genero: str, torneo_n: str) -> bool | None:
    g = normalizar(genero)
    if g in ("f", "w", "women", "woman", "femenino", "mujeres", "female", "wta"):
        return True
    if g in ("m", "men", "man", "masculino", "hombres", "male", "atp"):
        return False
    if re.search(r"\b(wta|women|w[0-9]{2,3})\b", torneo_n):
        return True
    if re.search(r"\b(atp|men|m[0-9]{2,3})\b", torneo_n):
        return False
    return None


def deducir(torneo: str, genero: str = "") -> str:
    t = normalizar(torneo)
    fem = _es_femenino(genero, t)
    if "challenger" in t:
        return CHALLENGER
    if "125" in t and (fem or "wta" in t):
        return WTA125
    if _ITF.search(t):
        if fem is True or re.search(r"\bw[0-9]{2,3}\b", t):
            return ITF_W
        if fem is False or re.search(r"\bm[0-9]{2,3}\b", t):
            return ITF_M
        return OTRA
    if "wta" in t:
        return WTA
    if "atp" in t:
        return ATP
    if fem is True:
        return WTA
    if fem is False:
        return ATP
    return OTRA
