#!/usr/bin/env python3
"""
scripts/probar_betano.py — ¿Qué web de Betano responde desde aquí?

Betano usa el MISMO número de partido en todos sus países (comprobado: el
número de ro.betano.com abrió el partido en betano.co). Así que el BOT puede
leer CUALQUIER Betano que responda desde su servidor (EE. UU.) y enlazar a
betano.co con ese número.

Uso (con la VPN de EE. UU. activa, que es donde estará el servidor):
    python scripts/probar_betano.py
Para cada web: si responde, cuántos partidos de tenis EN VIVO tiene y el
enlace de betano.co que saldría del primero.
"""
from __future__ import annotations

import argparse
import json
import re
import time

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--proxy", default="", help="http://usuario:clave@host:puerto (proxy residencial en Colombia)")
ap.add_argument("--solo-co", action="store_true", help="probar solo betano.co y betano.com")
A = ap.parse_args()


def _normalizar(t):
    """host:puerto:usuario:clave → http://usuario:clave@host:puerto (como el BOT)."""
    from urllib.parse import quote
    t = (t or "").strip()
    if not t or "://" in t:
        return t
    p = t.split(":")
    if len(p) >= 4:
        return f"http://{quote(p[2], safe='')}:{quote(':'.join(p[3:]), safe='')}@{p[0]}:{p[1]}"
    return f"http://{t}"


A.proxy = _normalizar(A.proxy)

HOSTS = ["www.betano.co", "www.betano.com", "www.betano.com.br", "www.betano.pe",
         "www.betano.mx", "www.betano.ca", "www.betano.bet.ar", "www.betano.cl",
         "ro.betano.com", "www.betano.pt", "www.betano.de", "www.betano.cz", "www.betano.gr"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def slug(t):
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def cab(host, con_x):
    h = {"User-Agent": UA, "Accept": "application/json, text/plain, */*",
         "Origin": f"https://{host}", "Referer": f"https://{host}/",
         "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-origin"}
    if con_x:
        h.update({"x-language": "8", "x-operator": "17"})
    return h


def pedir(host, ruta, con_x, chrome):
    url = f"https://{host}/danae-webapi/api/live/{ruta}"
    if chrome:
        from curl_cffi import requests as cr
        extra = {"proxies": {"http": A.proxy, "https": A.proxy}} if A.proxy else {}
        r = cr.get(url, headers=cab(host, con_x), impersonate="chrome", timeout=15, **extra)
        return r.status_code, r.content
    r = httpx.get(url, headers=cab(host, con_x), timeout=httpx.Timeout(15, connect=8),
                  follow_redirects=False, **({"proxy": A.proxy} if A.proxy else {}))
    return r.status_code, r.content


def main():
    try:
        p = httpx.get("https://ipinfo.io/json", timeout=15,
                      **({"proxy": A.proxy} if A.proxy else {})).json()
        via = " (a través del proxy)" if A.proxy else ""
        print(f"Conexión desde: {p.get('country')} · {p.get('region')}{via}\n")
    except Exception:
        print("No se pudo comprobar el país de salida" + (" del proxy" if A.proxy else "") + "\n")
    try:
        import curl_cffi  # noqa: F401
        formas = [("normal", False), ("huella Chrome", True)]
    except ImportError:
        formas = [("normal", False)]
    buenas = []
    for host in (HOSTS[:2] if A.solo_co else HOSTS):
        res = "✗"
        for nombre, chrome in formas:
            for con_x in (False, True):
                try:
                    st, cuerpo = pedir(host, "availabilities/latest", con_x, chrome)
                except Exception as e:
                    res = f"✗ no responde ({type(e).__name__})"
                    break                     # sin conexión: no insistir con esta web
                if st != 200:
                    res = f"✗ HTTP {st}"
                    continue
                try:
                    d = json.loads(cuerpo)
                except ValueError:
                    res = "✗ no es JSON"
                    continue
                ten = [str(v.get("eventId")) for v in (d.get("liveEvents") or {}).values()
                       if v.get("sportId") == "TENN"]
                res = f"✅ {len(ten)} partidos de tenis en vivo ({nombre}{', con x-operator' if con_x else ''})"
                if ten:
                    try:
                        st2, c2 = pedir(host, f"events/{ten[0]}/latest", con_x, chrome)
                        ev = json.loads(c2).get("event", {}) if st2 == 200 else {}
                        ps = [x.get("name", "") for x in ev.get("participants") or []]
                        if len(ps) == 2:
                            res += (f"\n        ej. {ps[0]} vs {ps[1]} → número {ten[0]}"
                                    f"\n        https://www.betano.co/live/{slug(ps[0] + ' ' + ps[1])}/{ten[0]}/")
                    except Exception:
                        pass
                buenas.append(host)
                break
            if res.startswith("✅") or res.startswith("✗ no responde"):
                break
        print(f"  {host:<22} {res}")
        time.sleep(0.5)
    print("\nWebs que responden:", ", ".join(buenas) or "ninguna")
    print("Abre (sin VPN, desde Colombia) el enlace de betano.co de ejemplo y dime si abre ese partido.")


if __name__ == "__main__":
    main()
