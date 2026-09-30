#!/usr/bin/env python3
"""
scripts/verificar_todo.py — Verificación completa ANTES de subir.

    python scripts/verificar_todo.py
    python scripts/verificar_todo.py --rankingftr C:\\ruta\\a\\RankingFTR

Requisitos (una vez):
    pip install playwright
    python -m playwright install chromium

Tres partes:
  1. Pruebas del buscador (tests/test_buscador.py).
  2. Escenarios en un NAVEGADOR REAL (Chromium, sin ventana) con la pestaña
     REAL de RankingFTR y el servicio real. Las fuentes de las casas (Kambi,
     FanDuel, DraftKings, Caesars) van SIMULADAS con la estructura de las
     capturas reales: permite provocar fallos (lenta, caída, recién empezado).
     Cubre los 8 escenarios de STAGING.md y los casos nuevos.
  3. Con --rankingftr: la pestaña probada es IDÉNTICA a la de tu RankingFTR
     (buscador.js y buscador.html), y research.html pide la versión nueva.

Nada toca Railway, FullTenis ni tu base: todo en una carpeta temporal.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
DIR_SIM = Path(__file__).resolve().parent / "simulador"

ap = argparse.ArgumentParser()
ap.add_argument("--rankingftr", help="raíz de tu RankingFTR con los cambios aplicados")
A = ap.parse_args()

P_FT, P_BOT, P_OTRO, P_APAGADO, P_SINCONF = 8100, 8101, 8102, 8103, 8104
CLAVE_FALSA = "AK-FANDUEL-QUE-NUNCA-DEBE-SALIR-EN-LOGS"
SECRETO = "secreto-de-verificacion-local"
TMP = Path(tempfile.mkdtemp())
os.environ.update({
    "FANDUEL_AK": CLAVE_FALSA, "ODDSPAPI_API_KEY": "", "BUSCADOR_DB_PATH": str(TMP / "v.db"),
    "BUSCADOR_TOKEN_SECRET": SECRETO, "ALLOWED_ORIGINS": f"http://127.0.0.1:{P_FT}",
    "SYNC_ACTIVO": "0", "FTR_SERVICE_URL": "http://127.0.0.1:1",
    "FTR_LECTURA_SECRET": "no-se-usa", "TIMEOUT_PROVIDER_S": "2", "MODO_PRUEBA": "",
})

RESULTADOS: list[tuple[str, bool, str]] = []


def check(parte: str, nombre: str, cond: bool, detalle: str = ""):
    RESULTADOS.append((parte, bool(cond), nombre + (f"  [{detalle}]" if detalle and not cond else "")))
    print(("  OK    " if cond else "  FALLA ") + nombre + (f"  [{detalle}]" if detalle and not cond else ""))


# ── 1. Pruebas del buscador ─────────────────────────────────────────────
print("\n1. Pruebas del buscador")
r = subprocess.run([sys.executable, str(RAIZ / "tests" / "test_buscador.py")],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
ult = [x for x in r.stdout.strip().splitlines() if x.strip()][-1:] or ["(sin salida)"]
check("1", f"tests/test_buscador.py -> {ult[0]}", r.returncode == 0 and "TODO BIEN" in r.stdout,
      "ejecútalo aparte para ver el detalle")

# ── 2. Navegador real ───────────────────────────────────────────────────
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sys.exit("\nFalta Playwright:  pip install playwright  y  python -m playwright install chromium")

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse, Response  # noqa: E402

LOGS = io.StringIO()
_h = logging.StreamHandler(LOGS)
_h.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_h)
logging.getLogger().setLevel(logging.INFO)

from buscador import app as bot, catalogo, config, db, sync  # noqa: E402
import time as _time  # noqa: E402

from buscador.providers.fuentes import FUENTES  # noqa: E402

ahora = datetime.now(timezone.utc)
HOY = (ahora - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _kambi(i, a, b):
    return {"event": {"id": i, "homeName": a, "awayName": b, "sport": "TENNIS", "group": "X",
                      "state": "STARTED", "start": HOY}}


KAMBI_EV = [_kambi(1029306638, "Eduardo Ribeiro", "Pedro Sakamoto"),
            _kambi(1029400001, "Luis Lento", "Tomas Tardio"),
            _kambi(1029400002, "Doble A/Doble B", "Doble C/Doble D")]
FD_R = {"attachments": {"events": {"36130487": {
    "eventId": 36130487, "name": "Eduardo Ribeiro v Pedro Sakamoto", "competitionId": 7,
    "openDate": HOY, "inPlay": True}}, "competitions": {"7": {"name": "Challenger Curitiba 2026"}}}}
DK_R = {"events": [{"id": "34746083", "seoIdentifier": "eduardo-ribeiro-vs-pedro-sakamoto", "sportId": "6",
                    "startEventDate": HOY, "status": "STARTED",
                    "participants": [{"name": "Eduardo Ribeiro", "sortOrder": 1},
                                     {"name": "Pedro Sakamoto", "sortOrder": 2}]}]}
CZ_R = [{"eventId": "ca32cb2b-0584-475f-b5fa-eaf91d79a37e", "startTime": HOY, "started": True,
         "eventDisplay": {"teams": ["Alejandro Tabilo", "Tommy Paul"]}}]
URL_BETPLAY = "https://tienda.betplay.com.co/apuestas#event/1029306638"
URL_FANDUEL = "https://sportsbook.fanduel.com/tennis/challenger-curitiba-2026/eduardo-ribeiro-v-pedro-sakamoto-36130487"
URL_DK = "https://sportsbook.draftkings.com/event/eduardo-ribeiro-vs-pedro-sakamoto/34746083"
PETICIONES: list[str] = []
LENTO = {"kambi": False}


async def fuentes_falsas(req: httpx.Request):
    h = req.url.host
    PETICIONES.append(h)
    if "kambicdn" in h:
        if LENTO["kambi"]:
            await asyncio.sleep(5)
        return httpx.Response(200, json={"liveEvents": KAMBI_EV})
    if "fanduel" in h:
        if req.url.params.get("_ak") != CLAVE_FALSA:
            return httpx.Response(403)
        return httpx.Response(200, json=FD_R)
    if "draftkings" in h:
        return httpx.Response(200, json=DK_R)
    if "americanwagering" in h:
        return httpx.Response(200, json=CZ_R)
    return httpx.Response(404)


for _f in FUENTES.values():
    _f._transporte = httpx.MockTransport(fuentes_falsas)
conn = db.conectar()
db.inicializar(conn)
catalogo.sembrar(conn)
for fid, a, b in (("r", "Eduardo Ribeiro", "Pedro Sakamoto"), ("l", "Luis Lento", "Tomas Tardio"),
                  ("d", "Doble A/Doble B", "Doble C/Doble D"), ("n", "Nuevo Jugador", "Recien Empezado")):
    sync.guardar_fixture(conn, {"fixture_id": "ft-" + fid, "fecha": HOY, "jugador1": a, "jugador2": b,
                                "torneo": "Challenger Curitiba", "genero": "M"}, "fixtures")
conn.commit()


def app_ft(url_bot: str | None) -> FastAPI:
    ft = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    panel = (DIR_SIM / "buscador.html").read_text(encoding="utf-8")
    js = (DIR_SIM / "buscador.js").read_text(encoding="utf-8")
    pagina = ("<!doctype html><meta charset=utf-8><body>"
              "<button class='tab-btn' data-tab='buscador' onclick='selTab(this)'>BUSCADOR</button>"
              + panel + "<script>function selTab(b){}</script>"
              "<script src='/research/static/js/tabs/buscador_ventanas.js' defer></script>"
              "<script src='/research/static/js/tabs/buscador.js' defer></script></body>")
    ventanas_js = (DIR_SIM / "ventanas.js").read_text(encoding="utf-8")

    @ft.get("/", response_class=HTMLResponse)
    def inicio():
        return pagina

    @ft.get("/research/static/js/tabs/buscador.js")
    def script():
        return Response(js, media_type="application/javascript")

    @ft.get("/research/static/js/tabs/buscador_ventanas.js")
    def script_ventanas():
        return Response(ventanas_js, media_type="application/javascript")

    @ft.get("/api/buscador/token")
    def token():
        if url_bot is None:
            return JSONResponse(status_code=503, content={"detail": "no configurado"})
        from buscador.token import emitir
        return {"token": emitir(SECRETO, "v", "verificador", "admin"), "url": url_bot, "expira_en": 600}
    return ft


def arrancar():
    async def todo():
        cfg = lambda app, p: uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=p,  # noqa: E731
                                                           log_level="warning"))
        await asyncio.gather(
            cfg(bot.app, P_BOT).serve(),
            cfg(app_ft(f"http://127.0.0.1:{P_BOT}"), P_FT).serve(),
            cfg(app_ft(f"http://127.0.0.1:{P_BOT}"), P_OTRO).serve(),      # origen no permitido
            cfg(app_ft("http://127.0.0.1:8199"), P_APAGADO).serve(),       # buscador apagado
            cfg(app_ft(None), P_SINCONF).serve())                          # sin configurar
    threading.Thread(target=lambda: asyncio.run(todo()), daemon=True).start()
    for _ in range(50):
        try:
            if httpx.get(f"http://127.0.0.1:{P_BOT}/salud", timeout=0.5).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    sys.exit("No arrancaron los servidores locales (¿puertos 8100-8104 ocupados?).")


arrancar()
print("\n2. Escenarios en navegador real (pestaña real + servicio real, fuentes simuladas)")


def limpiar_mapa():
    c = db.conectar()
    c.execute("DELETE FROM provider_event_map")
    c.commit()
    c.close()


with sync_playwright() as pw:
    nav = pw.chromium.launch()

    def pagina(puerto: int, espera: int = 1500):
        ctx = nav.new_context()
        ventanas = []
        ctx.on("page", lambda p: ventanas.append(p))
        ctx.route("https://**/*", lambda r: r.fulfill(status=200, body="<h1>casa</h1>"))
        pg = ctx.new_page()
        pg.goto(f"http://127.0.0.1:{puerto}/#buscador")
        pg.wait_for_timeout(espera)
        return pg, ventanas

    def buscar_elegir(pg, q):
        pg.fill("#bb-q", q)
        pg.wait_for_timeout(900)
        pg.check("#bb-resultados input[name=bb-p]")
        pg.wait_for_timeout(200)

    def abrir(pg, ventanas, espera=3000):
        antes = len(ventanas)
        pg.click("#bb-abrir")
        pg.wait_for_timeout(espera)
        return pg.inner_text("#bb-estado"), [v for v in ventanas[antes:]]

    def aviso(pg):
        return pg.is_visible("#bb-aviso"), pg.inner_text("#bb-aviso") if pg.is_visible("#bb-aviso") else ""

    # Escenario 1: funcionando
    pg, ven = pagina(P_FT)
    check("2", "E1 la pestaña carga sin aviso de 'no disponible'", not aviso(pg)[0])
    check("2", "solo aparecen las casas disponibles (ninguna pendiente)",
          pg.locator("#bb-casas input[value='luckia_co']").count() == 0
          and pg.locator("#bb-casas input[value='betplay_co']").count() == 1
          and pg.locator("#bb-casas input[disabled]").count() == 0)
    buscar_elegir(pg, "ribeiro")
    check("2", "ABRIR desactivado si aún no hay casas guardadas", pg.is_disabled("#bb-abrir"))
    check("2", "aviso para guardar casas", "Guardar mis casas" in pg.inner_text("#bb-estado"))
    for pid in ("betplay_co", "rushbet_co", "fanduel_nc", "draftkings_nc", "caesars_nc"):
        pg.check(f"#bb-casas input[value='{pid}']")
    pg.click("#bb-guardar")
    pg.wait_for_timeout(900)
    check("2", "ABRIR se activa al guardar casas después de elegir partido",
          not pg.is_disabled("#bb-abrir"))
    check("2", "la búsqueda no muestra dobles",
          "Doble" not in (pg.fill("#bb-q", "doble") or pg.wait_for_timeout(900) or
                          pg.inner_text("#bb-resultados")))
    PETICIONES.clear()
    buscar_elegir(pg, "ribeiro")
    est, nuevas = abrir(pg, ven)
    urls = sorted(v.url for v in nuevas if not v.is_closed())
    check("2", "E1 BetPlay, Rushbet, FanDuel y DraftKings ✅; Caesars ❌ (no tiene el partido)",
          est.count("✅") == 4 and "Caesars Sportsbook → ❌" in est, est.replace("\n", " | "))
    check("2", "E1 4 ventanas en el partido y la de Caesars en su sección de tenis (respaldo)",
          len(urls) == 5 and URL_BETPLAY in urls and "https://sportsbook.caesars.com/tennis" in urls, str(urls))
    check("2", "E1 respaldo: la fila de Caesars dice que busque el apellido",
          "Caesars Sportsbook → ❌" in est and "busca «Ribeiro»" in est, est.replace("\n", " | "))
    pg.context.grant_permissions(["clipboard-read", "clipboard-write"])
    pg.click("#bb-copiar")
    pg.wait_for_timeout(400)
    copiado = pg.evaluate("navigator.clipboard.readText()")
    check("2", "📋 Copiar enlaces: el partido y los 4 enlaces directos (sin respaldos)",
          copiado.startswith("🎾 Eduardo Ribeiro vs Pedro Sakamoto") and copiado.count("https://") == 4
          and "caesars" not in copiado, copiado.replace("\n", " | "))
    check("2", "casas agrupadas por región", pg.locator("#bb-casas .bb-region").count() == 3)
    check("2", "hay 3 modos y el de por defecto es 📑 todas a la vez",
          pg.locator("#bb-dist input[name=bb-modo]").count() == 3 and pg.is_checked("#bb-dist input[value=todas]"))

    # Modo CUADRÍCULA: mismas casas y destinos, en ventanas colocadas
    pg.check("#bb-dist input[value=cuadricula]")
    pg.wait_for_timeout(300)
    limpiar_mapa()
    est_c, nuevas_c = abrir(pg, ven, espera=4000)
    urls_c = sorted(v.url for v in nuevas_c if not v.is_closed())
    check("2", "CUADRÍCULA: 4 ventanas con el partido + Caesars en su sección de tenis",
          len(urls_c) == 5 and URL_BETPLAY in urls_c and "https://sportsbook.caesars.com/tennis" in urls_c, str(urls_c))

    # Modo UNA A UNA: no abre ventanas; un botón «Abrir» por casa
    pg.check("#bb-dist input[value=una]")
    pg.wait_for_timeout(300)
    antes = len([v for v in ven if not v.is_closed()])
    limpiar_mapa()
    est_u, nuevas_u = abrir(pg, ven)
    enlaces_u = pg.eval_on_selector_all("#bb-estado a.bb-uno", "as => as.map(a => [a.textContent, a.href])")
    check("2", "UNA A UNA: no abre ninguna ventana sola", not [v for v in nuevas_u if not v.is_closed()], str(len(nuevas_u)))
    check("2", "UNA A UNA: botón «Abrir» con el enlace de cada casa y «sección de tenis» en Caesars",
          ["Abrir", URL_BETPLAY] in enlaces_u and ["Abrir", URL_DK] in enlaces_u
          and ["Abrir sección de tenis", "https://sportsbook.caesars.com/tennis"] in enlaces_u, str(enlaces_u))
    with pg.context.expect_page() as nueva:
        pg.click("#bb-estado a.bb-uno[href='" + URL_BETPLAY + "']")
    check("2", "UNA A UNA: al pulsar «Abrir» se abre esa casa", nueva.value.url == URL_BETPLAY, nueva.value.url)
    pg.reload(); pg.wait_for_timeout(1500)
    check("2", "la preferencia se recuerda en este ordenador (tras recargar sigue «una a una»)",
          pg.is_checked("#bb-dist input[value=una]"))
    pg.check("#bb-dist input[value=todas]")
    pg.wait_for_timeout(300)
    buscar_elegir(pg, "ribeiro")                  # la recarga borra el partido elegido
    check("2", "FanDuel y DraftKings abren con su formato de enlace",
          URL_FANDUEL in urls and URL_DK in urls, str(urls))
    check("2", "ninguna ventana va al boleto (betslip)", not any("coupon" in u for u in urls))
    check("2", "BetPlay y Rushbet: 1 sola lectura de Kambi para las dos",
          sum("kambicdn" in h for h in PETICIONES) == 1, str(PETICIONES))
    PETICIONES.clear()
    limpiar_mapa()
    abrir(pg, ven)
    check("2", "segunda vez: 0 lecturas de las fuentes (caché)", not PETICIONES, str(PETICIONES))

    # Flujo MTO: partido que empezó después de la última lectura
    KAMBI_EV.append(_kambi(1029400003, "Nuevo Jugador", "Recien Empezado"))
    FUENTES["kambi"]._cuando = _time.monotonic() - 20
    buscar_elegir(pg, "recien")
    est, _ = abrir(pg, ven)
    check("2", "partido recién empezado: relee la fuente y BetPlay lo abre",
          "BetPlay → ✅" in est, est.replace("\n", " | "))

    # Escenario 4: fuente lenta
    LENTO["kambi"] = True
    FUENTES["kambi"]._eventos, FUENTES["kambi"]._cuando = [], 0.0
    limpiar_mapa()
    t0 = time.time()
    buscar_elegir(pg, "ribeiro")
    est, _ = abrir(pg, ven, espera=5500)
    check("2", "E4 fuente lenta: ⛔ tiempo agotado en BetPlay, DraftKings sigue ✅",
          "tiempo agotado" in est and "DraftKings → ✅" in est and time.time() - t0 < 10,
          est.replace("\n", " | "))
    LENTO["kambi"] = False

    # Escenario 7: una fuente caída
    config.MODO_PRUEBA.add("fuente_caida:kambi")
    limpiar_mapa()
    est, nuevas = abrir(pg, ven)
    check("2", "E7 fuente Kambi caída: BetPlay y Rushbet ⛔, FanDuel y DraftKings ✅",
          "BetPlay → ⛔" in est and "Rushbet → ⛔" in est and est.count("✅") == 2,
          est.replace("\n", " | "))
    config.MODO_PRUEBA.clear()

    # Escenario 8: una casa fallando
    config.MODO_PRUEBA.add("casa_falla:betplay_co")
    limpiar_mapa()
    est, _ = abrir(pg, ven)
    check("2", "E8 BetPlay falla: BetPlay ⛔ y Rushbet ✅",
          "BetPlay → ⛔" in est and "Rushbet → ✅" in est, est.replace("\n", " | "))
    config.MODO_PRUEBA.clear()
    pg.context.close()

    # Escenario 3: lento (toda la API)
    config.MODO_PRUEBA.add("lento")
    pg, _ = pagina(P_FT, espera=6000)
    check("2", "E3 servicio lento: aviso 'temporalmente no disponible' en ~4 s", aviso(pg)[0])
    config.MODO_PRUEBA.clear()
    pg.context.close()

    # Escenario 5: error 500
    config.MODO_PRUEBA.add("error500")
    pg, _ = pagina(P_FT)
    check("2", "E5 error 500: aviso 'temporalmente no disponible'", aviso(pg)[0])
    config.MODO_PRUEBA.clear()
    pg.context.close()

    # Escenario 6: CORS de otro origen
    pg, _ = pagina(P_OTRO)
    check("2", "E6 origen no permitido (CORS): aviso y ningún dato", aviso(pg)[0])
    pg.context.close()

    # Escenario 2: buscador apagado
    pg, _ = pagina(P_APAGADO, espera=5500)
    check("2", "E2 buscador apagado: aviso 'temporalmente no disponible'", aviso(pg)[0])
    pg.context.close()

    # Sin configurar (BUSCADOR_PUBLIC_URL vacía en RankingFTR -> token 503)
    pg, _ = pagina(P_SINCONF)
    v, texto = aviso(pg)
    check("2", "sin configurar: 'no está disponible todavía'", v and "todavía" in texto, texto)
    pg.context.close()
    nav.close()

salud = httpx.get(f"http://127.0.0.1:{P_BOT}/salud").text
check("2", "la clave _ak de FanDuel no aparece en los logs", CLAVE_FALSA not in LOGS.getvalue())
check("2", "la clave _ak de FanDuel no aparece en /salud", CLAVE_FALSA not in salud)

# ── 3. Archivos de RankingFTR ───────────────────────────────────────────
print("\n3. Pestaña probada = pestaña de tu RankingFTR")
if not A.rankingftr:
    print("  (omitido: pasa --rankingftr RUTA para comprobarlo)")
elif not Path(A.rankingftr).is_dir():
    check("3", f"la carpeta de RankingFTR existe: {A.rankingftr}", False,
          "no existe; pon la ruta real de tu proyecto RankingFTR")
elif not (Path(A.rankingftr) / "research").is_dir():
    check("3", f"{A.rankingftr} es la raíz de RankingFTR", False,
          "no tiene la carpeta 'research'; pon la carpeta que contiene production/ y research/")
else:
    rf = Path(A.rankingftr)

    def h(p):
        return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest() if p.exists() else None
    for rel, sim in (("research/web/static/js/tabs/buscador.js", "buscador.js"),
                     ("research/web/static/js/tabs/buscador_ventanas.js", "ventanas.js"),
                     ("research/web/templates/tabs/buscador.html", "buscador.html")):
        check("3", f"{rel} idéntico al probado", h(rf / rel) == h(DIR_SIM / sim) and h(rf / rel),
              "no existe: ¿aplicaste RankingFTR_bot_buscador.zip?" if not (rf / rel).exists()
              else "distinto: aplica la última versión de RankingFTR_bot_buscador.zip")
    res = rf / "research/web/templates/research.html"
    check("3", "research.html pide buscador.js y buscador_ventanas.js ?v=20260930c",
          res.exists() and "buscador.js?v=20260930c" in res.read_text(encoding="utf-8")
          and "buscador_ventanas.js?v=20260930c" in res.read_text(encoding="utf-8"))

# ── Resumen ─────────────────────────────────────────────────────────────
malos = [r for r in RESULTADOS if not r[1]]
print("\n" + "═" * 60)
print(f"  {len(RESULTADOS) - len(malos)}/{len(RESULTADOS)} comprobaciones correctas")
for p, _, n in malos:
    print(f"  FALLA ({p}) {n}")
print("  TODO CORRECTO: listo para staging" if not malos else "  NO SUBIR hasta corregir lo anterior")
print("═" * 60)
os._exit(1 if malos else 0)
