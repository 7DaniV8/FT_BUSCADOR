#!/usr/bin/env python3
"""
scripts/probar_plataformas.py — ¿Sirve el número de partido de otro país en la
web COLOMBIANA de la misma casa?

OddsPapi trae Betano, Bwin, Stake, Codere y Betsson, pero con su web de otro
país (ro.betano.com, sports.bwin.com, stake.com, codere.es, betsson.com). Si
la casa usa el MISMO número de partido en todos sus países, basta con cambiar
el dominio para tener su enlace colombiano.

Uso (desde la raíz de BOT_BUSCADOR):
    python scripts/probar_plataformas.py TU_CLAVE
    python scripts/probar_plataformas.py TU_CLAVE --max 4

Gasto: 1 petición (lista) + 1 por partido. Crea plataformas_colombia.html:
ábrelo, pulsa cada enlace candidato y apunta cuál lleva al partido correcto.
Los formatos colombianos son HIPÓTESIS hasta que los pruebes: por eso hay
varios por casa.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ap = argparse.ArgumentParser()
ap.add_argument("clave")
ap.add_argument("--max", type=int, default=3)
A = ap.parse_args()
os.environ.update({"ODDSPAPI_API_KEY": A.clave,
                   "BUSCADOR_DB_PATH": str(Path(tempfile.mkdtemp()) / "p.db")})

from buscador import db  # noqa: E402
from buscador.providers import ODDSPAPI  # noqa: E402

CONTROL = "betplay"          # sabemos que funciona: sirve de referencia
# casa en OddsPapi -> (nombre, cómo sacar el número, enlaces colombianos candidatos)
PLATAFORMAS = {
    "betano": ("Betano", r"/(\d{6,})/?(?:[?#].*)?$", [
        "https://www.betano.co/cuotas-de-partido/e-e/{id}/",
        "https://www.betano.co/live/e-e/{id}/"]),
    "bwin": ("Bwin", r"/events/(\d+)", [
        "https://sports.bwin.co/es/sports/eventos/{id}",
        "https://sports.bwin.co/en/sports/events/{id}"]),
    "stake": ("Stake", r"/sports/(.+)$", [
        "https://stake.com.co/es/deportes/{id}",
        "https://stake.com.co/sports/{id}"]),
    "codere.es": ("Codere", r"eventId=(\d+)", [
        "https://www.codere.com.co/apuestas-deportivas?eventId={id}",
        "https://apuestas.codere.com.co/es_CO/e/{id}"]),
    "betsson": ("Betsson", r"eventId=([^&#]+)", [
        "https://www.betsson.co/apuestas-deportivas?eventId={id}"]),
}


def _nombre(n):
    if "," in n:
        a, b = [x.strip() for x in n.split(",", 1)]
        return f"{b} {a}"
    return n


async def main():
    conn = db.conectar()
    db.inicializar(conn)
    print("1) Lista de partidos de OddsPapi...")
    await ODDSPAPI.sincronizar_fixtures(conn)
    ahora = datetime.now(timezone.utc)
    desde = (ahora + timedelta(minutes=30)).isoformat()[:19]
    hasta = (ahora + timedelta(hours=30)).isoformat()[:19]
    filas = conn.execute(
        "SELECT * FROM oddspapi_fixtures WHERE tiene_cuotas=1 AND fixture_id LIKE 'id%' "
        "AND substr(inicio,1,19) BETWEEN ? AND ? ORDER BY "
        "CASE WHEN categoria IN ('atp','wta','challenger') THEN 0 ELSE 1 END, inicio",
        (desde, hasta)).fetchall()
    vistos, elegidos = set(), []
    for f in filas:                       # variedad de categorías
        if f["categoria"] not in vistos and len(elegidos) < A.max:
            vistos.add(f["categoria"])
            elegidos.append(f)
    if not elegidos:
        sys.exit("No hay partidos próximos con cuotas.")

    bm = ",".join([CONTROL, *PLATAFORMAS])
    bloques = []
    async with ODDSPAPI._cliente(20) as cli:
        for i, f in enumerate(elegidos, 1):
            partido = f"{_nombre(f['jugador1'])} vs {_nombre(f['jugador2'])}"
            print(f"\n2.{i}) {partido} — {f['torneo']} ({f['inicio'][:16]} UTC)")
            try:
                d = await ODDSPAPI._pedir(cli, "odds", fixtureId=f["fixture_id"], bookmakers=bm)
            except Exception as e:
                print(f"   ! {type(e).__name__}: {e}")
                continue
            casas = (d or {}).get("bookmakerOdds") or {}
            filas_html = []
            ctrl = (casas.get(CONTROL) or {}).get("fixturePath")
            filas_html.append(("BetPlay (referencia)", ctrl or "—", [ctrl] if ctrl else []))
            print(f"   BetPlay (referencia): {ctrl or 'no está'}")
            for slug, (nombre, patron, plantillas) in PLATAFORMAS.items():
                orig = (casas.get(slug) or {}).get("fixturePath")
                m = re.search(patron, orig or "")
                cands = [p.format(id=m.group(1)) for p in plantillas] if m else []
                filas_html.append((nombre, orig or "no está en este partido", cands))
                print(f"   {nombre:<8} OddsPapi: {orig or 'no está'}")
                for c in cands:
                    print(f"   {'':<8} probar:   {c}")
            bloques.append((partido, f["torneo"], f["inicio"][:16], filas_html))

    L = ["<!doctype html><meta charset=utf-8><title>Probar webs de Colombia</title>",
         "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;"
         "background:#12161c;color:#e6e6e6}a{color:#8ab4ff;word-break:break-all}"
         "td{padding:6px 10px;border-bottom:1px solid #2a2f37;vertical-align:top;font-size:14px}"
         ".o{opacity:.6;font-size:12px}h2{font-size:17px;margin-top:2em}</style>",
         "<h1>¿Funciona el mismo número en la web de Colombia?</h1>",
         "<p>Abre cada enlace <b>probar</b>. Si lleva al partido correcto, apunta cuál. "
         "Si abre la portada o un error, no sirve. BetPlay es la referencia (ya sabemos "
         "que funciona).</p>"]
    for partido, torneo, inicio, filas_html in bloques:
        L.append(f"<h2>{html.escape(partido)}</h2><div class=o>{html.escape(torneo)} · "
                 f"{inicio} UTC</div><table>")
        for nombre, orig, cands in filas_html:
            enl = "<br>".join(f"probar: <a href='{html.escape(c)}' target=_blank "
                              f"rel='noopener noreferrer'>{html.escape(c)}</a>" for c in cands)
            L.append(f"<tr><td><b>{html.escape(nombre)}</b></td><td><div class=o>OddsPapi: "
                     f"{html.escape(orig)}</div>{enl or '<span class=o>sin número</span>'}</td></tr>")
        L.append("</table>")
    salida = RAIZ / "plataformas_colombia.html"
    salida.write_text("\n".join(L), encoding="utf-8")
    print(f"\nAbre {salida} y prueba cada enlace.")


if __name__ == "__main__":
    asyncio.run(main())
