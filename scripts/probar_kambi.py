#!/usr/bin/env python3
"""
scripts/probar_kambi.py — Enlaces GRATIS de BetPlay y Rushbet para partidos EN JUEGO.

BetPlay y Rushbet funcionan sobre la plataforma Kambi: su web lee los partidos
de un JSON público (sin clave, sin sesión). Una sola petición trae TODOS los
partidos de tenis en juego con su número de evento, y ese número sirve para
las dos casas:
    BetPlay: https://tienda.betplay.com.co/apuestas#event/<ID>
    Rushbet: https://www.rushbet.co/?page=sportsbook#event/<ID>

No es una API oficial: puede cambiar sin aviso. Úsese con moderación.

CÓMO SACAR EL CÓDIGO DE OPERADOR (una vez, 1 minuto):
  1. Abre https://tienda.betplay.com.co/apuestas en Chrome.
  2. F12 → pestaña Network (Red) → en el filtro escribe:  kambicdn
  3. Recarga la página (F5). Pulsa cualquier petición de la lista y mira su
     URL. Tendrá esta forma:
        https://....kambicdn.com/offering/v2018/XXXXX/...?lang=es_CO&market=CO
     XXXXX es el código de operador. Apunta también el host, y lang y market.
  4. Lo mismo en https://www.rushbet.co/?page=sportsbook (será otro código).

Uso (desde la raíz de BOT_BUSCADOR):
    python scripts/probar_kambi.py XXXXX
    python scripts/probar_kambi.py XXXXX --host eu-offering-api.kambicdn.com --lang es_CO --market CO
Crea kambi_en_vivo.html con los enlaces para abrirlos.
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
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CAB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
       "Accept": "application/json"}
HOSTS = ["eu-offering-api.kambicdn.com", "eu1.offering-api.kambicdn.com",
         "us1.offering-api.kambicdn.com"]
ENLACES = {"BetPlay": "https://tienda.betplay.com.co/apuestas#event/{id}",
           "Rushbet": "https://www.rushbet.co/?page=sportsbook#event/{id}"}


def pedir(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=20) as r:
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def eventos(datos):
    """Partidos del JSON de Kambi (listView): events[].event."""
    for e in (datos or {}).get("events") or []:
        ev = (e or {}).get("event") or {}
        if not ev.get("id"):
            continue
        nombre = ev.get("name") or f"{ev.get('homeName', '')} - {ev.get('awayName', '')}"
        yield {"id": ev["id"], "nombre": nombre, "torneo": ev.get("group", ""),
               "estado": ev.get("state", ""), "inicio": ev.get("start", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("operador", help="código de operador de Kambi (ver instrucciones arriba)")
    ap.add_argument("--host", help="host de Kambi visto en el navegador")
    ap.add_argument("--lang", default="es_CO")
    ap.add_argument("--market", default="CO")
    A = ap.parse_args()

    q = urllib.parse.urlencode({"lang": A.lang, "market": A.market, "useCombined": "true"})
    ruta = f"/offering/v2018/{A.operador}/listView/tennis/all/all/all/in-play.json?{q}"
    datos, usado = None, None
    for host in ([A.host] if A.host else HOSTS):
        print(f"Probando https://{host}{ruta.split('?')[0]} ...")
        datos, err = pedir(f"https://{host}{ruta}")
        if datos is not None:
            usado = host
            break
        print(f"   ✗ {err}")
        time.sleep(1)
    if datos is None:
        sys.exit("\nNo respondió ningún host. Revisa el código de operador y pásame el host, "
                 "lang y market que viste en el navegador.")

    lista = list(eventos(datos))
    print(f"\n✓ {usado}: {len(lista)} partidos de tenis EN JUEGO (1 petición, gratis)\n")
    for ev in lista[:15]:
        print(f"  {ev['nombre']:<45} {ev['torneo'][:30]:<30} id={ev['id']}")
    if len(lista) > 15:
        print(f"  ... y {len(lista) - 15} más")
    if not lista:
        print("  (0 partidos: puede que ahora no haya tenis en juego, o que el operador no sea "
              "el correcto; los primeros caracteres de la respuesta:)")
        print("  " + json.dumps(datos, ensure_ascii=False)[:500])

    L = ["<!doctype html><meta charset=utf-8><title>Kambi en vivo</title>",
         "<style>body{font-family:system-ui,sans-serif;max-width:1100px;margin:2em auto;"
         "background:#12161c;color:#e6e6e6}a{color:#8ab4ff}td,th{padding:6px 10px;"
         "border-bottom:1px solid #2a2f37;text-align:left;font-size:14px}.o{opacity:.6}</style>",
         f"<h1>Tenis en juego — Kambi ({html.escape(A.operador)})</h1>",
         f"<p class=o>{len(lista)} partidos · 1 petición gratuita a {html.escape(usado)}. "
         "Abre los enlaces y comprueba que llevan al partido correcto.</p>",
         "<table><tr><th>Partido</th><th>Torneo</th><th>BetPlay</th><th>Rushbet</th></tr>"]
    for ev in lista:
        cel = [f"<a href='{html.escape(p.format(id=ev['id']))}' target=_blank "
               f"rel='noopener noreferrer'>abrir</a>" for p in ENLACES.values()]
        L.append(f"<tr><td><b>{html.escape(ev['nombre'])}</b></td>"
                 f"<td class=o>{html.escape(str(ev['torneo']))}</td><td>{cel[0]}</td><td>{cel[1]}</td></tr>")
    L.append("</table>")
    salida = RAIZ / "kambi_en_vivo.html"
    salida.write_text("\n".join(L), encoding="utf-8")
    print(f"\nAbre {salida}")


if __name__ == "__main__":
    main()
