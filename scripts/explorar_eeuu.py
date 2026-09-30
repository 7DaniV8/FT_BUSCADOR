#!/usr/bin/env python3
"""
scripts/explorar_eeuu.py — ¿Qué da OddsPapi de cada casa de EE. UU.?

Para cada casa estadounidense muestra, partido a partido:
  - fixturePath          el enlace que da OddsPapi (si lo da)
  - bookmakerFixtureId   el NÚMERO de partido de la propia casa. Aunque no haya
                         enlace, con el número a veces se construye a mano
                         (como se hizo con Kalshi)
  - candidato NC         el enlace ajustado a Carolina del Norte, si se sabe

Uso (desde la raíz de BOT_BUSCADOR):
    python scripts/explorar_eeuu.py TU_CLAVE
    python scripts/explorar_eeuu.py TU_CLAVE --max 6

Gasto: 1 petición (lista) + 1 por partido, con pausa de 2 s entre ellas para
no chocar con el límite de OddsPapi (el error 429). Crea eeuu_oddspapi.html.
OJO: las webs de EE. UU. suelen bloquear el acceso desde fuera del país; para
comprobar los enlaces hace falta una VPN de EE. UU. o alguien en NC.
"""
from __future__ import annotations

import argparse
import asyncio
import html
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

ap = argparse.ArgumentParser()
ap.add_argument("clave")
ap.add_argument("--max", type=int, default=4)
A = ap.parse_args()
os.environ.update({"ODDSPAPI_API_KEY": A.clave, "ODDSPAPI_ESTADO_US": "nc",
                   "BUSCADOR_DB_PATH": str(Path(tempfile.mkdtemp()) / "e.db")})

from buscador import db  # noqa: E402
from buscador.providers import ODDSPAPI  # noqa: E402
from buscador.providers.oddspapi import ajustar_url  # noqa: E402

# clave en OddsPapi -> (nombre, provider del catálogo si existe, estado en NC)
CASAS_US = {
    "draftkings": ("DraftKings", "draftkings_nc", "activa en el BOT"),
    "fanduel": ("FanDuel", "fanduel_nc", "activa en el BOT"),
    "betmgm": ("BetMGM", "betmgm_nc", "activa en el BOT"),
    "bet365": ("bet365", None, "pendiente"),
    "bet365-nj": ("bet365 (NJ)", None, "pendiente"),
    "fanatics": ("Fanatics", None, "pendiente"),
    "espnbet": ("ESPN BET / theScore", None, "pendiente"),
    "thescore": ("theScore Bet", None, "pendiente"),
    "caesars": ("Caesars", None, "pendiente"),
    "williamhill": ("Caesars (William Hill)", None, "pendiente"),
    "betrivers": ("BetRivers", None, "no autorizada en NC"),
    "underdog": ("Underdog", None, "próximamente"),
    "hardrockbet": ("Hard Rock Bet", None, "fuera del catálogo"),
    "ballybet": ("Bally Bet", None, "fuera del catálogo"),
    "betparx": ("betPARX", None, "fuera del catálogo"),
    "fliff": ("Fliff", None, "fuera del catálogo"),
}


def candidato_nc(slug: str, url: str | None) -> str:
    """Enlace ajustado a NC cuando se conoce la regla. Hipótesis salvo BetMGM."""
    if not url:
        return ""
    if slug in ("draftkings", "fanduel"):
        return url                          # mismo dominio en todo EE. UU.
    if slug == "betmgm":
        return ajustar_url("betmgm_nc", url)
    if slug in ("bet365", "bet365-nj") and "bet365.com/#/" in url:
        return url.replace("https://www.bet365.com/", "https://www.nc.bet365.com/")
    return ""


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
    filas = conn.execute(
        "SELECT * FROM oddspapi_fixtures WHERE tiene_cuotas=1 AND fixture_id LIKE 'id%' "
        "AND substr(inicio,1,19) BETWEEN ? AND ? ORDER BY "
        "CASE categoria WHEN 'atp' THEN 0 WHEN 'wta' THEN 1 WHEN 'challenger' THEN 2 ELSE 3 END, inicio",
        ((ahora + timedelta(minutes=30)).isoformat()[:19],
         (ahora + timedelta(hours=30)).isoformat()[:19])).fetchall()
    vistos, elegidos = set(), []
    for f in filas:
        if f["categoria"] not in vistos and len(elegidos) < A.max:
            vistos.add(f["categoria"])
            elegidos.append(f)
    for f in filas:                           # completar si hay pocas categorías
        if len(elegidos) >= A.max:
            break
        if f not in elegidos:
            elegidos.append(f)
    if not elegidos:
        sys.exit("No hay partidos próximos con cuotas.")

    cobertura = defaultdict(lambda: {"enlace": 0, "numero": 0, "aparece": 0})
    bloques = []
    async with ODDSPAPI._cliente(20) as cli:
        for i, f in enumerate(elegidos, 1):
            if i > 1:
                await asyncio.sleep(2)            # evita el 429
            partido = f"{_nombre(f['jugador1'])} vs {_nombre(f['jugador2'])}"
            print(f"\n2.{i}) {partido} — {f['torneo']}")
            try:
                d = await ODDSPAPI._pedir(cli, "odds", fixtureId=f["fixture_id"],
                                          bookmakers=",".join(CASAS_US))
            except Exception as e:
                print(f"   ! {type(e).__name__}: {e}")
                continue
            casas = (d or {}).get("bookmakerOdds") or {}
            filas_p = []
            for slug, (nombre, _, _) in CASAS_US.items():
                info = casas.get(slug)
                if not isinstance(info, dict):
                    filas_p.append((slug, nombre, None, None, ""))
                    continue
                url, num = info.get("fixturePath"), info.get("bookmakerFixtureId")
                cobertura[slug]["aparece"] += 1
                cobertura[slug]["enlace"] += bool(url)
                cobertura[slug]["numero"] += bool(num)
                cand = candidato_nc(slug, url)
                filas_p.append((slug, nombre, url, num, cand))
                print(f"   {nombre:<24} enlace={url or '—'}  número={num or '—'}")
            bloques.append((partido, f["torneo"], f["inicio"][:16], filas_p))

    n = len(bloques)
    L = ["<!doctype html><meta charset=utf-8><title>Casas de EE. UU. en OddsPapi</title>",
         "<style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:2em auto;"
         "background:#12161c;color:#e6e6e6}a{color:#8ab4ff;word-break:break-all}"
         "td,th{padding:6px 10px;border-bottom:1px solid #2a2f37;vertical-align:top;"
         "font-size:13px;text-align:left}.o{opacity:.55}.ok{color:#3fb950}.no{color:#f85149}"
         "h2{font-size:16px;margin-top:2em}</style>",
         "<h1>Casas de EE. UU. en OddsPapi</h1>",
         "<p class=o>Las webs de EE. UU. suelen bloquear el acceso desde fuera del país: para "
         "comprobar los enlaces hace falta una VPN de EE. UU. o alguien en Carolina del Norte.</p>",
         f"<h2>Resumen ({n} partidos)</h2><table><tr><th>Casa</th><th>Estado en el BOT</th>"
         "<th>Aparece</th><th>Con enlace</th><th>Con número de partido</th></tr>"]
    for slug, (nombre, _, estado) in CASAS_US.items():
        c = cobertura[slug]
        cl = "ok" if c["enlace"] else ("" if c["numero"] else "no")
        L.append(f"<tr><td><b>{html.escape(nombre)}</b> <span class=o>{slug}</span></td>"
                 f"<td>{estado}</td><td>{c['aparece']}/{n}</td><td class={cl}>{c['enlace']}/{n}</td>"
                 f"<td>{c['numero']}/{n}</td></tr>")
    L.append("</table>")
    for partido, torneo, inicio, filas_p in bloques:
        L.append(f"<h2>{html.escape(partido)}</h2><div class=o>{html.escape(torneo)} · {inicio} UTC"
                 "</div><table><tr><th>Casa</th><th>Enlace de OddsPapi</th><th>Número de la casa</th>"
                 "<th>Candidato NC</th></tr>")
        for slug, nombre, url, num, cand in filas_p:
            if url is None and num is None:
                L.append(f"<tr class=o><td>{html.escape(nombre)}</td><td colspan=3>no aparece en "
                         "este partido</td></tr>")
                continue
            a = (lambda u: f"<a href='{html.escape(u)}' target=_blank rel='noopener noreferrer'>"
                           f"{html.escape(u)}</a>" if u else "<span class=o>—</span>")
            L.append(f"<tr><td><b>{html.escape(nombre)}</b></td><td>{a(url)}</td>"
                     f"<td>{html.escape(str(num or '—'))}</td><td>{a(cand)}</td></tr>")
        L.append("</table>")
    salida = RAIZ / "eeuu_oddspapi.html"
    salida.write_text("\n".join(L), encoding="utf-8")
    print(f"\nAbre {salida}")


if __name__ == "__main__":
    asyncio.run(main())
