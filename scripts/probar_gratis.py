#!/usr/bin/env python3
"""
scripts/probar_gratis.py — Dos comprobaciones que NO gastan cupo de OddsPapi.

  1. /v4/account (siempre gratis): tu límite real de peticiones y cuántas llevas.
  2. /v4/historical-odds (siempre gratis): ¿trae el ENLACE o el número de
     partido de la casa, aunque el partido ya esté en juego? Según la
     documentación solo trae precios; se comprueba por si acaso.

Uso (desde la raíz de BOT_BUSCADOR, después de probar_barrido.py):
    python scripts/probar_gratis.py TU_CLAVE
    python scripts/probar_gratis.py TU_CLAVE --fixture id1201285575072440
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.oddspapi.io/v4"
CAB = {"User-Agent": "Mozilla/5.0 (compatible; FullTenis-BOT_BUSCADOR/1.0)",
       "Accept": "application/json"}
RAIZ = Path(__file__).resolve().parent.parent


def pedir(ruta, **params):
    url = f"{BASE}/{ruta}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=60) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def buscar_claves(datos, claves, ruta="", salida=None):
    salida = [] if salida is None else salida
    if isinstance(datos, dict):
        for k, v in datos.items():
            if k in claves and v not in (None, ""):
                salida.append((f"{ruta}.{k}".lstrip("."), v))
            buscar_claves(v, claves, f"{ruta}.{k}", salida)
    elif isinstance(datos, list):
        for i, v in enumerate(datos[:50]):
            buscar_claves(v, claves, f"{ruta}[{i}]", salida)
    return salida


def partido_empezado():
    """Un partido ya empezado de los que bajó probar_barrido.py."""
    ahora = datetime.now(timezone.utc).isoformat()[:19]
    mejor = None
    for f in sorted((RAIZ / "barrido_crudo").glob("*.json")):
        try:
            datos = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for p in (datos if isinstance(datos, list) else []):
            ini = str(p.get("startTime") or "")[:19]
            if ini and ini <= ahora and (not mejor or ini > mejor[1]):
                mejor = (p.get("fixtureId"), ini)
    return mejor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clave")
    ap.add_argument("--fixture", help="fixtureId de un partido ya empezado")
    ap.add_argument("--casas", default="betplay,draftkings,fanduel", help="máximo 3")
    A = ap.parse_args()

    print("1) Tu cuenta (gratis)...")
    cuenta, err = pedir("account", apiKey=A.clave)
    if err:
        print(f"   ✗ {err}")
    else:
        vistos = buscar_claves(cuenta, {"request_limit", "request_count", "plan", "name",
                                        "planName", "expiresAt", "resetAt", "periodEnd"})
        for k, v in vistos:
            print(f"   {k} = {v}")
        if not vistos:
            print("   " + json.dumps(cuenta, ensure_ascii=False)[:800])

    fid, ini = (A.fixture, "?") if A.fixture else (partido_empezado() or (None, None))
    if not fid:
        sys.exit("\nSin partido empezado: ejecuta antes probar_barrido.py o pasa --fixture ID")
    print(f"\n2) Histórico (gratis) de {fid} (inicio {ini} UTC), casas {A.casas}...")
    time.sleep(1)
    hist, err = pedir("historical-odds", apiKey=A.clave, fixtureId=fid, bookmakers=A.casas)
    if err:
        sys.exit(f"   ✗ {err}")
    (RAIZ / "barrido_crudo" / "historico.json").write_text(
        json.dumps(hist, ensure_ascii=False)[:3_000_000], encoding="utf-8")
    casas = list(((hist or {}).get("bookmakers") or {}).keys())
    enlaces = buscar_claves(hist, {"fixturePath", "bookmakerFixtureId", "betslip"})
    print(f"   casas en la respuesta: {casas or 'ninguna'}")
    if enlaces:
        print(f"   ✅ SÍ trae datos de enlace ({len(enlaces)}):")
        for k, v in enlaces[:6]:
            print(f"      {k} = {v}")
    else:
        print("   ❌ No trae enlace ni número de partido de la casa (solo precios).")
    print("\nRespuesta completa en barrido_crudo/historico.json")


if __name__ == "__main__":
    main()
