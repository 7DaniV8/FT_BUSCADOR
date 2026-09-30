#!/usr/bin/env python3
"""
scripts/probar_eeuu.py — ¿De dónde sale el número de cada partido en las casas
de EE. UU.? Pregunta a cada casa por su lista de tenis (lo mismo que hace su
web) y muestra: jugadores → número → URL generada.

    python scripts/probar_eeuu.py
    python scripts/probar_eeuu.py --fanduel-ak TU_AK      (para incluir FanDuel)

IMPORTANTE: estas casas solo responden a conexiones desde EE. UU. Activa ANTES
la VPN de EE. UU. (la aplicación de todo el ordenador, no una extensión).
Crea eeuu_enlaces.html con las URL para abrirlas (con la VPN activa).
"""
from __future__ import annotations

import argparse
import asyncio
import html
import json
import os
import sys
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

def _clave_local(archivo: str) -> str:
    f = Path(__file__).resolve().parent.parent / archivo
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def _ak_local() -> str:
    return _clave_local("fanduel_ak.txt")


# Claves públicas guardadas por scripts/sacar_claves.py (si no vienen por variable)
if not os.getenv("BETMGM_ACCESSID") and _clave_local("betmgm_accessid.txt"):
    os.environ["BETMGM_ACCESSID"] = _clave_local("betmgm_accessid.txt")


ap = argparse.ArgumentParser()
ap.add_argument("--fanduel-ak", default=os.getenv("FANDUEL_AK", "") or _ak_local())
ap.add_argument("--max", type=int, default=5, help="partidos de ejemplo por casa")
ap.add_argument("--region", choices=["us", "co", "todas"], default="us",
                help="us: casas de EE. UU.; co: casas de Colombia; todas: como el servidor de "
                     "producción (con la VPN de EE. UU. activa)")
A = ap.parse_args()
os.environ["FANDUEL_AK"] = A.fanduel_ak or ""

from buscador.providers.fuentes import FUENTES, refrescar_todas  # noqa: E402

_US = {"draftkings": "draftkings_nc", "fanduel": "fanduel_nc", "caesars": "caesars_nc",
       "betmgm": "betmgm_nc", "kalshi": "kalshi", "polymarket": "polymarket"}
_CO = {"kambi": "betplay_co", "betano": "betano_co", "wplay": "wplay_co"}
CASAS = _US if A.region == "us" else _CO if A.region == "co" else {**_CO, **_US}
# Casas que salen de cada fuente (para el resumen)
CASAS_DE = {"kambi": "BetPlay + Rushbet", "betano": "Betano", "wplay": "Wplay",
            "draftkings": "DraftKings", "fanduel": "FanDuel", "caesars": "Caesars",
            "betmgm": "BetMGM + Bwin CO", "kalshi": "Kalshi", "polymarket": "Polymarket"}


def pais():
    try:
        with urllib.request.urlopen("https://ipinfo.io/json", timeout=8) as r:
            d = json.loads(r.read())
            return f"{d.get('country', '?')} · {d.get('region', '?')}"
    except Exception:
        return "desconocido"


def main():
    esperado = "CO" if A.region == "co" else "US"
    print(f"Tu conexión sale desde: {pais()}   (para --region {A.region} debe ser {esperado})\n")
    estados = asyncio.run(refrescar_todas())
    filas = []
    for metodo, pid in CASAS.items():
        f = FUENTES[metodo]
        print(f"── {metodo.upper():<11} {estados.get(metodo)}")
        plantilla = f.ENLACES[pid]
        for ev in f._eventos[:A.max]:
            url = plantilla.format(**ev)
            print(f"   {ev['j1']} vs {ev['j2']}")
            print(f"      número: {ev['id']}")
            print(f"      URL:    {url}")
            filas.append((metodo, f"{ev['j1']} vs {ev['j2']}", ev["id"], url))
        print()
    L = ["<!doctype html><meta charset=utf-8><title>Enlaces EE. UU.</title>",
         "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;"
         "background:#12161c;color:#e6e6e6}a{color:#8ab4ff;word-break:break-all}td,th{padding:6px 10px;"
         "border-bottom:1px solid #2a2f37;text-align:left;font-size:14px}</style>",
         "<h1>Casas de EE. UU.: jugadores → número → URL</h1>",
         "<p>Ábrelas con la VPN de EE. UU. activa y comprueba que cada una abre su partido.</p>",
         "<table><tr><th>Casa</th><th>Partido</th><th>Número</th><th>URL</th></tr>"]
    for casa, partido, num, url in filas:
        L.append(f"<tr><td>{casa}</td><td>{html.escape(partido)}</td><td>{html.escape(str(num))}</td>"
                 f"<td><a href='{html.escape(url)}' target=_blank rel='noopener noreferrer'>"
                 f"{html.escape(url)}</a></td></tr>")
    L.append("</table>")
    ok = [m for m in CASAS if estados.get(m, "").endswith("partidos") and not estados[m].startswith("0 ")]
    print("══ RESUMEN " + "═" * 50)
    for m in CASAS:
        e = estados.get(m, "")
        marca = "✅" if m in ok else ("⚠️ " if e.startswith("0 ") else "❌")
        print(f"  {marca} {CASAS_DE.get(m, m):<20} {e}")
    n_casas = sum(len(CASAS_DE.get(m, m).split(" + ")) for m in ok)
    print(f"  → {n_casas} casas con enlace directo desde esta conexión")
    if A.region == "todas" and "betano" not in ok:
        print("  (Betano necesita el proxy colombiano: FUENTES_PROXY)")
    print()
    salida = RAIZ / {"us": "eeuu_enlaces.html", "co": "colombia_enlaces.html",
                     "todas": "produccion_enlaces.html"}[A.region]
    salida.write_text("\n".join(L), encoding="utf-8")
    print(f"Abre {salida} para probar las URL.")


if __name__ == "__main__":
    main()
