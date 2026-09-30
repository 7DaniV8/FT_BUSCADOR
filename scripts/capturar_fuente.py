#!/usr/bin/env python3
"""
scripts/capturar_fuente.py — Captura y analiza una fuente GRATUITA de partidos.

Sirve para escribir cada proveedor del BOT sobre datos REALES. Guarda la
respuesta en capturas/ y dice si encontró partidos (nombres + número de evento).

    python scripts/capturar_fuente.py kalshi
    python scripts/capturar_fuente.py polymarket
    python scripts/capturar_fuente.py kambi CODIGO_OPERADOR [--host H --lang es_CO --market CO]
    python scripts/capturar_fuente.py url "https://....json" --nombre draftkings

Modo url: la URL que encontraste con F12 → Network → Fetch/XHR en la sección de
tenis EN VIVO de la casa (clic derecho → Copy → Copy URL). NO pegues "as cURL"
ni encabezados: llevan tus cookies. Si desde aquí responde, el BOT también
podrá leerla (desde el mismo país); si da 403, la casa bloquea programas.

Al terminar, comprime la carpeta capturas/ y súbela.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DEST = RAIZ / "capturas"
CAB = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
       "Accept": "application/json, text/plain, */*"}
TENIS = re.compile(r"\b(atp|wta|itf|utr|challenger|tennis|tenis|m15|m25|w15|w35|w50|w75)\b", re.I)


def pedir(url, intentos=1):
    t0 = time.time()
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=CAB), timeout=30) as r:
            cuerpo = r.read()
            return json.loads(cuerpo), f"HTTP {r.status} · {len(cuerpo) / 1024:.0f} KB · {time.time() - t0:.1f} s"
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} (la fuente rechazó la petición)"
    except json.JSONDecodeError:
        return None, "respondió, pero no es JSON"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def guardar(nombre, datos, nota=""):
    DEST.mkdir(exist_ok=True)
    marca = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    ruta = DEST / f"{nombre}_{marca}.json"
    ruta.write_text(json.dumps({"_nota": nota, "_capturado": marca, "datos": datos},
                               ensure_ascii=False)[:8_000_000], encoding="utf-8")
    return ruta


# ── Análisis genérico: ¿hay partidos con nombres y número? ─────────────────
CLAVES_ID = ("id", "eventid", "event_id", "eventticker", "event_ticker", "fixtureid", "slug", "ticker")
CLAVES_NOMBRE = ("name", "title", "homename", "awayname", "participant", "competitor", "team",
                 "player", "home", "away", "runner", "subtitle", "sub_title")


def _texto_partido(d: dict) -> str:
    trozos = []
    for k, v in d.items():
        if isinstance(v, str) and any(c in k.lower() for c in CLAVES_NOMBRE):
            trozos.append(v)
    return " | ".join(trozos)[:160]


def _id(d: dict):
    for k, v in d.items():
        if k.lower().replace("-", "") in CLAVES_ID and isinstance(v, (str, int)) and str(v):
            return k, v
    return None


def analizar(datos, maximo=8):
    """Busca objetos con un número/identificador y texto que parezca un partido
    ('A vs B', 'A - B' o campos home/away)."""
    hallados, vistos = [], 0

    def recorrer(x, ruta):
        nonlocal vistos
        if len(hallados) >= 400:
            return
        if isinstance(x, dict):
            vistos += 1
            ident, texto = _id(x), _texto_partido(x)
            if ident and texto and (" vs" in texto.lower() or " - " in texto or " v " in texto.lower()
                                    or any(k.lower() in ("homename", "awayname") for k in x)):
                hallados.append((ruta, ident, texto, sorted(x.keys())[:25]))
            for k, v in x.items():
                recorrer(v, f"{ruta}.{k}")
        elif isinstance(x, list):
            for i, v in enumerate(x[:2000]):
                recorrer(v, f"{ruta}[]")

    recorrer(datos, "$")
    rutas = {}
    for r, *_ in hallados:
        rutas[r] = rutas.get(r, 0) + 1
    print(f"   objetos revisados: {vistos} · posibles partidos: {len(hallados)}")
    for r, n in sorted(rutas.items(), key=lambda x: -x[1])[:3]:
        print(f"   ruta más frecuente: {r}  ({n})")
    tenis = [h for h in hallados if TENIS.search(h[2])]
    for ruta, (k, v), texto, claves in (tenis or hallados)[:maximo]:
        print(f"   · {texto}   [{k}={v}]")
    if hallados:
        print(f"   campos del objeto: {', '.join(hallados[0][3])}")
    return hallados


# ── Kalshi (API oficial) ─────────────────────────────────────────────────
KALSHI_BASES = ["https://api.elections.kalshi.com/trade-api/v2",
                "https://external-api.kalshi.com/trade-api/v2"]
KALSHI_SERIES_CONOCIDAS = ["KXATPMATCH", "KXWTAMATCH", "KXATPCHALLENGERMATCH",
                           "KXWTACHALLENGERMATCH", "KXITFMATCH", "KXITFWMATCH"]


def kalshi():
    base, series_dat, nota = None, None, ""
    for b in KALSHI_BASES:
        print(f"Probando {b}/series?category=Sports ...")
        series_dat, estado = pedir(f"{b}/series?category=Sports")
        print(f"   {estado}")
        if series_dat is not None:
            base = b
            break
    if not base:
        sys.exit("Kalshi no respondió.")
    series = [s for s in (series_dat or {}).get("series") or []
              if TENIS.search(f"{s.get('ticker', '')} {s.get('title', '')}")
              or "MATCH" in str(s.get("ticker", "")) and re.search(r"ATP|WTA|ITF", str(s.get("ticker", "")))]
    tickers = sorted({s.get("ticker") for s in series if s.get("ticker")} | set(KALSHI_SERIES_CONOCIDAS))
    print(f"   series de tenis: {', '.join(tickers)}")
    guardar("kalshi_series", series, f"base={base}")
    total = 0
    for t in tickers:
        time.sleep(0.4)
        ev, estado = pedir(f"{base}/events?series_ticker={t}&status=open&limit=200")
        eventos = (ev or {}).get("events") or []
        total += len(eventos)
        print(f"\n{t}: {estado} · {len(eventos)} eventos abiertos")
        for e in eventos[:3]:
            et = e.get("event_ticker", "")
            print(f"   · {e.get('title')} | {e.get('sub_title', '')}")
            print(f"     https://kalshi.com/markets/{t}/x/{et}")
        if eventos:
            guardar(f"kalshi_{t}", ev, f"base={base}")
    print(f"\nTotal eventos de tenis abiertos en Kalshi: {total}")


# ── Polymarket (API Gamma oficial) ────────────────────────────────────────
def polymarket():
    url = "https://gamma-api.polymarket.com/events?tag_slug=tennis&closed=false&limit=500"
    print(f"Probando {url} ...")
    datos, estado = pedir(url)
    print(f"   {estado}")
    if datos is None or not datos:
        url = "https://gamma-api.polymarket.com/events?closed=false&limit=500&order=startDate"
        print(f"Sin resultados con la etiqueta; probando {url} ...")
        datos, estado = pedir(url)
        print(f"   {estado}")
    eventos = [e for e in (datos or []) if isinstance(e, dict)
               and TENIS.search(f"{e.get('title', '')} {e.get('slug', '')}")]
    print(f"   eventos de tenis: {len(eventos)}")
    for e in eventos[:6]:
        print(f"   · {e.get('title')}  →  https://polymarket.com/event/{e.get('slug')}")
    guardar("polymarket", eventos or datos, url)


# ── Kambi (BetPlay, Rushbet) ────────────────────────────────────────────
def kambi(operador, host, lang, market):
    q = urllib.parse.urlencode({"lang": lang, "market": market, "useCombined": "true"})
    for h in ([host] if host else ["eu-offering-api.kambicdn.com", "eu1.offering-api.kambicdn.com"]):
        url = f"https://{h}/offering/v2018/{operador}/listView/tennis/all/all/all/in-play.json?{q}"
        print(f"Probando {url.split('?')[0]} ...")
        datos, estado = pedir(url)
        print(f"   {estado}")
        if datos is not None:
            guardar(f"kambi_{operador}", datos, url)
            analizar(datos)
            return
        time.sleep(1)
    print("No respondió: revisa el código de operador, o pásame host, lang y market del navegador.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fuente", choices=["kalshi", "polymarket", "kambi", "url"])
    ap.add_argument("valor", nargs="?", help="código de operador (kambi) o URL (url)")
    ap.add_argument("--nombre", default="casa", help="nombre de la casa (modo url)")
    ap.add_argument("--host")
    ap.add_argument("--lang", default="es_CO")
    ap.add_argument("--market", default="CO")
    A = ap.parse_args()
    if A.fuente == "kalshi":
        kalshi()
    elif A.fuente == "polymarket":
        polymarket()
    elif A.fuente == "kambi":
        if not A.valor:
            sys.exit("Falta el código de operador.")
        kambi(A.valor, A.host, A.lang, A.market)
    else:
        if not A.valor or not A.valor.startswith("http"):
            sys.exit('Falta la URL:  python scripts/capturar_fuente.py url "https://..." --nombre casa')
        print(f"Probando {A.valor[:120]} ...")
        datos, estado = pedir(A.valor)
        print(f"   {estado}")
        if datos is None:
            sys.exit("   Desde un programa NO responde: la casa bloquea el acceso automático "
                     "(o la URL lleva un código temporal). Guárdala igualmente y pásamela.")
        guardar(A.nombre, datos, A.valor)
        analizar(datos)
    print(f"\nGuardado en {DEST}. Cuando termines, comprime la carpeta 'capturas' y súbela.")


if __name__ == "__main__":
    main()
