#!/usr/bin/env python3
"""
scripts/ver_bet365.py — ¿Abren el partido los enlaces de bet365 que da OddsPapi?

Junta la lista de partidos (nombres) con los enlaces de bet365 y crea
bet365_enlaces.html con cada partido y su enlace YA adaptado a tu estado
(www.<estado>.bet365.com), para abrirlos con un clic con la VPN en ese estado.

    python scripts/ver_bet365.py "TU_CLAVE"                (estado nc por defecto)
    python scripts/ver_bet365.py "TU_CLAVE" --estado nj

Gasto: 2 peticiones (lista de partidos + enlaces de bet365 de un lote de torneos).
"""
from __future__ import annotations

import argparse
import html
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BASE = "https://api.oddspapi.io/v4"
CAB = {"User-Agent": "Mozilla/5.0 (compatible; FullTenis-BOT_BUSCADOR/1.0)", "Accept": "application/json"}
RAIZ = Path(__file__).resolve().parent.parent


def pedir(ruta, **params):
    url = f"{BASE}/{ruta}?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=90) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def recorrer(datos):
    if isinstance(datos, dict):
        if "fixtureId" in datos and "bookmakerOdds" in datos:
            yield datos
        for v in datos.values():
            yield from recorrer(v)
    elif isinstance(datos, list):
        for v in datos:
            yield from recorrer(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clave")
    ap.add_argument("--estado", default="nc", help="estado de bet365 de tu VPN (nc, nj, az, il...)")
    A = ap.parse_args()
    est = A.estado.lower()[:2]

    hoy = date.today()
    fx, err = pedir("fixtures", apiKey=A.clave, sportId=12,
                    **{"from": hoy.isoformat(), "to": (hoy + timedelta(days=1)).isoformat()})
    if err or not isinstance(fx, list):
        sys.exit(f"No llegó la lista de partidos: {err}")
    validos = [f for f in fx if "simulated" not in str(f.get("categorySlug"))
               and "/" not in str(f.get("participant1Name"))]
    info = {f.get("fixtureId"): f for f in validos}
    torneos = [str(t) for t, _ in Counter(f.get("tournamentId") for f in validos
                                          if f.get("tournamentId")).most_common()][:5]
    time.sleep(1.5)
    datos, err = pedir("odds-by-tournaments", apiKey=A.clave, bookmaker="bet365",
                       tournamentIds=",".join(torneos), oddsFormat="decimal")
    if err:
        sys.exit(f"No llegaron los enlaces de bet365: {err}")

    ahora = datetime.now(timezone.utc)
    filas = []
    for p in recorrer(datos):
        b = (p.get("bookmakerOdds") or {}).get("bet365") or {}
        url = b.get("fixturePath") if isinstance(b, dict) else None
        f = info.get(p.get("fixtureId")) or {}
        if not url or not f:
            continue
        url_est = url.replace("https://www.bet365.com/", f"https://www.{est}.bet365.com/")
        ini = str(f.get("startTime") or f.get("trueStartTime") or "")
        try:
            empezado = datetime.fromisoformat(ini.replace("Z", "+00:00")) <= ahora
        except ValueError:
            empezado = False
        tipo = "EN VIVO (IP)" if "/IP/" in url else "previo (AC)"
        filas.append((ini, f"{f.get('participant1Name')} vs {f.get('participant2Name')}",
                      str(f.get("tournamentName") or f.get("categorySlug") or ""), tipo,
                      "ya empezó" if empezado else "aún no", url_est))
    filas.sort()
    print(f"{len(filas)} partidos con enlace de bet365 (adaptado a www.{est}.bet365.com):\n")
    for ini, partido, torneo, tipo, emp, u in filas[:15]:
        print(f"  {ini[:16]}  {partido}  [{torneo}] · {tipo} · {emp}\n      {u}")
    pagina = RAIZ / "bet365_enlaces.html"
    L = ["<!doctype html><meta charset=utf-8><title>Enlaces bet365 (OddsPapi)</title>",
         "<style>body{font-family:system-ui,sans-serif;background:#12161c;color:#e6e6e6;max-width:1100px;"
         "margin:2em auto}a{color:#8ab4ff;word-break:break-all}td,th{padding:6px 10px;"
         "border-bottom:1px solid #2a2f37;text-align:left;font-size:14px}</style>",
         f"<h1>bet365: ¿abre el partido? (www.{est}.bet365.com)</h1>",
         "<p>Ábrelos con la VPN en ese estado. Para cada uno, anota si abre EL PARTIDO, "
         "la sección de tenis o la portada.</p>",
         "<table><tr><th>Hora (UTC)</th><th>Partido</th><th>Torneo</th><th>Tipo</th><th>¿Empezó?</th>"
         "<th>Enlace</th></tr>"]
    for ini, partido, torneo, tipo, emp, u in filas:
        L.append(f"<tr><td>{html.escape(ini[:16])}</td><td>{html.escape(partido)}</td>"
                 f"<td>{html.escape(torneo)}</td><td>{tipo}</td><td>{emp}</td>"
                 f"<td><a href='{html.escape(u)}' target=_blank rel='noopener noreferrer'>abrir</a></td></tr>")
    L.append("</table>")
    pagina.write_text("\n".join(L), encoding="utf-8")
    print(f"\nPágina con todos los enlaces: {pagina}")
    try:
        webbrowser.open(pagina.as_uri())
    except Exception:
        pass


if __name__ == "__main__":
    main()
