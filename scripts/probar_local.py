#!/usr/bin/env python3
"""
scripts/probar_local.py — Prueba LOCAL del buscador con OddsPapi real.

No necesita Railway ni FullTenis. Usa una base local (local_prueba.db) y pasa
por el mismo camino que producción: /api/resolver de la app, emparejamiento,
petición de enlaces, comprobación de dominios y ajuste de BetMGM.

Uso (desde la raíz de BOT_BUSCADOR):
    python scripts/probar_local.py TU_CLAVE
        -> elige 5 partidos próximos de OddsPapi (uno por categoría)
    python scripts/probar_local.py TU_CLAVE --max 3
    python scripts/probar_local.py TU_CLAVE --partido "Eduardo Ribeiro" "Pedro Sakamoto" 2026-09-30
        -> un partido escrito a mano, como lo tendría FullTenis (prueba el emparejamiento)

Gasto en OddsPapi: 1 petición (lista) + 1 por partido. Repetir con los mismos
partidos no vuelve a gastar: los enlaces quedan en local_prueba.db.

Resultado: en pantalla y en enlaces_local.html (ábrelo y pulsa cada enlace).
"""
from __future__ import annotations

import argparse
import asyncio
import html
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))


def _args():
    ap = argparse.ArgumentParser()
    ap.add_argument("clave", help="clave de OddsPapi")
    ap.add_argument("--max", type=int, default=5, help="partidos a probar (elegidos de OddsPapi)")
    ap.add_argument("--partido", nargs=3, metavar=("JUGADOR1", "JUGADOR2", "FECHA"),
                    help="un partido escrito a mano (FECHA = AAAA-MM-DD)")
    ap.add_argument("--db", default=str(RAIZ / "local_prueba.db"))
    return ap.parse_args()


A = _args()
# Configuración de prueba ANTES de importar el buscador.
os.environ.update({
    "ODDSPAPI_API_KEY": A.clave,
    "BUSCADOR_DB_PATH": A.db,
    "BUSCADOR_TOKEN_SECRET": "solo-para-prueba-local",
    "ALLOWED_ORIGINS": "http://localhost",
    "SYNC_ACTIVO": "0",
    "FTR_SERVICE_URL": "http://localhost",
    "FTR_LECTURA_SECRET": "no-se-usa-en-local",
    "TIMEOUT_PROVIDER_S": "15",
})

from fastapi.testclient import TestClient  # noqa: E402

from buscador import app as app_mod, catalogo, claves, db, sync  # noqa: E402
from buscador.providers import ODDSPAPI  # noqa: E402
from buscador.providers.oddspapi import CASAS  # noqa: E402
from buscador.token import emitir  # noqa: E402

ICONO = {"ENCONTRADO": "✅", "NO_ENCONTRADO": "·", "AMBIGUO": "🟡", "ERROR": "⛔",
         "PROVIDER_PENDING": "⏳"}


def _nombre(n: str) -> str:
    """'Ribeiro, Eduardo' -> 'Eduardo Ribeiro' (como suele venir de FullTenis)."""
    if "," in n:
        ap, nom = [x.strip() for x in n.split(",", 1)]
        return f"{nom} {ap}".strip()
    return n


def _elegir_de_oddspapi(conn, maximo: int) -> list[dict]:
    desde = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()[:19]
    hasta = (datetime.now(timezone.utc) + timedelta(hours=30)).isoformat()[:19]
    filas = conn.execute(
        "SELECT * FROM oddspapi_fixtures WHERE tiene_cuotas=1 AND fixture_id LIKE 'id%' "
        "AND substr(inicio,1,19) BETWEEN ? AND ? ORDER BY inicio", (desde, hasta)).fetchall()
    vistos, elegidos = set(), []
    for f in filas:                                   # uno por categoría primero
        if f["categoria"] not in vistos:
            vistos.add(f["categoria"])
            elegidos.append(f)
    for f in filas:
        if len(elegidos) >= maximo:
            break
        if f not in elegidos:
            elegidos.append(f)
    return [{"j1": _nombre(f["jugador1"]), "j2": _nombre(f["jugador2"]), "fecha": f["inicio"],
             "torneo": f["torneo"], "cat": f["categoria"]} for f in elegidos[:maximo]]


def main():
    conn = db.conectar()
    db.inicializar(conn)
    catalogo.sembrar(conn)
    print("1) Lista de partidos de OddsPapi...")
    n = asyncio.run(ODDSPAPI.sincronizar_fixtures(conn))
    print(f"   {n} partidos guardados (sin dobles ni simulados)\n")

    if A.partido:
        partidos = [{"j1": A.partido[0], "j2": A.partido[1], "fecha": A.partido[2],
                     "torneo": "", "cat": "a mano"}]
    else:
        partidos = _elegir_de_oddspapi(conn, A.max)
    if not partidos:
        sys.exit("No hay partidos próximos con cuotas en OddsPapi ahora mismo.")

    cli = TestClient(app_mod.app)
    H = {"Authorization": "Bearer " + emitir("solo-para-prueba-local", "local", "local", "admin")}
    resultados = []
    for i, p in enumerate(partidos, 1):
        fid = f"local-{i}-{p['j1']}-{p['j2']}"
        genero = "F" if any(x in (p["cat"] or "") for x in ("women", "wta")) else "M"
        sync.guardar_fixture(conn, {"fixture_id": fid, "fecha": p["fecha"], "jugador1": p["j1"],
                                    "jugador2": p["j2"], "torneo": p["torneo"], "genero": genero},
                             "fixtures")
        conn.commit()
        clave = claves.clave_partido(fid, p["fecha"], p["j1"], p["j2"])
        print(f"2.{i}) {p['j1']} vs {p['j2']} — {p['torneo'] or ''} [{p['cat']}] {p['fecha'][:16]}")
        fila = {**p, "casas": []}
        for pid in CASAS:
            r = cli.get("/api/resolver", params={"clave": clave, "provider": pid}, headers=H).json()
            est = r.get("estado", "?")
            print(f"     {ICONO.get(est, '?')} {pid:<14} {est:<14} {r.get('url') or r.get('detalle') or ''}")
            fila["casas"].append((pid, est, r.get("url"), r.get("detalle")))
        resultados.append(fila)
        print()

    total = sum(1 for f in resultados for c in f["casas"] if c[1] == "ENCONTRADO")
    print(f"Enlaces encontrados: {total} en {len(resultados)} partidos")
    for pid in CASAS:
        k = sum(1 for f in resultados for c in f["casas"] if c[0] == pid and c[1] == "ENCONTRADO")
        print(f"  {pid:<14} {k}/{len(resultados)}")

    L = ["<!doctype html><meta charset=utf-8><title>BOT BUSCADOR — prueba local</title>",
         "<style>body{font-family:sans-serif;max-width:900px;margin:2em auto}"
         "td{padding:4px 10px}h3{margin-top:1.6em}</style>",
         "<h1>Prueba local — enlaces de OddsPapi</h1>",
         "<p>Abre cada enlace (mejor en ventana de incógnito) y apunta: ¿abre el partido "
         "correcto? ¿pide iniciar sesión?</p>"]
    for f in resultados:
        L.append(f"<h3>{html.escape(f['j1'])} vs {html.escape(f['j2'])}</h3>"
                 f"<div>{html.escape(f['torneo'] or '')} · {html.escape(f['fecha'][:16])}</div><table>")
        for pid, est, url, det in f["casas"]:
            celda = (f"<a href='{html.escape(url)}' target=_blank>{html.escape(url)}</a>" if url
                     else html.escape(det or ""))
            L.append(f"<tr><td>{ICONO.get(est, '?')} {pid}</td><td>{est}</td><td>{celda}</td></tr>")
        L.append("</table>")
    salida = RAIZ / "enlaces_local.html"
    salida.write_text("\n".join(L), encoding="utf-8")
    print(f"\nAbre {salida} y pulsa cada enlace.")


if __name__ == "__main__":
    main()
