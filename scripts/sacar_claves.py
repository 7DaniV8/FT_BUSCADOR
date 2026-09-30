#!/usr/bin/env python3
"""
scripts/sacar_claves.py — Saca de TUS archivos HAR las claves PÚBLICAS que usan
las webs de las casas y las guarda en la carpeta del BOT:

  fanduel_ak.txt          parámetro _ak de FanDuel
  betmgm_accessid.txt     parámetro x-bwin-accessid de BetMGM

    python scripts/sacar_claves.py            busca los HAR solo (carpeta del BOT, Descargas)
    python scripts/sacar_claves.py a.har b.har

Son claves de la web (iguales para cualquier visitante), no datos tuyos. Las
herramientas locales las leen de esos archivos; en Railway van en las
variables FANDUEL_AK y BETMGM_ACCESSID.
"""
import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

RAIZ = Path(__file__).resolve().parent.parent
CLAVES = {  # archivo destino: (dominio, parámetro)
    "fanduel_ak.txt": ("fanduel.com", "_ak"),
    "betmgm_accessid.txt": ("betmgm.com", "x-bwin-accessid"),
}


def hars():
    if len(sys.argv) > 1:
        return [Path(a) for a in sys.argv[1:]]
    salida, vistos = [], set()
    for d in (Path.cwd(), RAIZ, RAIZ.parent, Path.home() / "Downloads", Path.home() / "Descargas"):
        if d.is_dir():
            for f in sorted(d.glob("*.har"), key=lambda x: -x.stat().st_mtime):
                if f.resolve() not in vistos:
                    vistos.add(f.resolve())
                    salida.append(f)
    return salida


def buscar(har: Path, dominio: str, param: str):
    try:
        datos = json.load(open(har, encoding="utf-8", errors="replace"))
    except Exception:
        return None
    vals = Counter(v for e in datos.get("log", {}).get("entries", [])
                   if dominio in (urlsplit(e["request"]["url"]).hostname or "")
                   for k, v in parse_qsl(urlsplit(e["request"]["url"]).query) if k == param)
    return vals.most_common(1)[0][0] if vals else None


pendientes = dict(CLAVES)
for har in hars():
    for destino, (dominio, param) in list(pendientes.items()):
        if dominio.split(".")[0] not in har.name.lower() and len(sys.argv) == 1:
            continue
        valor = buscar(har, dominio, param)
        if valor:
            (RAIZ / destino).write_text(valor, encoding="utf-8")
            print(f"✓ {param} de {dominio} encontrado en {har.name} → {destino}")
            del pendientes[destino]
for destino, (dominio, param) in pendientes.items():
    print(f"✗ no encontré {param} ({dominio}): copia su HAR a la carpeta del BOT o a Descargas")
if len(pendientes) < len(CLAVES):
    print("\nYa puedes ejecutar sin escribir nada más:\n  python scripts/probar_bloqueos.py\n"
          "  python scripts/simular_fulltenis.py")
