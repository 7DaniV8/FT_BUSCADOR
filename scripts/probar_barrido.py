#!/usr/bin/env python3
"""
scripts/probar_barrido.py — ¿Trae /odds-by-tournaments el ENLACE de cada casa
para TODOS los partidos con una sola petición por casa?

Contexto: el flujo real empieza con un MTO, así que el partido SIEMPRE está en
juego cuando se busca. Con el plan gratuito OddsPapi no da enlaces en juego:
hay que tenerlos guardados ANTES. Pedirlos partido a partido cuesta ~1
petición por partido; por torneos serían ~1 petición por casa para todos.

Uso (desde la raíz de BOT_BUSCADOR):
    python scripts/probar_barrido.py TU_CLAVE
    python scripts/probar_barrido.py TU_CLAVE --casas betplay,draftkings,betano

OddsPapi admite como máximo 5 torneos por petición: se mandan lotes de 5,
empezando por los torneos con más partidos. Por defecto, 1 lote por casa.

Gasto: 1 petición (lista) + casas × lotes (por defecto 2 × 1 = 3 en total).
Guarda las respuestas en barrido_crudo/ para revisarlas.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

BASE = "https://api.oddspapi.io/v4"
CAB = {"User-Agent": "Mozilla/5.0 (compatible; FullTenis-BOT_BUSCADOR/1.0)",
       "Accept": "application/json"}
RAIZ = Path(__file__).resolve().parent.parent


def pedir(ruta, **params):
    url = f"{BASE}/{ruta}?" + urllib.parse.urlencode(params)
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=90) as r:
            cuerpo = r.read()
            return json.loads(cuerpo), len(cuerpo), time.time() - t0, None
    except urllib.error.HTTPError as e:
        return None, 0, time.time() - t0, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:
        return None, 0, time.time() - t0, f"{type(e).__name__}: {e}"


def recorrer_partidos(datos):
    """La forma exacta de la respuesta no está documentada con detalle: se
    buscan objetos con fixtureId y bookmakerOdds en cualquier nivel."""
    if isinstance(datos, dict):
        if "fixtureId" in datos and "bookmakerOdds" in datos:
            yield datos
        for v in datos.values():
            yield from recorrer_partidos(v)
    elif isinstance(datos, list):
        for v in datos:
            yield from recorrer_partidos(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clave")
    ap.add_argument("--casas", default="betplay,draftkings")
    ap.add_argument("--lotes", type=int, default=1, help="lotes de 5 torneos por casa")
    A = ap.parse_args()
    dest = RAIZ / "barrido_crudo"
    dest.mkdir(exist_ok=True)

    print("1) Lista de partidos de tenis (hoy y mañana)...")
    hoy = date.today()
    fx, _, _, err = pedir("fixtures", apiKey=A.clave, sportId=12, **{
        "from": hoy.isoformat(), "to": (hoy + timedelta(days=1)).isoformat()})
    if err or not isinstance(fx, list):
        sys.exit(f"   no llegó la lista: {err}")
    validos = [f for f in fx if "simulated" not in str(f.get("categorySlug"))
               and "/" not in str(f.get("participant1Name"))]
    por_torneo = Counter(f.get("tournamentId") for f in validos if f.get("tournamentId"))
    cat_de = {f.get("fixtureId"): f.get("categorySlug") for f in validos}
    torneos = [str(t) for t, _ in por_torneo.most_common()]
    lotes = [torneos[i:i + 5] for i in range(0, len(torneos), 5)]
    usar = lotes[:max(1, A.lotes)]
    cubiertos = sum(por_torneo[int(t)] if t.isdigit() else por_torneo[t] for l in usar for t in l)
    print(f"   {len(validos)} partidos individuales en {len(torneos)} torneos "
          f"= {len(lotes)} lotes de 5")
    print(f"   se prueban {len(usar)} lote(s): {cubiertos} partidos de la lista")

    for casa in [c.strip() for c in A.casas.split(",") if c.strip()]:
        time.sleep(1.5)
        print(f"\n2) {casa}: {len(usar)} petición(es) de 5 torneos...")
        partidos, tam, seg, err = [], 0, 0.0, None
        for n, lote in enumerate(usar, 1):
            if n > 1:
                time.sleep(1.5)
            datos, t_, s_, err = pedir("odds-by-tournaments", apiKey=A.clave, bookmaker=casa,
                                       tournamentIds=",".join(lote), oddsFormat="decimal")
            if err:
                print(f"   ✗ lote {n}: {err}")
                break
            tam, seg = tam + t_, seg + s_
            (dest / f"{casa}_lote{n}.json").write_text(
                json.dumps(datos, ensure_ascii=False)[:5_000_000], encoding="utf-8")
            partidos += list(recorrer_partidos(datos))
        if err and not partidos:
            continue
        con_enlace, por_cat, ejemplos = 0, defaultdict(lambda: [0, 0]), []
        for p in partidos:
            info = (p.get("bookmakerOdds") or {}).get(casa) or {}
            url = info.get("fixturePath") if isinstance(info, dict) else None
            cat = cat_de.get(p.get("fixtureId"), "?")
            por_cat[cat][0] += 1
            if url:
                con_enlace += 1
                por_cat[cat][1] += 1
                if len(ejemplos) < 3:
                    ejemplos.append((p.get("fixtureId"), url))
        print(f"   ✓ {tam / 1024:.0f} KB en {seg:.1f} s · {len(partidos)} partidos · "
              f"{con_enlace} con enlace")
        for cat, (n, e) in sorted(por_cat.items(), key=lambda x: -x[1][0]):
            print(f"     {cat:<22} {e}/{n} con enlace")
        for fid, url in ejemplos:
            print(f"     ej. {fid}: {url}")
        if not partidos:
            print("   (forma de respuesta no reconocida; primeros caracteres:)")
            print("   " + json.dumps(datos, ensure_ascii=False)[:600])
    casas_bot = 7
    print(f"\nCoste de un barrido COMPLETO por torneos: {len(lotes)} lotes × {casas_bot} casas "
          f"= {len(lotes) * casas_bot} peticiones (partido a partido: ~{len(validos)}).")
    print(f"Respuestas completas en {dest}")


if __name__ == "__main__":
    main()
