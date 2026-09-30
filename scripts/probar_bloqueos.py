#!/usr/bin/env python3
"""
scripts/probar_bloqueos.py — ¿Por qué rechazan DraftKings, Caesars (y FanDuel)
al programa, si al navegador le responden?

Prueba cada casa de tres formas y dice cuál acepta:
  A  como ahora (programa, encabezados mínimos)
  B  + los encabezados que envía un navegador de verdad (Origin, Referer, sec-fetch…)
  C  + conexión con la huella de Chrome (librería curl_cffi)
     → pip install curl_cffi   (si no está instalada, C se salta)

Uso, CON LA VPN DE EE. UU. ACTIVA (aplicación de todo el ordenador):
    python scripts/probar_bloqueos.py
    python scripts/probar_bloqueos.py --fanduel-ak VALOR_REAL
Sin cookies ni sesión en ninguna forma. Solo una petición por casa y forma.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import json
import time
import uuid

import httpx

def _clave_local(archivo: str) -> str:
    f = Path(__file__).resolve().parent.parent / archivo
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def _ak_local() -> str:
    return _clave_local("fanduel_ak.txt")


# Claves públicas guardadas por scripts/sacar_claves.py (si no vienen por variable)
if not os.getenv("BETMGM_ACCESSID") and _clave_local("betmgm_accessid.txt"):
    os.environ["BETMGM_ACCESSID"] = _clave_local("betmgm_accessid.txt")


ap = argparse.ArgumentParser()
ap.add_argument("--fanduel-ak", default=_ak_local())
ap.add_argument("--estado", default="nc")
A = ap.parse_args()

CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def navegador(origen: str) -> dict:
    return {"User-Agent": CHROME_UA, "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9", "Origin": origen, "Referer": origen + "/",
            "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site"}


CASAS = {
    "draftkings": {
        "url": "https://sportsbook-nash.draftkings.com/api/sportscontent/views/dkuswv/v1/live",
        "params": {"tabId": "6"}, "origen": "https://sportsbook.draftkings.com",
        "extra": {"x-client-name": "web", "x-client-page": "Live", "x-client-feature": "live-page",
                  "x-client-version": "2640.2.1.7"}},
    "caesars": {
        "url": f"https://api.americanwagering.com/regions/us/locations/{A.estado}/brands/czr/sb/v4/sports/tennis/schedule",
        "params": {}, "origen": "https://sportsbook.caesars.com",
        "extra": {"x-app-version": "7.56.2", "x-platform": "cordova-desktop",
                  "x-unique-device-id": str(uuid.uuid4())}},
}
if os.getenv("BETMGM_ACCESSID"):
    CASAS["betmgm (lista deducida)"] = {
        "url": "https://www.nc.betmgm.com/cds-api/bettingoffer/fixtures",
        "params": {"x-bwin-accessid": os.environ["BETMGM_ACCESSID"], "lang": "en-us", "country": "US",
                   "userCountry": "US", "subdivision": "US-NorthCarolina", "fixtureTypes": "Standard",
                   "state": "Live", "offerMapping": "Filtered", "sportIds": "5", "skip": "0",
                   "take": "200", "sortBy": "StartDate"},
        "origen": "https://www.nc.betmgm.com", "extra": {}}
if A.fanduel_ak:
    CASAS["fanduel"] = {
        "url": "https://api.sportsbook.fanduel.com/sbapi/content-managed-page",
        "params": {"page": "SPORT", "eventTypeId": "2", "_ak": A.fanduel_ak, "timezone": "America/New_York"},
        "origen": "https://sportsbook.fanduel.com", "extra": {"x-sportsbook-region": A.estado.upper()}}


def resumen(status, cuerpo: bytes) -> str:
    if status != 200:
        return f"✗ HTTP {status}"
    try:
        d = json.loads(cuerpo)
    except ValueError:
        return "✗ 200 pero no es JSON (página de verificación antibots)"
    n = len(d) if isinstance(d, list) else len(d.get("events") or d.get("fixtures")
                                               or (d.get("attachments") or {}).get("events") or [])
    return f"✅ HTTP 200 · {n} partidos/eventos"


def forma_a(c):
    r = httpx.get(c["url"], params=c["params"], headers={"User-Agent": CHROME_UA, **c["extra"]}, timeout=15)
    return resumen(r.status_code, r.content)


def forma_b(c):
    r = httpx.get(c["url"], params=c["params"], headers={**navegador(c["origen"]), **c["extra"]}, timeout=15)
    return resumen(r.status_code, r.content)


def forma_c(c):
    try:
        from curl_cffi import requests as cr
    except ImportError:
        return "— (instala curl_cffi para probarla: pip install curl_cffi)"
    r = cr.get(c["url"], params=c["params"], headers={**navegador(c["origen"]), **c["extra"]},
               impersonate="chrome", timeout=15)
    return resumen(r.status_code, r.content)


def main():
    try:
        pais = httpx.get("https://ipinfo.io/json", timeout=8).json()
        print(f"Conexión desde: {pais.get('country')} · {pais.get('region')}\n")
    except Exception:
        print("Conexión desde: desconocido\n")
    if not A.fanduel_ak or not os.getenv("BETMGM_ACCESSID"):
        print("(Falta alguna clave: ejecuta antes  python scripts/sacar_claves.py)\n")
    for nombre, c in CASAS.items():
        print(f"── {nombre.upper()}")
        for letra, f in (("A", forma_a), ("B", forma_b), ("C", forma_c)):
            try:
                print(f"   {letra}: {f(c)}")
            except Exception as e:
                print(f"   {letra}: ✗ {type(e).__name__}")
            time.sleep(1)
        print()
    print("Pégame este resultado: con él adapto el BOT a la forma que acepta cada casa.")


if __name__ == "__main__":
    main()
