#!/usr/bin/env python3
"""
scripts/medir_feed.py — Medición del feed de OpticOdds durante el TRIAL.

NO CONTRATAR TODAVÍA. Este script existe para responder, con datos, lo que el
trial tiene que demostrar antes de pagar:

  1. ¿Nuestra API key trae deep_link?
  2. ¿Hay enlaces para las casas de NC que queremos (bet365, Caesars, FanDuel,
     BetMGM, DraftKings, Fanatics, theScore Bet)? ¿Y para alguna de Colombia?
  3. ¿Son URLs del EVENTO y no URLs que añaden selecciones al betslip?
  4. ¿Los términos permiten abrirlas públicamente desde FullTenis? (esto se
     revisa en el contrato, no en código: queda como casilla del informe)
  5. Cobertura por sportsbook y categoría: ATP, WTA, Challenger, WTA125,
     ITF hombres, ITF mujeres.

ESTADO: preparado a la espera de la clave. La forma exacta de las respuestas
de OpticOdds se fija con su documentación del trial; hasta entonces el script
trabaja sobre un volcado JSON que guardes de su API:

    python scripts/medir_feed.py --volcado respuesta_opticodds.json

Formato mínimo esperado del volcado (lista de filas):
    [{"sportsbook": "...", "fixture": "Damm vs Fils", "torneo": "...",
      "genero": "M", "fecha": "2026-09-28T14:00:00Z", "deep_link": "https://..."}]

Genera enlaces_para_probar.csv (mismas columnas de prueba manual que Kalshi y
Polymarket) y un resumen de cobertura.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from buscador import categoria  # noqa: E402

SOSPECHA_BETSLIP = ("betslip", "addtobetslip", "selection", "outcome", "bs=", "slip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--volcado", required=True)
    ap.add_argument("--salida", default="enlaces_para_probar.csv")
    args = ap.parse_args()
    filas = json.loads(Path(args.volcado).read_text(encoding="utf-8"))
    cob = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # casa -> cat -> [con enlace, total]
    salida = []
    for f in filas:
        casa = str(f.get("sportsbook", "?"))
        cat = categoria.deducir(str(f.get("torneo", "")), str(f.get("genero", "")))
        link = str(f.get("deep_link") or "")
        cob[casa][cat][1] += 1
        if not link:
            continue
        cob[casa][cat][0] += 1
        u = link.lower()
        salida.append({"provider": casa, "partido": f.get("fixture", ""),
                       "torneo": f.get("torneo", ""), "categoria": cat,
                       "fecha": f.get("fecha", ""), "url": link,
                       "dominio": urlparse(link).hostname or "",
                       "sospecha_betslip": "SI" if any(s in u for s in SOSPECHA_BETSLIP) else "",
                       "deep_link (ok/fallo)": "",
                       "abre_sin_login (abrio/pidio_login/pidio_ubicacion/no_cargo)": "",
                       "evento_correcto (ok/fallo)": "", "navegador_limpio (si/no)": "",
                       "probador": "", "region_prueba": "", "notas": ""})
    with open(args.salida, "w", newline="", encoding="utf-8") as fh:
        if salida:
            w = csv.DictWriter(fh, fieldnames=list(salida[0].keys()))
            w.writeheader()
            w.writerows(salida)
    print(f"{len(salida)} enlaces en {args.salida}")
    print("\nCobertura (con enlace / total) por casa y categoría:")
    for casa, cats in sorted(cob.items()):
        print(f"  {casa}: " + ", ".join(f"{c} {a}/{t}" for c, (a, t) in sorted(cats.items())))
    sospechas = sum(1 for s in salida if s["sospecha_betslip"])
    if sospechas:
        print(f"\n⚠️ {sospechas} enlaces parecen de betslip/selección: NO sirven para FullTenis.")


if __name__ == "__main__":
    main()
