#!/usr/bin/env python3
"""
scripts/diagnostico_ventanas.py — Página de diagnóstico de la distribución de
ventanas (Windows y Mac). Solo Python estándar; no necesita el resto del BOT.

    python scripts/diagnostico_ventanas.py        (en Mac: python3 ...)

Abre el navegador en http://127.0.0.1:8010/ventanas_diagnostico.html
Usa Chrome o Edge para probar varios monitores. Ctrl+C para parar.
"""
import functools
import http.server
import threading
import webbrowser
from pathlib import Path

CARPETA = Path(__file__).resolve().parent / "simulador"
PUERTO = 8010
manejador = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(CARPETA))
servidor = http.server.ThreadingHTTPServer(("127.0.0.1", PUERTO), manejador)
url = f"http://127.0.0.1:{PUERTO}/ventanas_diagnostico.html"
print(f"Diagnóstico de ventanas en {url}\n(Ctrl+C para parar)")
threading.Timer(1.0, lambda: webbrowser.open(url)).start()
try:
    servidor.serve_forever()
except KeyboardInterrupt:
    print("\nParado.")
