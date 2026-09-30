#!/usr/bin/env python3
"""
scripts/explorar.py — Enlaces de OddsPapi contra partidos REALES de FullTenis.

Uso (desde la raíz de BOT_BUSCADOR, con las variables del servicio, incluida
ODDSPAPI_API_KEY):
    python scripts/explorar.py                       # partidos de la caché del buscador
    python scripts/explorar.py --desde-fullteni      # lee /ft-intel/fixtures en el momento
    python scripts/explorar.py --max 20 --salida informes/

Gasto en OddsPapi: 1 petición (lista de partidos) + 1 por partido emparejado,
hasta --max. Los enlaces quedan guardados en la base del buscador, así que
repetir no vuelve a gastar para los mismos partidos.

Genera:
  reporte_exploracion.md       emparejados por categoría y casas con enlace
  enlaces_para_probar.csv      una fila por (partido, casa) con columnas vacías
                               para la prueba manual en navegador LIMPIO
Después de probar a mano:
    python scripts/importar_pruebas.py enlaces_para_probar.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import httpx  # noqa: E402

from buscador import catalogo, categoria, config, db, sync  # noqa: E402
from buscador.providers import ODDSPAPI  # noqa: E402
from buscador.providers.oddspapi import CASAS, ajustar_url, emparejar  # noqa: E402
from buscador.resolver import AMBIGUO, ENCONTRADO, Partido  # noqa: E402

COLUMNAS_PRUEBA = ["deep_link (ok/fallo)",
                   "abre_sin_login (abrio/pidio_login/pidio_ubicacion/no_cargo)",
                   "evento_correcto (ok/fallo)", "navegador_limpio (si/no)",
                   "probador", "region_prueba", "notas"]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde-fullteni", action="store_true")
    ap.add_argument("--max", type=int, default=20, help="partidos a consultar en OddsPapi")
    ap.add_argument("--salida", default=".")
    args = ap.parse_args()
    if not config.ODDSPAPI_API_KEY:
        sys.exit("Falta ODDSPAPI_API_KEY.")
    dest = Path(args.salida)
    dest.mkdir(parents=True, exist_ok=True)

    conn = db.conectar()
    db.inicializar(conn)
    catalogo.sembrar(conn)
    if args.desde_fullteni:
        async with httpx.AsyncClient(timeout=config.TIMEOUT_FTR_S) as cli:
            await sync.sincronizar_una_vez(conn, cli)
    n_op = await ODDSPAPI.sincronizar_fixtures(conn)
    lista = [dict(f) for f in conn.execute("SELECT * FROM fixtures_cache ORDER BY fecha")]
    if not lista:
        sys.exit("No hay partidos de FullTenis en la caché. Usa --desde-fullteni.")

    cobertura = defaultdict(lambda: {"total": 0, "emparejado": 0, "ambiguo": 0})
    por_casa = defaultdict(int)
    filas, consultados = [], 0
    for f in lista:
        cat = f["categoria"] or categoria.OTRA
        cobertura[cat]["total"] += 1
        p = Partido(clave=f["clave"], jugador1=f["jugador1"], jugador2=f["jugador2"],
                    fecha=f["fecha"], hora_conocida=bool(f["hora_conocida"]),
                    torneo=f["torneo"] or "", categoria=cat)
        estado, ids, conf = emparejar(conn, p)
        if estado == AMBIGUO:
            cobertura[cat]["ambiguo"] += 1
        if estado != ENCONTRADO:
            continue
        cobertura[cat]["emparejado"] += 1
        if consultados >= args.max:
            continue
        consultados += 1
        try:
            enlaces = await ODDSPAPI.enlaces(conn, ids[0], "betplay")
        except Exception as e:
            print(f"  ! {f['jugador1']} vs {f['jugador2']}: {type(e).__name__}")
            continue
        for pid, slug in CASAS.items():
            if slug not in enlaces:
                continue
            por_casa[pid] += 1
            filas.append({"provider": pid, "clave": f["clave"],
                          "partido": f"{f['jugador1']} vs {f['jugador2']}",
                          "torneo": f["torneo"], "categoria": cat, "fecha": f["fecha"],
                          "url": ajustar_url(pid, enlaces[slug]),
                          **{c: "" for c in COLUMNAS_PRUEBA}})

    ahora = datetime.now(timezone.utc).isoformat(timespec="minutes")
    L = [f"# Exploración OddsPapi — {ahora}", "",
         f"{len(lista)} partidos de FullTenis · {n_op} partidos en OddsPapi · "
         f"{consultados} consultados (enlaces).", "",
         "## Emparejados por categoría", "",
         "| Categoría | Partidos FullTenis | Emparejados en OddsPapi | Ambiguos |",
         "| --- | --- | --- | --- |"]
    for cat in categoria.CATEGORIAS:
        if cat in cobertura:
            c = cobertura[cat]
            L.append(f"| {cat} | {c['total']} | {c['emparejado']} | {c['ambiguo']} |")
    L += ["", f"## Casas con enlace (de {consultados} partidos consultados)", "",
          "| Casa | Partidos con enlace |", "| --- | --- |"]
    L += [f"| {pid} | {por_casa.get(pid, 0)} |" for pid in CASAS]
    L += ["", "Emparejado = los dos jugadores, cada uno en su lado, y el mismo día (±1). "
          "Que la URL abra el partido correcto lo deciden las pruebas manuales del CSV."]
    (dest / "reporte_exploracion.md").write_text("\n".join(L), encoding="utf-8")
    with open(dest / "enlaces_para_probar.csv", "w", newline="", encoding="utf-8") as fh:
        cols = ["provider", "clave", "partido", "torneo", "categoria", "fecha", "url"] + COLUMNAS_PRUEBA
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(filas)
    print(f"{len(lista)} partidos, {consultados} consultados, {len(filas)} enlaces para probar")
    print(f"  {dest / 'reporte_exploracion.md'}")
    print(f"  {dest / 'enlaces_para_probar.csv'}")


if __name__ == "__main__":
    asyncio.run(main())
