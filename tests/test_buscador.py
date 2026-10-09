#!/usr/bin/env python3
"""
tests/test_buscador.py — Pruebas de BOT_BUSCADOR. Sin red: FullTenis y
OddsPapi se simulan.

    python tests/test_buscador.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
_TMP = Path(tempfile.mkdtemp())
os.environ["BUSCADOR_DB_PATH"] = str(_TMP / "b.db")
os.environ["BUSCADOR_TOKEN_SECRET"] = "clave-de-prueba"
os.environ["ALLOWED_ORIGINS"] = "https://fulltenis.example"
os.environ["SYNC_ACTIVO"] = "0"
os.environ["CASAS_OCULTAS"] = ""      # las pruebas usan todas las casas; el ocultamiento se prueba aparte
os.environ["FTR_SERVICE_URL"] = "https://ftr.example"
os.environ["FTR_LECTURA_SECRET"] = "lectura-de-prueba"
os.environ["TIMEOUT_PROVIDER_S"] = "1"
os.environ["ODDSPAPI_API_KEY"] = "clave-oddspapi-prueba"
os.environ["FUENTES_IMITAR_CHROME"] = "betmgm"

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from buscador import app as app_mod  # noqa: E402
from buscador import categoria, claves, config, db, providers, sync, validacion  # noqa: E402
from buscador.providers.base import Provider  # noqa: E402
from buscador.resolver import (AMBIGUO, ENCONTRADO, NO_ENCONTRADO, Candidato,  # noqa: E402
                               Partido, confianza, elegir)
from buscador.token import TokenInvalido, emitir, verificar  # noqa: E402

fallos = 0


def ok(cond, texto):
    global fallos
    print(("  OK    " if cond else "  FALLO ") + texto)
    if not cond:
        fallos += 1


print("\n1. Token corto de FullTenis")
S = "clave-de-prueba"
t = emitir(S, "42", "ruben", "admin")
c = verificar(t, S, "bot_buscador")
ok(c["sub"] == "42" and c["aud"] == "bot_buscador" and c["exp"] - c["iat"] == 600,
   "token válido: sub, aud, iat, exp (10 min)")
for nombre, tok in [("firma", emitir("otra", "42", "r", "admin")),
                    ("audiencia", emitir(S, "42", "r", "admin", aud="otra")),
                    ("caducado", emitir(S, "42", "r", "admin", ahora=int(time.time()) - 3600)),
                    ("vida larga", emitir(S, "42", "r", "admin", vida_s=86400))]:
    try:
        verificar(tok, S, "bot_buscador")
        ok(False, f"rechaza token con {nombre}")
    except TokenInvalido:
        ok(True, f"rechaza token con {nombre}")
cab, carga, _ = t.split(".")
import base64  # noqa: E402
nada = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
try:
    verificar(f"{nada}.{carga}.", S, "bot_buscador")
    ok(False, "rechaza alg=none")
except TokenInvalido:
    ok(True, "rechaza alg=none")

print("\n2. Clave compuesta (fixture_id + fecha + jugadores)")
k1 = claves.clave_partido("92831", "2026-09-28T14:00:00Z", "Martin Damm", "Arthur Fils")
k2 = claves.clave_partido("92831", "2026-09-28", "Arthur Fils", "Martin Damm")
k3 = claves.clave_partido("92831", "2026-09-28", "Otro Jugador", "Arthur Fils")
ok(k1 == k2, "mismo partido con jugadores al revés y con/sin hora: misma clave")
ok(k1 != k3, "mismo fixture_id (choque CRC32) con otros jugadores: clave distinta")
ok(not claves.tiene_hora("2026-09-28") and claves.tiene_hora("2026-09-28T14:00:00Z"),
   "ITF sin hora se reconoce como 'hora desconocida'")

for crudo, esp in [("Martin Damm", {"damm"}), ("Damm M.", {"damm"}),
                   ("Fita Boluda A.", {"fita", "boluda"}), ("Damm, Martin", {"damm"})]:
    ok(claves.apellidos(crudo) == esp, f"apellido de '{crudo}' -> {sorted(esp)}")

print("\n3. Categoría deducida dentro del buscador")
for torneo, genero, esp in [("ATP Tokyo", "M", "ATP"), ("WTA Beijing", "F", "WTA"),
                            ("Challenger Jingshan", "M", "CHALLENGER"),
                            ("WTA 125 Montreux", "F", "WTA125"),
                            ("M25 Bogota", "M", "ITF_M"), ("W35 Kyoto", "F", "ITF_W")]:
    ok(categoria.deducir(torneo, genero) == esp, f"{torneo} -> {esp}")

print("\n4. Resolver")
p_hora = Partido("k", "Martin Damm", "Arthur Fils", "2026-09-28T14:00:00+00:00", True,
                 "ATP Tokyo", "ATP")
p_itf = Partido("k", "Martin Damm", "Arthur Fils", "2026-09-28", False, "ATP Tokyo", "ATP")
cand = Candidato("E1", "Damm vs Fils", "https://polymarket.com/event/x",
                 "2026-09-28T14:30:00+00:00", "ATP Tokyo tennis")
ok(confianza(p_hora, Candidato("E0", "Damm vs Sinner", "u", "2026-09-28T14:00:00+00:00")) == 0,
   "si falta un jugador, confianza 0")
ok(confianza(p_itf, cand) < confianza(p_hora, cand),
   "sin hora: menos confianza (no se inventa hora)")
ok(elegir(p_hora, [cand])[0] == ENCONTRADO, "partido completo: ENCONTRADO")
otro = Candidato("E2", "Damm vs Fils", "https://polymarket.com/event/y",
                 "2026-09-28T14:10:00+00:00", "ATP Tokyo tennis")
ok(elegir(p_hora, [cand, otro])[0] == AMBIGUO, "dos candidatos casi iguales: AMBIGUO")
ok(elegir(p_hora, [])[0] == NO_ENCONTRADO, "sin candidatos: NO_ENCONTRADO")

print("\n5. Matriz de validación")
ok(validacion.escala(0, 2)["estado"] == "SIN_DATOS", "0-2 pruebas: SIN DATOS")
ok(validacion.escala(5, 10)["estado"] == "EN_PRUEBA", "3-19 pruebas: EN PRUEBA")
ok(validacion.escala(19, 20)["estado"] == "VALIDADO", "20+ y 95%: VALIDADO")
ok(validacion.escala(17, 20)["estado"] == "NO_CONFIABLE", "20+ y 85%: NO CONFIABLE")
conn = db.conectar()
db.inicializar(conn)
from buscador import catalogo  # noqa: E402
catalogo.sembrar(conn)
for _ in range(4):
    validacion.registrar(conn, "kalshi", "abre_sin_login", "pidio_login")
validacion.registrar(conn, "kalshi", "abre_sin_login", "abrio", navegador_limpio=False)
m = validacion.matriz_provider(conn, "kalshi")
ok(m["abre_sin_login"]["total"] == 4 and m["abre_sin_login"]["descartadas_perfil_no_limpio"] == 1,
   "prueba con perfil NO limpio: guardada pero fuera del cálculo")
ok(validacion.aviso_apertura(m) == "LOGIN_REQUERIDO", "pide login en pruebas limpias: aviso")
ok(m["deep_link"]["estado"] == "SIN_DATOS", "columnas independientes (deep link sin datos)")
conn.execute("DELETE FROM validaciones")
conn.commit()
ok(len([p for p in catalogo.SEMILLA if p["region"] == "CO"]) == 15,
   "catálogo: 15 casas de Colombia en investigación")

print("\n6. API y aislamiento entre casas")


class Falso(Provider):
    def __init__(self, cands=None, lento=False, roto=False):
        self.cands, self.lento, self.roto = cands or [], lento, roto

    async def candidatos(self, partido):
        if self.lento:
            await asyncio.sleep(5)
        if self.roto:
            raise RuntimeError("se cayó")
        return self.cands


# Fecha de HOY: el BOT borra los partidos de más de 3 días (DIAS_RETENCION).
_DIA = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat()
_AYER = (__import__('datetime').date.fromisoformat(_DIA) - __import__('datetime').timedelta(days=1)).isoformat()
sync.guardar_fixture(conn, {"fixture_id": "92831", "fecha": _DIA + "T14:00:00+00:00",
                            "jugador1": "Martin Damm", "jugador2": "Arthur Fils",
                            "torneo": "ATP Tokyo", "genero": "M"}, "fixtures")
conn.commit()
clave = claves.clave_partido("92831", _DIA, "Martin Damm", "Arthur Fils")
cli = TestClient(app_mod.app)
H = {"Authorization": "Bearer " + emitir(S, "42", "ruben", "admin")}
# Para probar el aislamiento se usan dos casas cualquiera como TESTING.
conn.execute("UPDATE provider_catalog SET estado='TESTING' WHERE id IN ('kalshi','polymarket')")
conn.commit()
ok(cli.get("/api/partidos", params={"q": "Damm"}).status_code == 401, "sin token: 401")
r = cli.get("/api/partidos", params={"q": "Damm"}, headers=H).json()
ok(r["partidos"] and r["partidos"][0]["clave"] == clave, "buscar 'Damm' en la caché propia")
ok(cli.put("/api/mis-casas", json={"providers": ["luckia_co"]}, headers=H).status_code == 400,
   "Mis casas: no deja marcar una casa PROVIDER_PENDING")
ok(cli.put("/api/mis-casas", json={"providers": ["kalshi", "polymarket", "kalshi"]},
           headers=H).status_code == 200, "Mis casas: guarda casas en TESTING (sin repetidos)")
ok([p["id"] for p in cli.get("/api/mis-casas", headers=H).json()["providers"]]
   == ["kalshi", "polymarket"], "Mis casas: se leen del usuario del token")
ok(cli.get("/api/resolver", params={"clave": clave, "provider": "luckia_co"},
           headers=H).json()["estado"] == "PROVIDER_PENDING", "casa pendiente: su estado, sin consultar")
ok(cli.get("/api/resolver", params={"clave": clave, "provider": "thescore_nc"},
           headers=H).json()["estado"] == "PROVIDER_PENDING", "casa OpticOdds sin trial: pendiente")

# Aislamiento con dos fuentes de prueba (vía candidatos genérica).
conn.execute("UPDATE provider_catalog SET metodo='kalshi_api' WHERE id='kalshi'")
conn.execute("UPDATE provider_catalog SET metodo='polymarket_gamma' WHERE id='polymarket'")
conn.commit()
providers._REGISTRO["kalshi_api"] = Falso(lento=True)
cand = Candidato(cand.id_externo, cand.titulo, cand.url, _DIA + "T14:10:00+00:00", cand.texto_extra)  # fecha de hoy
providers._REGISTRO["polymarket_gamma"] = Falso([cand])
t0 = time.time()
rk = cli.get("/api/resolver", params={"clave": clave, "provider": "kalshi"}, headers=H).json()
ok(rk["estado"] == "ERROR" and time.time() - t0 < 3, "casa lenta: ERROR por tiempo, sin colgarse")
rp = cli.get("/api/resolver", params={"clave": clave, "provider": "polymarket"}, headers=H).json()
ok(rp["estado"] == "ENCONTRADO" and rp["url"] == cand.url, "otra casa sigue funcionando: ENCONTRADO")
providers._REGISTRO["kalshi_api"] = Falso(roto=True)
ok(cli.get("/api/resolver", params={"clave": clave, "provider": "kalshi"},
           headers=H).json()["estado"] == "ERROR", "casa que lanza excepción: ERROR aislado")
providers._REGISTRO["kalshi_api"] = Falso([Candidato("E9", "Damm vs Fils",
                                                      "https://malicioso.example/x",
                                                      _DIA + "T14:00:00+00:00", "ATP")])
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(cli.get("/api/resolver", params={"clave": clave, "provider": "kalshi"},
           headers=H).json()["estado"] == "ERROR", "URL fuera de los dominios de la casa: nunca se abre")
config.MODO_PRUEBA.add("casa_falla:polymarket")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(cli.get("/api/resolver", params={"clave": clave, "provider": "polymarket"},
           headers=H).json()["estado"] == "ERROR", "MODO_PRUEBA casa_falla: esa casa da ERROR")
config.MODO_PRUEBA.clear()
pre = cli.options("/api/partidos", headers={"Origin": "https://fulltenis.example",
                                            "Access-Control-Request-Method": "GET"})
mal = cli.options("/api/partidos", headers={"Origin": "https://otro.example",
                                            "Access-Control-Request-Method": "GET"})
ok(pre.headers.get("access-control-allow-origin") == "https://fulltenis.example"
   and "access-control-allow-origin" not in mal.headers, "CORS: solo el origen de FullTenis")
ok(cli.post("/api/validaciones", json={"provider_id": "kalshi", "columna": "deep_link",
                                       "resultado": "ok"},
            headers={"Authorization": "Bearer " + emitir(S, "7", "x", "lectura")}).status_code == 403,
   "solo admin registra pruebas de la matriz")

print("\n7. Sincronización con FullTenis (simulado)")
vistas = []


def fullteni(request: httpx.Request):
    vistas.append((request.method, request.url.path, request.headers.get("X-FTR-Lectura-Secret"),
                   request.headers.get("X-FTR-Internal-Secret")))
    if request.url.path == "/ft-intel/fixtures":
        return httpx.Response(200, json={"fixtures": [
            {"fixture_id": 555, "fecha": _AYER, "jugador1": "Ana Uno",
             "jugador2": "Bea Dos", "torneo": "W35 Kyoto", "genero": "F"}], "hay_mas": False})
    if request.url.path == "/ft-intel/en-vivo":
        return httpx.Response(200, json={"partidos": [
            {"fid": 9, "home": "Ana Uno", "away": "Bea Dos", "liga": "W35 Kyoto",
             "primera_vez_visto": _AYER + "T10:00:00Z"}]})
    return httpx.Response(404)


async def _sync():
    async with httpx.AsyncClient(transport=httpx.MockTransport(fullteni)) as c:
        return await sync.sincronizar_una_vez(conn, c)


res = asyncio.run(_sync())
ok(all(m == "GET" and s == "lectura-de-prueba" and i is None for m, s, i in [v[:1] + v[2:] for v in vistas]),
   "solo GET, con FTR_LECTURA_SECRET y nunca con el secreto interno")
ok({v[1] for v in vistas} == {"/ft-intel/fixtures", "/ft-intel/en-vivo"},
   "solo las dos rutas permitidas")
f = conn.execute("SELECT * FROM fixtures_cache WHERE jugador1='Ana Uno'").fetchall()
ok(len(f) == 1 and f[0]["hora_conocida"] == 0 and f[0]["categoria"] == "ITF_W",
   "ITF sin hora guardado sin inventar hora; categoría propia; en-vivo no lo duplica")


def caido(request):
    raise httpx.ConnectError("apagado")


async def _sync_caido():
    async with httpx.AsyncClient(transport=httpx.MockTransport(caido)) as c:
        await sync.sincronizar_una_vez(conn, c)
try:
    asyncio.run(_sync_caido())
    ok(False, "FullTenis caído: la sincronización falla limpiamente")
except httpx.ConnectError:
    ok(cli.get("/api/partidos", params={"q": "Damm"}, headers=H).json()["partidos"] != [],
       "FullTenis caído: el buscador sigue sirviendo su caché")

print("\n8. OddsPapi: solo el enlace de cada casa")
from buscador.providers import oddspapi as op  # noqa: E402

conn.execute("DELETE FROM provider_catalog")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
catalogo.sembrar(conn)
ok(catalogo.obtener(conn, "betplay_co")["metodo"] == "kambi"
   and catalogo.obtener(conn, "betplay_co")["estado"] == "TESTING",
   "BetPlay va por Kambi (fuente gratuita), no por OddsPapi")

# Migración: fila antigua sin tocar -> se actualiza; fila cambiada a mano -> se respeta.
conn.execute("UPDATE provider_catalog SET metodo='kalshi_api', estado='TESTING' WHERE id='kalshi'")
conn.execute("UPDATE provider_catalog SET metodo='ninguno', estado='DISABLED' WHERE id='rushbet_co'")
conn.commit()
catalogo.sembrar(conn)
ok(catalogo.obtener(conn, "kalshi")["metodo"] == "kalshi", "migración: Kalshi antiguo -> su API oficial")
ok(catalogo.obtener(conn, "rushbet_co")["estado"] == "DISABLED", "migración: cambio manual respetado")
# El código de OddsPapi se conserva (desactivado): se prueba forzando esas casas a él.
conn.execute("UPDATE provider_catalog SET metodo='oddspapi', estado='TESTING' WHERE id IN "
             "('betplay_co','rushbet_co','draftkings_nc','fanduel_nc','betmgm_nc','kalshi','polymarket')")
conn.commit()

LISTA = [
    {"fixtureId": "id1201406175125672", "participant1Name": "Ribeiro, Eduardo",
     "participant2Name": "Sakamoto, Pedro", "startTime": _DIA + "T13:00:00.000Z",
     "hasOdds": True, "categorySlug": "challenger", "tournamentName": "ATP Challenger Curitiba",
     "statusName": "Pre-Game"},
    {"fixtureId": "pn129000000000000001", "participant1Name": "Eduardo Ribeiro",
     "participant2Name": "Pedro Sakamoto", "startTime": _DIA + "T13:00:00.000Z",
     "hasOdds": True, "categorySlug": "challenger", "tournamentName": "Curitiba"},
    {"fixtureId": "id1", "participant1Name": "Ribeiro E / Sakamoto P",
     "participant2Name": "Otro A / Otro B", "startTime": _DIA + "T15:00:00.000Z",
     "hasOdds": True, "categorySlug": "challenger"},
    {"fixtureId": "id2", "participant1Name": "Ribeiro, Eduardo (Srl)",
     "participant2Name": "Sakamoto, Pedro (Srl)", "startTime": _DIA + "T16:00:00.000Z",
     "hasOdds": True, "categorySlug": "simulated-reality"},
    {"fixtureId": "id3", "participant1Name": "Ribeiro, Eduardo", "participant2Name": "Zeta, Zed",
     "startTime": _DIA + "T17:00:00.000Z", "hasOdds": True, "categorySlug": "challenger"},
]
ENLACES = {
    "betplay": "https://tienda.betplay.com.co/apuestas#event/1029306638",
    "rushbet.co": "https://www.rushbet.co/?page=sportsbook#event/1029306638",
    "draftkings": "https://sportsbook.draftkings.com/event/34746083",
    "betmgm": "https://sports.nj.betmgm.com/en-us/sports/events/19972363",
    "kalshi": "https://kalshi.com/markets/kxatpmatch/e#kxatpmatch-26sep30ribsak",
}
llamadas = []
modo = {"odds": "ok"}


def oddspapi_falso(request: httpx.Request):
    llamadas.append((request.url.path, dict(request.url.params)))
    if request.url.path.endswith("/fixtures"):
        return httpx.Response(200, json=LISTA)
    if request.url.path.endswith("/odds"):
        if modo["odds"] == "vivo":
            return httpx.Response(403, json={"error": {"code": "RESTRICTED_ACCESS",
                                                       "message": "live"}})
        casas = {k: {"fixturePath": v, "markets": {"121": {"outcomes": {}}}}
                 for k, v in ENLACES.items()}
        casas["betplay"]["markets"]["121"]["outcomes"] = {"121": {"players": {"0": {
            "betslip": "https://tienda.betplay.com.co/apuestas#event/1?coupon=x"}}}}
        casas["pinnacle"] = {"fixturePath": "https://www.pinnacle.com/en/e/e/e/1"}
        return httpx.Response(200, json={"fixtureId": request.url.params["fixtureId"],
                                         "bookmakerOdds": casas})
    return httpx.Response(404)


providers.ODDSPAPI._transporte = httpx.MockTransport(oddspapi_falso)
n = asyncio.run(providers.ODDSPAPI.sincronizar_fixtures(conn))
ok(n == 3, "lista de OddsPapi: fuera dobles y simulados (SRL)")

sync.guardar_fixture(conn, {"fixture_id": "777", "fecha": _DIA,
                            "jugador1": "Eduardo Ribeiro", "jugador2": "Pedro Sakamoto",
                            "torneo": "Challenger Curitiba", "genero": "M"}, "fixtures")
conn.commit()
clave_op = claves.clave_partido("777", _DIA, "Eduardo Ribeiro", "Pedro Sakamoto")
est, ids, conf = op.emparejar(conn, Partido(clave_op, "Eduardo Ribeiro", "Pedro Sakamoto",
                                            _DIA, False))
ok(est == ENCONTRADO and ids[0] == "id1201406175125672",
   "empareja por los dos jugadores, cada uno en su lado; prefiere el id con más casas")
est2, _, _ = op.emparejar(conn, Partido("x", "Eduardo Ribeiro", "Otro Jugador", _DIA, False))
ok(est2 == NO_ENCONTRADO, "con un solo jugador no empareja")

llamadas.clear()
cli2 = TestClient(app_mod.app)


def resolver(pid):
    return cli2.get("/api/resolver", params={"clave": clave_op, "provider": pid}, headers=H).json()


rb = resolver("betplay_co")
ok(rb["estado"] == "ENCONTRADO" and rb["url"] == ENLACES["betplay"],
   "BetPlay: ENCONTRADO con el enlace del partido (fixturePath)")
ok("coupon" not in rb["url"], "nunca el enlace del boleto (betslip)")
ok(resolver("betmgm_nc")["url"] == "https://sports.nc.betmgm.com/en-us/sports/events/19972363",
   "BetMGM: el estado del dominio pasa a nc")
ok(resolver("rushbet_co")["estado"] == "ENCONTRADO" and resolver("kalshi")["url"]
   == "https://kalshi.com/markets/KXATPMATCH/x/KXATPMATCH-26SEP30RIBSAK",
   "Rushbet y Kalshi con el mismo partido (Kalshi en la página del partido)")
n_odds = len([c for c in llamadas if c[0].endswith("/odds")])
ok(n_odds == 1, f"una sola petición a OddsPapi para todas las casas del partido ({n_odds})")
q = [c[1] for c in llamadas if c[0].endswith("/odds")][0]
ok("pinnacle" not in q.get("bookmakers", "") and "betplay" in q.get("bookmakers", ""),
   "solo se piden las casas del catálogo")
ok(resolver("fanduel_nc")["estado"] == "NO_ENCONTRADO", "casa sin enlace en ese partido: NO_ENCONTRADO")
ok(conn.execute("SELECT COUNT(*) FROM oddspapi_enlaces WHERE bookmaker='pinnacle'").fetchone()[0] == 0,
   "casas fuera del catálogo no se guardan")


async def _paralelo():
    conn.execute("DELETE FROM oddspapi_enlaces")
    conn.execute("DELETE FROM oddspapi_consultas")
    conn.commit()
    llamadas.clear()
    p = Partido(clave_op, "Eduardo Ribeiro", "Pedro Sakamoto", _DIA, False)
    return await asyncio.gather(*[providers.ODDSPAPI.resolver_directo(db.conectar(), p, pid)
                                  for pid in ("betplay_co", "rushbet_co", "draftkings_nc",
                                              "betmgm_nc", "kalshi")])


res_par = asyncio.run(_paralelo())
ok(all(r[0] == ENCONTRADO for r in res_par)
   and len([c for c in llamadas if c[0].endswith("/odds")]) == 1,
   "cinco casas a la vez: una sola petición (candado por partido)")

ENLACES["betplay"] = "https://malicioso.example/x"
conn.execute("DELETE FROM oddspapi_enlaces")
conn.execute("DELETE FROM oddspapi_consultas")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(resolver("betplay_co")["estado"] == "ERROR", "enlace fuera del dominio de la casa: nunca se abre")
ENLACES["betplay"] = "https://tienda.betplay.com.co/apuestas#event/1029306638"

modo["odds"] = "vivo"
conn.execute("DELETE FROM oddspapi_enlaces")
conn.execute("DELETE FROM oddspapi_consultas")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
rv = resolver("betplay_co")
ok(rv["estado"] == "ERROR" and "juego" in rv.get("detalle", ""),
   "partido en juego sin enlace guardado: ERROR explicado")
modo["odds"] = "ok"
conn.execute("DELETE FROM oddspapi_consultas")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
resolver("betplay_co")                                  # se guarda antes de empezar
modo["odds"] = "vivo"
conn.execute("DELETE FROM provider_event_map")
conn.execute("UPDATE oddspapi_consultas SET consultado_en='2000-01-01T00:00:00+00:00'")
conn.commit()
ok(resolver("betplay_co")["estado"] == "ENCONTRADO",
   "enlace guardado antes del partido: sigue sirviendo con el partido en juego")
modo["odds"] = "ok"

config.MODO_PRUEBA.add("oddspapi_caido")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(resolver("draftkings_nc")["estado"] == "ERROR", "MODO_PRUEBA oddspapi_caido: ERROR")
config.MODO_PRUEBA.clear()
clave_guardada = config.ODDSPAPI_API_KEY
config.ODDSPAPI_API_KEY = ""
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(resolver("draftkings_nc")["estado"] == "PROVIDER_PENDING", "sin clave de OddsPapi: pendiente")
config.ODDSPAPI_API_KEY = clave_guardada

ok(op.ajustar_url("kalshi", "https://kalshi.com/markets/kxatpmatch/e#kxatpmatch-26sep28vacblo")
   == "https://kalshi.com/markets/KXATPMATCH/x/KXATPMATCH-26SEP28VACBLO",
   "Kalshi: el evento pasa de tras '#' a la ruta del partido")
ok(op.ajustar_url("kalshi", "https://kalshi.com/markets/KXATPMATCH/x/KXATPMATCH-26AUG30TIRMAN")
   == "https://kalshi.com/markets/KXATPMATCH/x/KXATPMATCH-26AUG30TIRMAN",
   "Kalshi: un enlace ya correcto no se toca")
ok(op.ajustar_url("betmgm_nc", "https://sports.{state}.betmgm.com/en/sports/events/1")
   == "https://sports.nc.betmgm.com/en/sports/events/1", "BetMGM con {state}: nc")

print("\n9. Precarga: enlaces pedidos ANTES de que empiece el partido")
from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402
for t in ("fixtures_cache", "oddspapi_fixtures", "oddspapi_enlaces", "oddspapi_consultas"):
    conn.execute(f"DELETE FROM {t}")
conn.commit()
_ahora = _dt.now(_tz.utc)


def _iso(m):
    return (_ahora + _td(minutes=m)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


PARTIDOS = [("idPronto", "Pronto, Pablo", "Luego, Lucas", 30, True),      # empieza en 30 min
            ("idJugando", "Jugando, Juan", "Vivo, Victor", -60, True),    # ya empezó
            ("idLejos", "Lejos, Leo", "Tarde, Tomas", 300, True),         # dentro de 5 h
            ("idItf", "Itf, Ivan", "Sinhora, Sergio", 120, False),        # ITF sin hora, hoy
            ("idHecho", "Hecho, Hugo", "Previo, Pedro", 20, True)]        # ya pedido
op.guardar_fixtures(conn, [{"fixtureId": f, "participant1Name": a, "participant2Name": b,
                            "startTime": _iso(m), "hasOdds": True, "categorySlug": "challenger"}
                           for f, a, b, m, _ in PARTIDOS])
for f, a, b, m, hora in PARTIDOS:
    nom = lambda n: " ".join(reversed([x.strip() for x in n.split(",")]))  # noqa: E731
    fecha = _iso(m) if hora else _iso(m)[:10]
    sync.guardar_fixture(conn, {"fixture_id": "ft-" + f, "fecha": fecha, "jugador1": nom(a),
                                "jugador2": nom(b), "torneo": "Challenger X", "genero": "M"},
                         "fixtures")
conn.execute("INSERT INTO oddspapi_consultas VALUES ('idHecho', ?, 'ok')", (_ahora.isoformat(),))
conn.commit()
pedidos_pre = []
modo_pre = {"429": False}


def oddspapi_pre(request: httpx.Request):
    fid = request.url.params.get("fixtureId")
    pedidos_pre.append(fid)
    if modo_pre["429"]:
        return httpx.Response(429, json={"error": {"code": "RATE_LIMITED"}})
    return httpx.Response(200, json={"bookmakerOdds": {
        "betplay": {"fixturePath": f"https://tienda.betplay.com.co/apuestas#event/{fid}"}}})


providers.ODDSPAPI._transporte = httpx.MockTransport(oddspapi_pre)
config.ODDSPAPI_PAUSA_MS = 0
pend = providers.ODDSPAPI._pendientes_de_precarga(conn, 90)
ok(set(pend) == {"idPronto", "idItf"},
   f"ventana de 90 min: solo los que empiezan pronto y los ITF de hoy sin hora ({pend})")
ok(pend[0] == "idPronto" or pend[0] == "idItf", "ordenados por inicio")
modo_pre["429"] = True
r = asyncio.run(providers.ODDSPAPI.precargar(conn, 90, 10))
ok(r["cortado"] == "429" and len(pedidos_pre) == 1, "límite de OddsPapi (429): corta el ciclo y sigue en el próximo")
modo_pre["429"] = False
conn.execute("DELETE FROM oddspapi_consultas WHERE fixture_id != 'idHecho'")
conn.commit()
pedidos_pre.clear()
r = asyncio.run(providers.ODDSPAPI.precargar(conn, 90, 1))
ok(r["pedidos"] == 1 and len(pedidos_pre) == 1, "respeta el máximo por ciclo")
r = asyncio.run(providers.ODDSPAPI.precargar(conn, 90, 10))
ok(r["pedidos"] == 1 and set(pedidos_pre) == {"idPronto", "idItf"},
   "el siguiente ciclo pide solo lo que faltaba (nunca repite)")
ok("idJugando" not in pedidos_pre and "idLejos" not in pedidos_pre and "idHecho" not in pedidos_pre,
   "no pide los ya empezados, los lejanos ni los ya pedidos")
ok("precarga" in conn.execute("SELECT group_concat(clave) FROM sync_estado").fetchone()[0],
   "deja constancia en /salud")

# Con el partido ya en juego (plan gratuito), el enlace precargado sigue sirviendo.
clave_pre = claves.clave_partido("ft-idPronto", _iso(30), "Pablo Pronto", "Lucas Luego")
conn.execute("UPDATE provider_catalog SET metodo='oddspapi', estado='TESTING' WHERE id='betplay_co'")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
providers.ODDSPAPI._transporte = httpx.MockTransport(
    lambda r: httpx.Response(403, json={"error": {"code": "RESTRICTED_ACCESS"}}))
rp = cli2.get("/api/resolver", params={"clave": clave_pre, "provider": "betplay_co"}, headers=H).json()
ok(rp["estado"] == "ENCONTRADO" and rp["url"].endswith("idPronto"),
   "partido ya en juego: abre con el enlace precargado")

print("\n10. Barrido por torneos (flujo MTO: partido siempre en juego)")
import sqlite3 as _sq  # noqa: E402
_vieja = _sq.connect(":memory:")
_vieja.row_factory = _sq.Row
_vieja.execute("CREATE TABLE oddspapi_fixtures (fixture_id TEXT PRIMARY KEY, dia TEXT, inicio TEXT, "
               "jugador1 TEXT, jugador2 TEXT, torneo TEXT, categoria TEXT, tiene_cuotas INTEGER, "
               "actualizado_en TEXT)")
db.inicializar(_vieja)
ok("torneo_id" in {r[1] for r in _vieja.execute("PRAGMA table_info(oddspapi_fixtures)")},
   "base anterior: se añade la columna del torneo sin perder datos")

for t in ("fixtures_cache", "oddspapi_fixtures", "oddspapi_enlaces", "oddspapi_consultas"):
    conn.execute(f"DELETE FROM {t}")
conn.commit()
# 7 torneos con partidos próximos (T1 con 3) + 1 torneo lejano (fuera de la ventana)
LISTA_B = [{"fixtureId": f"idB{t}{j}", "participant1Name": f"Uno{t}{j}, A",
            "participant2Name": f"Dos{t}{j}, B", "startTime": _iso(60 + j),
            "hasOdds": True, "categorySlug": "itf-men", "tournamentId": 100 + t}
           for t in range(1, 8) for j in range(3 if t == 1 else 1)]
LISTA_B.append({"fixtureId": "idLejano", "participant1Name": "Lejano, L", "participant2Name": "Otro, O",
                "startTime": _iso(60 * 24 * 5), "hasOdds": True, "tournamentId": 999})
op.guardar_fixtures(conn, LISTA_B)
conn.commit()
tor = providers.ODDSPAPI.torneos_para_barrido(conn, 30)
ok(tor[0] == "101" and "999" not in tor and len(tor) == 7,
   "torneos de la ventana, el de más partidos primero; fuera los lejanos")
peticiones_b = []
modo_b = {"429_en": None}


def oddspapi_barrido(request: httpx.Request):
    peticiones_b.append((request.url.path, dict(request.url.params)))
    if modo_b["429_en"] and len(peticiones_b) >= modo_b["429_en"]:
        return httpx.Response(429, json={"error": {"code": "RATE_LIMITED"}})
    casa = request.url.params["bookmaker"]
    ids = request.url.params["tournamentIds"].split(",")
    salida = [{"fixtureId": f["fixtureId"], "bookmakerOdds": {casa: {
        "fixturePath": f"https://{casa}.example/event/{f['fixtureId']}",
        "markets": {"1": {"outcomes": {}}}}}}
        for f in LISTA_B if str(f["tournamentId"]) in ids]
    salida.append({"fixtureId": "idFuturo", "bookmakerOdds": {casa: {   # de días siguientes
        "fixturePath": f"https://{casa}.example/event/idFuturo"}}})
    return httpx.Response(200, json=salida)


providers.ODDSPAPI._transporte = httpx.MockTransport(oddspapi_barrido)
r = asyncio.run(providers.ODDSPAPI.barrer(conn, 30, 100, casas=["betplay", "draftkings"]))
ok(r["lotes"] == 2 and r["peticiones"] == 4, f"7 torneos = 2 lotes de 5; 2 casas = 4 peticiones ({r})")
ok(all(len(q["tournamentIds"].split(",")) <= 5 for _, q in peticiones_b),
   "nunca más de 5 torneos por petición (límite de OddsPapi)")
ok(all(q_path.endswith("/odds-by-tournaments") for q_path, _ in peticiones_b), "usa /odds-by-tournaments")
n_enl = conn.execute("SELECT COUNT(*) FROM oddspapi_enlaces WHERE bookmaker='betplay'").fetchone()[0]
ok(n_enl == 10, f"guarda el enlace de TODOS los partidos de la casa, incluidos días siguientes ({n_enl})")
ok(conn.execute("SELECT COUNT(*) FROM oddspapi_enlaces WHERE url LIKE '%markets%'").fetchone()[0] == 0,
   "solo el enlace: nada de cuotas")
peticiones_b.clear()
modo_b["429_en"] = 2
r = asyncio.run(providers.ODDSPAPI.barrer(conn, 30, 100, casas=["betplay", "draftkings"]))
ok(r["cortado"] == "429" and len(peticiones_b) == 2, "límite de OddsPapi (429): corta el barrido")
modo_b["429_en"] = None
peticiones_b.clear()
r = asyncio.run(providers.ODDSPAPI.barrer(conn, 30, 3, casas=["betplay", "draftkings"]))
ok(r["peticiones"] == 3 and r["cortado"], "respeta el máximo de peticiones por barrido")

# MTO: el partido ya está en juego y OddsPapi no da nada en vivo -> abre con lo barrido
sync.guardar_fixture(conn, {"fixture_id": "ft-mto", "fecha": _iso(-30), "jugador1": "A Uno10",
                            "jugador2": "B Dos10", "torneo": "M25 X", "genero": "M"}, "fixtures")
conn.execute("UPDATE oddspapi_fixtures SET inicio=?, dia=? WHERE fixture_id='idB10'",
             (_iso(-30), _iso(-30)[:10]))
conn.execute("UPDATE provider_catalog SET dominios=? WHERE id='betplay_co'",
             ('["betplay.example"]',))
conn.execute("DELETE FROM provider_event_map")
conn.commit()
providers.ODDSPAPI._transporte = httpx.MockTransport(
    lambda r: httpx.Response(403, json={"error": {"code": "RESTRICTED_ACCESS"}}))
clave_mto = claves.clave_partido("ft-mto", _iso(-30), "A Uno10", "B Dos10")
rm = cli2.get("/api/resolver", params={"clave": clave_mto, "provider": "betplay_co"}, headers=H).json()
ok(rm["estado"] == "ENCONTRADO" and rm["url"].endswith("idB10"),
   "MTO con el partido en juego: abre con el enlace del barrido, sin pedir nada")
conn.execute("UPDATE provider_catalog SET dominios=? WHERE id='betplay_co'", ('["betplay.com.co"]',))
conn.commit()

print("\n11. Fuentes gratuitas (estructura de las capturas HAR reales)")
import time as _t  # noqa: E402
from urllib.parse import urlparse as urlparse_  # noqa: E402
from buscador.providers import fuentes as fu  # noqa: E402

catalogo.sembrar(conn)
conn.execute("UPDATE provider_catalog SET metodo=?, estado='TESTING', dominios=? WHERE id=?",
             ("kambi", '["betplay.com.co"]', "betplay_co"))
conn.execute("UPDATE provider_catalog SET metodo=?, estado='TESTING', dominios=? WHERE id=?",
             ("kambi", '["rushbet.co"]', "rushbet_co"))
conn.execute("UPDATE provider_catalog SET metodo='fanduel', estado='TESTING', dominios='[\"fanduel.com\"]' "
             "WHERE id='fanduel_nc'")
conn.execute("UPDATE provider_catalog SET metodo='draftkings', estado='TESTING', "
             "dominios='[\"draftkings.com\"]' WHERE id='draftkings_nc'")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
HOY = _iso(-40)
KAMBI_R = {"liveEvents": [
    {"event": {"id": 1029296001, "homeName": "Jiri Lehecka", "awayName": "Zizou Bergs", "sport": "TENNIS",
               "group": "Tokio", "state": "STARTED", "start": HOY}},
    {"event": {"id": 1029300000, "homeName": "Lehecka J/Otro A", "awayName": "Bergs Z/Otro B",
               "sport": "TENNIS", "state": "STARTED", "start": HOY}},
    {"event": {"id": 5, "homeName": "Arsenal", "awayName": "Chelsea", "sport": "FOOTBALL", "start": HOY}}]}
FD_R = {"attachments": {
    "events": {"36127007": {"eventId": 36127007, "name": "Jiri Lehecka v Zizou Bergs", "competitionId": 1,
                            "openDate": HOY, "inPlay": True},
               "35218498": {"eventId": 35218498, "name": "Men's Australian Open 2027", "competitionId": 2,
                            "openDate": "2027-01-17T00:00:00.000Z"}},
    "competitions": {"1": {"name": "ATP Tokyo 2026"}, "2": {"name": "Australian Open 2027"}}}}
DK_R = {"events": [{"id": "34742219", "seoIdentifier": "jiri-lehecka-vs-zizou-bergs", "sportId": "6",
                    "name": "Jiri Lehecka vs Zizou Bergs", "startEventDate": HOY, "status": "STARTED",
                    "participants": [{"name": "Jiri Lehecka", "venueRole": "Home", "sortOrder": 1},
                                     {"name": "Zizou Bergs", "venueRole": "Away", "sortOrder": 2}]}]}
CZ_R = [{"eventId": "ca32cb2b-0584-475f-b5fa-eaf91d79a37e", "startTime": HOY, "started": True,
         "eventDisplay": {"teams": ["Alejandro Tabilo", "Tommy Paul"]}, "competitionName": "ATP Tokyo"}]
vistas_f = []
modo_f = {"kambi": 200}


def fuentes_falsas(request: httpx.Request):
    vistas_f.append(request)
    h = request.url.host
    if "kambicdn" in h:
        return httpx.Response(modo_f["kambi"], json=KAMBI_R)
    if "fanduel" in h:
        return httpx.Response(200, json=FD_R)
    if "draftkings" in h:
        return httpx.Response(200, json=DK_R)
    if "americanwagering" in h:
        return httpx.Response(200, json=CZ_R)
    return httpx.Response(404)


for f_ in fu.FUENTES.values():
    f_._transporte = httpx.MockTransport(fuentes_falsas)
    for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
    f_._eventos, f_._cuando, f_._error = [], 0.0, ""
config.FANDUEL_AK = "ak-de-prueba"
sync.guardar_fixture(conn, {"fixture_id": "ft-mto2", "fecha": HOY, "jugador1": "Zizou Bergs",
                            "jugador2": "Jiri Lehecka", "torneo": "ATP Tokyo", "genero": "M"}, "fixtures")
conn.commit()
clave_f = claves.clave_partido("ft-mto2", HOY, "Zizou Bergs", "Jiri Lehecka")


def res_f(pid, clave=None):
    return cli2.get("/api/resolver", params={"clave": clave or clave_f, "provider": pid}, headers=H).json()


rb, rr = res_f("betplay_co"), res_f("rushbet_co")
ok(rb["url"] == "https://tienda.betplay.com.co/apuestas#event/1029296001"
   and rr["url"] == "https://www.rushbet.co/?page=sportsbook#event/1029296001",
   "Kambi: BetPlay y Rushbet con el MISMO número, cada una con su dominio")
ok(len([r for r in vistas_f if "kambicdn" in r.url.host]) == 1,
   "Kambi: una sola lectura sirve para las dos casas (caché)")
ok("/betplay/event/live/open.json" in str([r.url for r in vistas_f if "kambicdn" in r.url.host][0]),
   "Kambi: lee la lista de partidos EN VIVO")
ok(res_f("fanduel_nc")["url"] ==
   "https://sportsbook.fanduel.com/tennis/atp-tokyo-2026/jiri-lehecka-v-zizou-bergs-36127007",
   "FanDuel: enlace /tennis/<torneo>/<a-v-b>-<número>")
rq_fd = [r for r in vistas_f if "fanduel" in r.url.host][0]
ok(rq_fd.headers.get("x-sportsbook-region") == "NC" and rq_fd.url.params.get("eventTypeId") == "2",
   "FanDuel: pide el tenis con la región NC")
ok(res_f("draftkings_nc")["url"] == "https://sportsbook.draftkings.com/event/jiri-lehecka-vs-zizou-bergs/34742219",
   "DraftKings: enlace /event/<seo>/<número>")
rq_dk = [r for r in vistas_f if "draftkings" in r.url.host][0]
ok(rq_dk.headers.get("origin") == "https://sportsbook.draftkings.com" and rq_dk.headers.get("sec-fetch-mode") == "cors",
   "DraftKings: envía los encabezados de su web (sin ellos responde 403)")
ok(all("cookie" not in {k.lower() for k in r.headers.keys()} for r in vistas_f),
   "ninguna fuente envía cookies")

sync.guardar_fixture(conn, {"fixture_id": "ft-cz", "fecha": HOY, "jugador1": "Tabilo A.",
                            "jugador2": "Paul T.", "torneo": "ATP Tokyo", "genero": "M"}, "fixtures")
conn.execute("UPDATE provider_catalog SET estado='TESTING' WHERE id='caesars_nc'")
conn.commit()
clave_cz = claves.clave_partido("ft-cz", HOY, "Tabilo A.", "Paul T.")
rc = res_f("caesars_nc", clave_cz)
ok(rc["url"] == "https://sportsbook.caesars.com/tennis/ca32cb2b-0584-475f-b5fa-eaf91d79a37e/alejandro-tabilo-vs-tommy-paul",
   "Caesars: enlace /tennis/<id>/<a-vs-b>, con nombres de FullTenis tipo 'Tabilo A.'")
ok("/locations/nc/" in str([r.url for r in vistas_f if "americanwagering" in r.url.host][0]),
   "Caesars: pide el calendario de Carolina del Norte")

pp = Partido("x", "Jiri Lehecka", "Otro Jugador", HOY, True)
ok(fu.emparejar(pp, fu.FUENTES["kambi"]._eventos)[0] == NO_ENCONTRADO, "un solo jugador: no empareja")
ok(all("/" not in e["j1"] for e in fu.FUENTES["kambi"]._eventos), "dobles fuera")
dup = [{"id": 1, "j1": "Jiri Lehecka", "j2": "Zizou Bergs", "inicio": HOY},
       {"id": 2, "j1": "Zizou Bergs", "j2": "Jiri Lehecka", "inicio": HOY}]
ok(fu.emparejar(Partido("x", "Jiri Lehecka", "Zizou Bergs", HOY, True), dup)[0] == AMBIGUO,
   "dos partidos distintos que encajan igual: AMBIGUO")

# Flujo MTO: partido que empezó después de la última lectura
KAMBI_R["liveEvents"].append({"event": {"id": 1029400000, "homeName": "Nuevo Jugador",
                                        "awayName": "Recien Empezado", "sport": "TENNIS",
                                        "state": "STARTED", "start": HOY}})
fu.FUENTES["kambi"]._cuando = _t.monotonic() - 20
sync.guardar_fixture(conn, {"fixture_id": "ft-nuevo", "fecha": HOY, "jugador1": "Nuevo Jugador",
                            "jugador2": "Recien Empezado", "torneo": "M25", "genero": "M"}, "fixtures")
conn.commit()
rn = res_f("betplay_co", claves.clave_partido("ft-nuevo", HOY, "Nuevo Jugador", "Recien Empezado"))
ok(rn["estado"] == "ENCONTRADO", "partido recién empezado: relee la fuente y lo encuentra")

# Fuente caída
modo_f["kambi"] = 403
fu.FUENTES["kambi"]._cuando = _t.monotonic() - 60
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betplay_co")["estado"] == "ENCONTRADO", "fuente que falla un momento: sirve la última lista buena")
fu.FUENTES["kambi"]._eventos, fu.FUENTES["kambi"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betplay_co")["estado"] == "ERROR" and res_f("draftkings_nc")["estado"] == "ENCONTRADO",
   "fuente bloqueada sin datos: ERROR solo en esa casa, las demás siguen")
modo_f["kambi"] = 200
config.MODO_PRUEBA.add("fuente_caida:kambi")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("rushbet_co")["estado"] == "ERROR", "MODO_PRUEBA fuente_caida:kambi")
config.MODO_PRUEBA.clear()
config.FANDUEL_AK = ""
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("fanduel_nc")["estado"] == "PROVIDER_PENDING", "FanDuel sin FANDUEL_AK: pendiente, sin consultar")
# Kalshi: API oficial, una petición por serie; las series que no existen se saltan
KALSHI_R = {"events": [
    {"event_ticker": "KXATPMATCH-26SEP30LEHBER", "series_ticker": "KXATPMATCH", "title": "Lehecka vs Bergs",
     "markets": [{"yes_sub_title": "Jiri Lehecka"}, {"yes_sub_title": "Zizou Bergs"}]},
    {"event_ticker": "KXATPMATCH-26SEP30TABPAU", "series_ticker": "KXATPMATCH",
     "title": "Tabilo vs Paul", "markets": []}]}


def kalshi_falso(request: httpx.Request):
    vistas_f.append(request)
    if request.url.params.get("series_ticker") == "KXATPMATCH":
        return httpx.Response(200, json=KALSHI_R)
    return httpx.Response(404)


fu.FUENTES["kalshi"]._transporte = httpx.MockTransport(kalshi_falso)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kalshi"]._eventos, fu.FUENTES["kalshi"]._cuando = [], 0.0
conn.execute("UPDATE provider_catalog SET metodo='kalshi', estado='TESTING', dominios='[\"kalshi.com\"]' "
             "WHERE id='kalshi'")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
rk = res_f("kalshi")
ok(rk["url"] == "https://kalshi.com/markets/KXATPMATCH/x/KXATPMATCH-26SEP30LEHBER",
   "Kalshi: enlace /markets/<SERIE>/x/<EVENTO> con los nombres de sus mercados")
ok(res_f("kalshi", clave_cz)["url"] == "https://kalshi.com/markets/KXATPMATCH/x/KXATPMATCH-26SEP30TABPAU",
   "Kalshi: si no hay mercados, usa el título 'Tabilo vs Paul'")
ok(all(e["inicio"] == "" for e in fu.FUENTES["kalshi"]._eventos),
   "Kalshi: no confunde el cierre del mercado con la hora del partido")

# BetMGM (Entain) y Polymarket (API oficial)
MGM_R = {"fixtures": [{"id": "19972424", "name": {"value": "Jiri Lehecka (CZE) - Zizou Bergs (BEL)"},
                       "participants": [{"name": {"value": "Jiri Lehecka (CZE)"}},
                                        {"name": {"value": "Zizou Bergs (BEL)"}}],
                       "stage": "Live", "startDate": HOY, "sport": {"id": 5}}]}
POLY_R = [{"slug": "atp-lehecka-bergs-" + HOY[:10], "title": "ATP: Lehecka vs Bergs",
           "markets": [{"outcomes": "[\"Lehecka\", \"Bergs\"]"}]},
          {"slug": "quien-gana-el-torneo", "title": "Who will win Tokyo?",
           "markets": [{"outcomes": "[\"Yes\", \"No\"]"}]}]
vistas_mp = []


def mgm_poly(request: httpx.Request):
    vistas_mp.append(request)
    if "betmgm" in request.url.host:
        return httpx.Response(200, json=MGM_R)
    return httpx.Response(200, json=POLY_R)


for m_ in ("betmgm", "polymarket"):
    fu.FUENTES[m_]._transporte = httpx.MockTransport(mgm_poly)
    for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
    fu.FUENTES[m_]._eventos, fu.FUENTES[m_]._cuando = [], 0.0
config.BETMGM_ACCESSID = "accessid-de-prueba"
conn.execute("UPDATE provider_catalog SET metodo='betmgm', estado='TESTING', dominios='[\"betmgm.com\"]' "
             "WHERE id='betmgm_nc'")
conn.execute("UPDATE provider_catalog SET metodo='polymarket', estado='TESTING', "
             "dominios='[\"polymarket.com\"]' WHERE id='polymarket'")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betmgm_nc")["url"] == "https://www.nc.betmgm.com/en/sports/events/jiri-lehecka-cze-zizou-bergs-bel-19972424",
   "BetMGM: enlace /en/sports/events/<nombre>-<id>, igual que la captura")
q_mgm = [r for r in vistas_mp if "betmgm" in r.url.host][0].url.params
ok(q_mgm.get("sportIds") == "5" and q_mgm.get("state") == "Live" and q_mgm.get("x-bwin-accessid"),
   "BetMGM: pide tenis (5) en vivo con su código público")
ok(res_f("polymarket")["url"] == "https://polymarket.com/event/atp-lehecka-bergs-" + HOY[:10],
   "Polymarket: enlace /event/<slug> con los nombres de sus resultados")
ok(len(fu.FUENTES["polymarket"]._eventos) == 1, "Polymarket: fuera los mercados Sí/No que no son partidos")
llamadas_chrome = []


async def curl_falso(url, params, headers, timeout, proxy=None):
    llamadas_chrome.append((url, headers.get("Origin")))
    import json as _j
    return 200, _j.dumps(MGM_R).encode()

_curl_orig = fu._curl_get
fu._curl_get = curl_falso
fu.FUENTES["betmgm"]._transporte = None
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["betmgm"]._eventos, fu.FUENTES["betmgm"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betmgm_nc")["estado"] == "ENCONTRADO" and len(llamadas_chrome) == 1
   and llamadas_chrome[0][1] == "https://www.nc.betmgm.com",
   "BetMGM: usa la conexión con huella de Chrome (FUENTES_IMITAR_CHROME)")
vistos_poly_http = len([r for r in vistas_mp if "polymarket" in r.url.host])
ok(vistos_poly_http >= 1, "las demás fuentes siguen con la conexión normal")
config.FUENTES_IMITAR_CHROME = set()
llamadas_chrome.clear()
fu.FUENTES["betmgm"]._transporte = httpx.MockTransport(lambda r: httpx.Response(403))
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["betmgm"]._eventos, fu.FUENTES["betmgm"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betmgm_nc")["estado"] == "ERROR" and not llamadas_chrome,
   "FUENTES_IMITAR_CHROME vacío: BetMGM vuelve a la conexión normal (y la casa la rechaza)")
# Proxy por fuente: solo la fuente configurada lo usa, y nunca se muestra
proxies_vistos = []


async def curl_con_proxy(url, params, headers, timeout, proxy=None):
    proxies_vistos.append((url.split("/")[2], proxy))
    import json as _j
    return 200, _j.dumps(MGM_R).encode()

fu._curl_get = curl_con_proxy
config.FUENTES_IMITAR_CHROME = {"betmgm"}
config.FUENTES_PROXY = {"betmgm": "http://usuario:SECRETO@proxy.example:8000"}
fu.FUENTES["betmgm"]._transporte = None
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["betmgm"]._eventos, fu.FUENTES["betmgm"]._cuando = [], 0.0
config.BETMGM_ACCESSID = "accessid-de-prueba"
conn.execute("DELETE FROM provider_event_map")
conn.commit()
res_f("betmgm_nc")
ok(proxies_vistos and proxies_vistos[0][1] == "http://usuario:SECRETO@proxy.example:8000",
   "proxy por fuente: la fuente configurada sale por su proxy")
sal_p = cli2.get("/salud").text
ok("SECRETO" not in sal_p and '"proxy":true' in sal_p.replace(" ", ""),
   "proxy por fuente: /salud dice que hay proxy, pero nunca su dirección ni su clave")
ok(config._proxies("betano=http://a:b@h:1, otra=http://c@d:2") == {"betano": "http://a:b@h:1", "otra": "http://c@d:2"},
   "FUENTES_PROXY: formato 'fuente=url,fuente=url'")
ok(config.normalizar_proxy("co.proxy.example:12321:usuario-country-co:cl@ve") ==
   "http://usuario-country-co:cl%40ve@co.proxy.example:12321",
   "proxy en formato host:puerto:usuario:clave se convierte (y la clave se codifica)")
config.FUENTES_PROXY = {}
config.BETMGM_ACCESSID = ""
fu._curl_get = _curl_orig
config.FUENTES_IMITAR_CHROME = {"betmgm"}

# Polymarket: partidos pasados que siguen 'abiertos' y fecha desde el slug
POLY_R.append({"slug": "itf-lehecka-bergs-2026-06-17", "title": "ITF: Lehecka vs Bergs",
               "markets": [{"outcomes": "[\"Lehecka\", \"Bergs\"]"}]})
POLY_R[0]["slug"] = "atp-lehecka-bergs-" + HOY[:10]
fu.FUENTES["polymarket"]._eventos, fu.FUENTES["polymarket"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
rp_ = res_f("polymarket")
ok(rp_["estado"] == "ENCONTRADO" and rp_["url"].endswith(HOY[:10]),
   "Polymarket: descarta el partido de junio de los mismos jugadores y usa la fecha del slug")

config.BETMGM_ACCESSID = ""
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betmgm_nc")["estado"] == "PROVIDER_PENDING", "BetMGM sin BETMGM_ACCESSID: pendiente")

# ── Colombia: Betano, Wplay y Bwin ──
BETANO_AV = {"liveEvents": {"a": {"eventId": 93269367, "sportId": "TENN"},
                            "b": {"eventId": 93349460, "sportId": "FOOT"}}}
_ms_hoy = int(_dt.fromisoformat(HOY.replace("Z", "+00:00")).timestamp() * 1000)
BETANO_EV = {"event": {"id": 93269367, "sportId": "TENN", "startTime": _ms_hoy,
                       "participants": [{"name": "Jiri Lehecka", "isHome": True}, {"name": "Zizou Bergs"}],
                       "url": "/live/jiri-lehecka-zizou-bergs/93269367/"}}
WPLAY_HTML = ('''<div class="expander event sport-TENN expander-collapsed load-on-click mkt mkt-932690621" data-mkt_id="932690621">
 <h6 class="expander-E33387591 expander-button" title="Jiri Lehecka v Zizou Bergs">
 <a href="/es/e/33387591/Jiri-Lehecka-v-Zizou-Bergs" > Jiri Lehecka v Zizou Bergs </a></h6></div>
<div class="expander event sport-FOOT expander-collapsed" data-mkt_id="1"><h6 class="x" title="Roma v Lazio">
 <a href="/es/e/33391887/Roma-v-Lazio" >Roma v Lazio</a></h6></div>
<div class="expander event sport-TENN expander-collapsed" data-mkt_id="2"><h6 class="x" title="A. Uno/B. Dos v C. Tres/D. Cuatro">
 <a href="/es/e/33399999/Dobles" >dobles</a></h6></div>''')
WPLAY_EXTRA = ('''<div class="expander event sport-TENN expander-collapsed" data-mkt_id="9">
 <h6 class="x" title="Elias Ymer v Terence Atmane"><a href="/es/e/33387592/Elias-Ymer-v-Terence-Atmane" >x</a></h6></div>''')
vistas_co = []


def colombia_falsa(request: httpx.Request):
    vistas_co.append(request)
    if "betano" in request.url.host:
        if request.url.path.endswith("/availabilities/latest"):
            return httpx.Response(200, json=BETANO_AV)
        return httpx.Response(200, json=BETANO_EV)
    if "wplay" in request.url.host:
        if request.url.path.startswith("/es/e/"):          # página de un partido: barra completa
            return httpx.Response(200, text=WPLAY_HTML + WPLAY_EXTRA)
        return httpx.Response(200, text=WPLAY_HTML)
    return httpx.Response(404)


for m_ in ("betano", "wplay"):
    fu.FUENTES[m_]._transporte = httpx.MockTransport(colombia_falsa)
    for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
    fu.FUENTES[m_]._eventos, fu.FUENTES[m_]._cuando = [], 0.0
catalogo.sembrar(conn)
conn.execute("DELETE FROM provider_event_map")
conn.commit()
rbet = res_f("betano_co")
ok(rbet["url"] == "https://www.betano.co/live/jiri-lehecka-zizou-bergs/93269367/",
   "Betano: enlace con la dirección que da su propia ficha")
rq_b = [r for r in vistas_co if "betano" in r.url.host]
ok(rq_b[0].headers.get("x-operator") == "17" and rq_b[0].headers.get("x-language") == "8",
   "Betano: envía los encabezados fijos de su web (idioma y operador)")
ok(len(rq_b) == 2 and not any("93349460" in str(r.url) for r in rq_b),
   "Betano: solo pide la ficha de los partidos de TENIS (no la del fútbol)")
vistas_co.clear()
fu.FUENTES["betano"]._cuando = 0.0
asyncio.run(fu.FUENTES["betano"].refrescar())
ok(len([r for r in vistas_co if "betano" in r.url.host]) == 1,
   "Betano: la ficha ya guardada no se vuelve a pedir (1 petición por lectura)")
BETANO_AV["liveEvents"].pop("a")
asyncio.run(fu.FUENTES["betano"].refrescar())
ok(fu.FUENTES["betano"]._eventos == [], "Betano: el partido que termina sale de la lista")
BETANO_AV["liveEvents"]["a"] = {"eventId": 93269367, "sportId": "TENN"}
_av_dict = BETANO_AV["liveEvents"]
BETANO_AV["liveEvents"] = list(_av_dict.values())            # por si llega como lista
fu.FUENTES["betano"]._fichas, fu.FUENTES["betano"]._cuando = {}, 0.0
asyncio.run(fu.FUENTES["betano"].refrescar())
ok(len(fu.FUENTES["betano"]._eventos) == 1, "Betano: acepta la lista de partidos como diccionario o como lista")
BETANO_AV["liveEvents"] = _av_dict

rw = res_f("wplay_co")
ok(rw["url"] == "https://apuestas.wplay.co/es/e/33387591/Jiri-Lehecka-v-Zizou-Bergs",
   "Wplay: enlace /es/e/<id>/<slug> de su barra en vivo")
ok(sorted(e["j1"] for e in fu.FUENTES["wplay"]._eventos) == ["Elias Ymer", "Jiri Lehecka"],
   "Wplay: solo tenis (sport-TENN), sin fútbol ni dobles")
ok(len([r for r in vistas_co if "wplay" in r.url.host]) == 2,
   "Wplay: portada + página de un partido en vivo (barra completa), 2 peticiones")

# Betano: leer de otro país y enlazar a Colombia con el mismo número
config.BETANO_HOST = "ro.betano.com"
fu.FUENTES["betano"]._fichas, fu.FUENTES["betano"]._eventos, fu.FUENTES["betano"]._cuando = {}, [], 0.0
vistas_co.clear()
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("betano_co")["url"] == "https://www.betano.co/live/jiri-lehecka-zizou-bergs/93269367/"
   and all(r.url.host == "ro.betano.com" for r in vistas_co if "betano" in r.url.host),
   "Betano: lee de otra web (ro.betano.com) y enlaza a betano.co con el mismo número")
config.BETANO_HOST = "www.betano.co"
fu.FUENTES["wplay"]._transporte = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>otra cosa</html>"))
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["wplay"]._eventos, fu.FUENTES["wplay"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("wplay_co")["estado"] == "ERROR",
   "Wplay: si la página no trae la barra en vivo, ERROR claro (no 'no encontrado')")

config.BETMGM_ACCESSID = "accessid-de-prueba"
fu.FUENTES["betmgm"]._transporte = httpx.MockTransport(lambda r: httpx.Response(200, json=MGM_R))
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["betmgm"]._eventos, fu.FUENTES["betmgm"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("bwin_co")["url"] == "https://sports.bwin.co/es/sports/eventos/19972424",
   "Bwin Colombia: mismo número que BetMGM, en sports.bwin.co")
config.BETMGM_ACCESSID = ""

pedidas_k = []


def kalshi_sin_red(request: httpx.Request):
    pedidas_k.append(request)
    raise httpx.ConnectTimeout("no responde")


fu.FUENTES["kalshi"]._transporte = httpx.MockTransport(kalshi_sin_red)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kalshi"]._eventos, fu.FUENTES["kalshi"]._cuando = [], 0.0
try:
    asyncio.run(fu.FUENTES["kalshi"].refrescar())
    ok(False, "Kalshi inalcanzable: error")
except fu.ErrorRed:
    ok(len(pedidas_k) == 1, "Kalshi inalcanzable: se rinde en la 1.ª serie, no prueba las 6")


async def _lenta(req):
    await asyncio.sleep(30)
    return httpx.Response(200, json={})

fu.FUENTES["kalshi"]._transporte = httpx.MockTransport(_lenta)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kalshi"]._eventos, fu.FUENTES["kalshi"]._cuando = [], 0.0
_orig = fu.TIEMPO_MAX_FUENTE_S
fu.TIEMPO_MAX_FUENTE_S = 1
config_to = config.TIMEOUT_PROVIDER_S
config.TIMEOUT_PROVIDER_S = 60
t0 = _t.time()
res_todas = asyncio.run(fu.refrescar_todas())
ok(_t.time() - t0 < 5 and res_todas["kalshi"].startswith("✗") and res_todas["kambi"].endswith("partidos"),
   "todas las fuentes a la vez: una lenta no frena a las demás (" + str(round(_t.time() - t0, 1)) + " s)")
fu.TIEMPO_MAX_FUENTE_S, config.TIMEOUT_PROVIDER_S = _orig, config_to

# Respaldo: sección de tenis de la casa cuando no hay enlace directo
catalogo.sembrar(conn)
fu.FUENTES["kambi"]._transporte = httpx.MockTransport(lambda r: httpx.Response(403))
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kambi"]._eventos, fu.FUENTES["kambi"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
r_err = res_f("betplay_co")
ok(r_err["estado"] == "ERROR" and r_err.get("respaldo") == "https://tienda.betplay.com.co/apuestas#filter/tennis",
   "respaldo: fuente caída → sección de tenis de la casa")
fu.FUENTES["kambi"]._transporte = httpx.MockTransport(fuentes_falsas)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kambi"]._eventos, fu.FUENTES["kambi"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
r_ok = res_f("betplay_co")
ok(r_ok["estado"] == "ENCONTRADO" and "respaldo" not in r_ok, "respaldo: nunca cuando hay enlace directo")
ok(res_f("luckia_co").get("respaldo") is None, "respaldo: nunca en casas pendientes")
catalogo.RESPALDO["betplay_co"] = "https://malicioso.example/tenis"
fu.FUENTES["kambi"]._transporte = httpx.MockTransport(lambda r: httpx.Response(403))
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kambi"]._eventos, fu.FUENTES["kambi"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok("respaldo" not in res_f("betplay_co"), "respaldo: fuera de los dominios de la casa, nunca se entrega")
catalogo.RESPALDO["betplay_co"] = "https://tienda.betplay.com.co/apuestas#filter/tennis"
ok(all(any(urlparse_(u).hostname == d or urlparse_(u).hostname.endswith("." + d)
           for d in next(x for x in catalogo.SEMILLA if x["id"] == pid)["dominios"])
       for pid, u in catalogo.RESPALDO.items()),
   "todas las direcciones de respaldo pertenecen a los dominios de su casa")
fu.FUENTES["kambi"]._transporte = httpx.MockTransport(fuentes_falsas)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["kambi"]._eventos, fu.FUENTES["kambi"]._cuando = [], 0.0

# Sync: tras un fallo reintenta pronto y, al recuperarse, borra el error antiguo
import buscador.sync as sync_mod  # noqa: E402
esperas, llamadas_sync = [], {"n": 0}


async def sinc_falsa(conn_, cli_):
    llamadas_sync["n"] += 1
    if llamadas_sync["n"] == 1:
        raise RuntimeError("401 de prueba")
    return {"ok": 1}


async def dormir_falso(seg):
    esperas.append(seg)
    if len(esperas) >= 2:
        raise asyncio.CancelledError


_orig_sinc, _orig_sleep = sync_mod.sincronizar_una_vez, sync_mod.asyncio.sleep
sync_mod.sincronizar_una_vez, sync_mod.asyncio.sleep = sinc_falsa, dormir_falso
try:
    asyncio.run(sync_mod.bucle(db.conectar))
except asyncio.CancelledError:
    pass
sync_mod.sincronizar_una_vez, sync_mod.asyncio.sleep = _orig_sinc, _orig_sleep
ok(esperas[0] == 60, "sync: tras un fallo reintenta al minuto (no a los 14)")
ok(conn.execute("SELECT COUNT(*) FROM sync_estado WHERE clave='ultimo_error'").fetchone()[0] == 0,
   "sync: al recuperarse, /salud deja de mostrar el error antiguo")

# Respuesta rápida: una casa que acaba de fallar no hace esperar al usuario
llamadas_lenta = {"n": 0}


async def _casa_lenta(req):
    llamadas_lenta["n"] += 1
    await asyncio.sleep(3)
    return httpx.Response(403)

fu.FUENTES["kambi"]._transporte = httpx.MockTransport(_casa_lenta)
fu.FUENTES["kambi"]._eventos, fu.FUENTES["kambi"]._cuando = [], 0.0
fu.FUENTES["kambi"]._error, fu.FUENTES["kambi"]._fallo_en = "kambi: sin conexión (Timeout)", _t.monotonic()
conn.execute("DELETE FROM provider_event_map")
conn.commit()
t0 = _t.time()
r_rap = res_f("betplay_co")
ok(_t.time() - t0 < 1 and r_rap["estado"] == "ERROR" and r_rap.get("respaldo") and llamadas_lenta["n"] == 0,
   "casa que acaba de fallar: responde al momento con su sección de tenis, sin volver a esperarla")
fu.FUENTES["kambi"]._transporte = httpx.MockTransport(fuentes_falsas)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0

# Búsqueda: el mismo partido registrado dos veces (dos vías) sale una sola vez
_h1 = _iso(-60)
_h2 = (_dt.fromisoformat(_h1.replace("Z", "+00:00")) + _td(hours=2)).isoformat()
sync.guardar_fixture(conn, {"fixture_id": "dup-a", "fecha": _h1, "jugador1": "Jiri Lehecka", "jugador2": "Zizou Bergs",
                            "torneo": "ATP Tokyo - R1", "genero": "M"}, "fixtures")
sync.guardar_fixture(conn, {"fixture_id": "dup-b", "fecha": _h2, "jugador1": "Zizou Bergs", "jugador2": "Jiri Lehecka",
                            "torneo": "Japan Open Tennis Championships", "genero": "M"}, "fixtures")
conn.commit()
lista_dup = cli2.get("/api/partidos", params={"q": "lehecka bergs"}, headers=H).json()["partidos"]
ok(len(lista_dup) == 1, f"búsqueda: el mismo partido registrado dos veces sale una sola vez ({len(lista_dup)})")
ok("proxies" in cli2.get("/salud").json(), "/salud incluye el diagnóstico de salida de los proxies")

# Hard Rock Bet (estructura de la captura del 02/10/2026) y bet365 solo-respaldo
HR_R = {"data": [
    {"id": "5750617385245737388", "name": "Dayana Yastremska vs Maja Chwalinska", "compName": "WTA Beijing",
     "eventTime": str(int(_dt.fromisoformat(HOY.replace("Z", "+00:00")).timestamp() * 1000)),
     "sport": "TENNIS", "inplay": True, "outright": False},
    {"id": "1", "name": "A Uno/B Dos vs C Tres/D Cuatro", "compName": "WTA Beijing", "eventTime": "0",
     "sport": "TENNIS", "inplay": True}], "meta": {"count": 2}}
vistas_hr = []


def hr_falso(request: httpx.Request):
    vistas_hr.append(request)
    return httpx.Response(200, json=HR_R)


fu.FUENTES["hardrock"]._transporte = httpx.MockTransport(hr_falso)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["hardrock"]._eventos, fu.FUENTES["hardrock"]._cuando = [], 0.0
catalogo.sembrar(conn)
sync.guardar_fixture(conn, {"fixture_id": "hr-1", "fecha": HOY, "jugador1": "Yastremska D.",
                            "jugador2": "Chwalinska M.", "torneo": "WTA Beijing", "genero": "F"}, "fixtures")
conn.execute("DELETE FROM provider_event_map")
conn.commit()
clave_hr = claves.clave_partido("hr-1", HOY, "Yastremska D.", "Chwalinska M.")
r_hr = res_f("hardrock_fl", clave_hr)
ok(r_hr["url"] == "https://app.hardrock.bet/competition/wtaBeijing/5750617385245737388",
   "Hard Rock: enlace /competition/<torneo>/<número>, igual que la captura")
q_hr = vistas_hr[0].url.params
ok(q_hr.get("sports") == "TENNIS" and q_hr.get("inplay") == "true" and q_hr.get("channel") == "FLORIDA_ONLINE"
   and "cookie" not in {k.lower() for k in vistas_hr[0].headers.keys()},
   "Hard Rock: pide el tenis en vivo de su estado, sin cookies")
ok(len(fu.FUENTES["hardrock"]._eventos) == 1, "Hard Rock: sin dobles")
r_365 = res_f("bet365_nc", clave_hr)
ok(r_365["estado"] == "NO_ENCONTRADO" and r_365.get("respaldo") == "https://www.nc.bet365.com/#/IP/B13",
   "bet365: casa «solo sección de tenis» (abre su tenis EN VIVO con el apellido copiado)")
ok(any(c["id"] == "bet365_nc" and c["seleccionable"] for c in cli2.get("/api/catalogo", headers=H).json()["providers"]),
   "bet365 y Hard Rock se pueden elegir en la pestaña")

# Casa lenta con TIMEOUT_PROVIDER_S alto: el usuario recibe respuesta (y su
# sección de tenis) ANTES de que la pestaña se rinda (Wplay, 02/10/2026)
async def _wplay_lento(req):
    await asyncio.sleep(10)
    return httpx.Response(200, text="")

_to, _rmax = config.TIMEOUT_PROVIDER_S, config.RESOLVER_MAX_S
config.TIMEOUT_PROVIDER_S, config.RESOLVER_MAX_S = 15, 1
fu.FUENTES["wplay"]._transporte = httpx.MockTransport(_wplay_lento)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["wplay"]._eventos, fu.FUENTES["wplay"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
t0 = _t.time()
r_lento = res_f("wplay_co", clave_hr)
ok(_t.time() - t0 < 3 and r_lento["estado"] == "ERROR" and r_lento.get("respaldo", "").startswith("https://apuestas.wplay.co"),
   f"casa lenta: respuesta en {_t.time() - t0:.1f} s con su sección de tenis (no espera los 15 s)")
config.TIMEOUT_PROVIDER_S, config.RESOLVER_MAX_S = _to, _rmax
fu.FUENTES["wplay"]._transporte = httpx.MockTransport(colombia_falsa)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación

# DraftKings y FanDuel: la lista COMPLETA (capturas del 30/09 y 05/10/2026)
sync.guardar_fixture(conn, {"fixture_id": "luan-1", "fecha": HOY, "jugador1": "Nino Ehrenschneider",
                            "jugador2": "Ryuki Matsuda", "torneo": "ITF Men Luan", "genero": "M"}, "fixtures")
conn.commit()
clave_luan = claves.clave_partido("luan-1", HOY, "Nino Ehrenschneider", "Ryuki Matsuda")
DK_LIVE = {"events": [{"id": "1", "sportId": "6", "name": "A Uno vs B Dos", "status": "STARTED",
                       "startEventDate": HOY, "participants": [{"name": "A Uno", "sortOrder": 1},
                                                               {"name": "B Dos", "sortOrder": 2}]}],
           "sections": [{"name": "ATP - Tokyo", "associatedData": {"leagueIds": ["78721"]}},
                        {"name": "ITF - Luan (M)", "associatedData": {"leagueIds": ["214652"]}}]}
DK_LIGA = {"sports": [{"id": "6"}], "leagues": [{"id": "214652"}], "events": [
    {"id": "34800001", "sportId": "6", "seoIdentifier": "nino-ehrenschneider-vs-ryuki-matsuda",
     "name": "Nino Ehrenschneider vs Ryuki Matsuda", "status": "STARTED", "startEventDate": HOY,
     "participants": [{"name": "Nino Ehrenschneider", "sortOrder": 1}, {"name": "Ryuki Matsuda", "sortOrder": 2}]}]}
vistas_dk = []


def dk_completo(req):
    vistas_dk.append(str(req.url))
    if "/nav/leagues/214652" in str(req.url):
        return httpx.Response(200, json=DK_LIGA)
    if "/nav/leagues/" in str(req.url):
        return httpx.Response(200, json={"events": []})
    return httpx.Response(200, json=DK_LIVE)


fu.FUENTES["draftkings"]._transporte = httpx.MockTransport(dk_completo)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["draftkings"]._eventos, fu.FUENTES["draftkings"]._cuando, fu.FUENTES["draftkings"]._ligas = [], 0.0, {}
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("draftkings_nc", clave_luan).get("url") ==
   "https://sportsbook.draftkings.com/event/nino-ehrenschneider-vs-ryuki-matsuda/34800001",
   "DraftKings: encuentra el ITF de Luan leyendo TODAS sus competiciones en vivo (no solo la portada)")
ok(sum("/nav/leagues/" in u for u in vistas_dk) == 2, "DraftKings: una petición por competición en vivo (2)")
vistas_dk.clear()
fu.FUENTES["draftkings"]._cuando = 0.0
asyncio.run(fu.FUENTES["draftkings"].refrescar())
ok(sum("/nav/leagues/" in u for u in vistas_dk) == 0, "DraftKings: cada competición se relee como mucho cada 2 min")

FD_SPORT = {"attachments": {"events": {}, "competitions": {"12834033": {"name": "ATP Tokyo 2026"}}}}
FD_FACET = {"facets": [{"type": "EVENT", "values": [
    {"key": {"eventId": 36200001}, "next": {"values": [{"value": "true"}]}}]}],
    "attachments": {"events": {"36200001": {"eventId": 36200001, "name": "Nino Ehrenschneider v Ryuki Matsuda",
                                            "eventTypeId": 2, "competitionId": 13000001, "openDate": HOY}},
                    "competitions": {"13000001": {"name": "ITF Men Luan"}}}}
cuerpos_fd = []


def fd_completo(req):
    if req.method == "POST":
        cuerpo = json.loads(req.content)
        cuerpos_fd.append((req.url.host, req.headers.get("x-application"), cuerpo["filter"]))
        if "eventTypeIds" in cuerpo["filter"]:
            return httpx.Response(200, json={"facets": [], "attachments": {}})   # sin resultados por deporte
        return httpx.Response(200, json=FD_FACET)
    return httpx.Response(200, json=FD_SPORT)


import json  # noqa: E402
config.FANDUEL_AK = "ak-de-prueba"
fu.FUENTES["fanduel"]._transporte = httpx.MockTransport(fd_completo)
for _fx in fu.FUENTES.values(): _fx._fallo_en = 0.0   # simular recuperación
fu.FUENTES["fanduel"]._eventos, fu.FUENTES["fanduel"]._cuando = [], 0.0
conn.execute("DELETE FROM provider_event_map")
conn.commit()
ok(res_f("fanduel_nc", clave_luan).get("url") ==
   "https://sportsbook.fanduel.com/tennis/itf-men-luan/nino-ehrenschneider-v-ryuki-matsuda-36200001",
   "FanDuel: encuentra el ITF de Luan con su buscador interno (no estaba en la página SPORT)")
ok(cuerpos_fd and cuerpos_fd[0][0] == "scan.nc.sportsbook.fanduel.com" and cuerpos_fd[0][1] == "ak-de-prueba",
   "FanDuel: buscador del estado (scan.nc…) con su clave pública en x-application")
ok(len(cuerpos_fd) == 2 and cuerpos_fd[0][2].get("eventTypeIds") == [2]
   and cuerpos_fd[1][2].get("competitionIds") == [12834033],
   "FanDuel: primero pide todo el tenis; si no responde, por sus competiciones")
ok(any(e["en_juego"] for e in fu.FUENTES["fanduel"]._eventos), "FanDuel: sabe qué partidos están EN JUEGO")

# Hora de FullTenis muy distinta de la real (Bu vs Djokovic, 02/10/2026)
_p_bu = Partido("x", "Yunchaokete Bu", "Novak Djokovic", "2026-10-02T01:00:00+00:00", True)
_ev_bu = [{"id": 7, "j1": "Bu Yunchaokete", "j2": "Novak Djokovic", "inicio": "2026-10-02T10:30:00+00:00",
           "en_juego": True}]
ok(fu.emparejar(_p_bu, _ev_bu)[0] == ENCONTRADO,
   "un único partido de esos jugadores con 9 h de diferencia de hora: ENCONTRADO (antes AMBIGUO)")
_ev_dos = _ev_bu + [{"id": 8, "j1": "Novak Djokovic", "j2": "Yunchaokete Bu", "inicio": "2026-10-02T02:00:00+00:00"}]
est_dos, ev_dos, _ = fu.emparejar(_p_bu, _ev_dos)
ok(est_dos == ENCONTRADO and ev_dos["id"] == 8, "con DOS candidatos, la hora decide (elige el de la hora más cercana)")
ok(fu.emparejar(_p_bu, [dict(_ev_bu[0], inicio="2026-10-06T10:30:00+00:00")])[0] == NO_ENCONTRADO,
   "un partido de esos jugadores 4 días después NO es este")

# Estado del usuario: BetMGM y bet365 tienen una web por estado
r_nj = cli2.get("/api/resolver", params={"clave": clave_hr, "provider": "bet365_nc", "estado": "nj"}, headers=H).json()
ok(r_nj.get("respaldo") == "https://www.nj.bet365.com/#/IP/B13", "estado=nj: bet365 en www.nj.bet365.com")
r_fl = cli2.get("/api/resolver", params={"clave": clave_hr, "provider": "bet365_nc", "estado": "fl"}, headers=H).json()
ok(r_fl["estado"] == "NO_DISPONIBLE" and "FL" in r_fl.get("detalle", "") and not r_fl.get("respaldo"),
   "estado=fl: bet365 dice que no opera en Florida y no abre nada")
r_mal = cli2.get("/api/resolver", params={"clave": clave_hr, "provider": "bet365_nc", "estado": "zz"}, headers=H).json()
ok(r_mal.get("respaldo") == "https://www.nc.bet365.com/#/IP/B13", "estado desconocido: se ignora")
r_hr_fl = cli2.get("/api/resolver", params={"clave": clave_hr, "provider": "hardrock_fl", "estado": "nj"}, headers=H).json()
ok(r_hr_fl.get("url") == "https://app.hardrock.bet/competition/wtaBeijing/5750617385245737388",
   "Hard Rock: misma dirección en cualquier estado")
from buscador.app import _url_estado  # noqa: E402
ok(_url_estado("https://www.nc.betmgm.com/en/sports/events/a-b-1", "fl") == "https://www.fl.betmgm.com/en/sports/events/a-b-1",
   "BetMGM: la dirección pasa al estado del usuario")
ok({c["region"] for c in cli2.get("/api/catalogo", headers=H).json()["providers"]
    if c["id"] in ("hardrock_fl", "draftkings_nc", "bet365_nc")} == {"US"},
   "EE. UU. es una sola región (las bases antiguas US-NC/US-FL se migran)")

# UTR: categoría propia y partidos que solo tienen las casas
from buscador import categoria as categoria_m, cobertura as cobertura_m  # noqa: E402
ok(categoria_m.deducir("UTR Men Newport Beach USA") == "UTR"
   and categoria_m.deducir("UTR Women Lincoln USA") == "UTR", "categoría UTR (UTR Pro Tennis Tour)")
config.FANDUEL_AK = "ak-de-prueba"
fu.FUENTES["fanduel"]._eventos = [{"id": 36116695, "j1": "Marika Jones", "j2": "Gala Arangio",
                                   "inicio": _iso(-20), "torneo": "UTR Women Newport Beach USA",
                                   "en_juego": True, "slug": "marika-jones-v-gala-arangio",
                                   "comp_slug": "utr-women-newport-beach-usa"}]
fu.FUENTES["fanduel"]._cuando = _t.monotonic()
conn.execute("UPDATE provider_catalog SET metodo='fanduel', estado='TESTING', dominios='[\"fanduel.com\"]' "
             "WHERE id='fanduel_nc'")
conn.commit()
lista_utr = cli2.get("/api/partidos", params={"q": "arangio"}, headers=H).json()["partidos"]
ok(len(lista_utr) == 1 and lista_utr[0]["categoria"] == "UTR" and "desde fanduel" in lista_utr[0]["torneo"],
   "búsqueda: un partido UTR que solo tiene una casa aparece (categoría UTR, «desde fanduel»)")
r_utr = res_f("fanduel_nc", lista_utr[0]["clave"])
ok(r_utr["estado"] == "ENCONTRADO" and r_utr["url"].endswith("-36116695"),
   "ese partido se abre en la casa como cualquier otro")
ok(len(cli2.get("/api/partidos", params={"q": "arangio"}, headers=H).json()["partidos"]) == 1,
   "buscarlo otra vez no lo duplica")

# Cobertura (rehecha con datos reales): base = partidos de FullTenis que una casa marca EN JUEGO
for _m in fu.FUENTES:
    fu.FUENTES[_m]._eventos = []
sync.guardar_fixture(conn, {"fixture_id": "cob-1", "fecha": HOY, "jugador1": "Jiri Lehecka", "jugador2": "Zizou Bergs",
                            "torneo": "ATP Tokyo", "genero": "M"}, "fixtures")
sync.guardar_fixture(conn, {"fixture_id": "cob-2", "fecha": HOY, "jugador1": "Hubert Hurkacz",
                            "jugador2": "Alejandro Davidovich Fokina", "torneo": "ATP Tokyo", "genero": "M"}, "fixtures")
sync.guardar_fixture(conn, {"fixture_id": "cob-3", "fecha": _iso(-600), "jugador1": "Ya Termino", "jugador2": "Partido Viejo",
                            "torneo": "ITF", "genero": "M"}, "fixtures")
conn.commit()
fu.FUENTES["kambi"]._eventos = [  # en juego: Lehecka-Bergs y un UTR que FullTenis no tiene
    {"id": 1, "j1": "Jiri Lehecka", "j2": "Zizou Bergs", "inicio": HOY, "torneo": "Tokio", "en_juego": True},
    {"id": 2, "j1": "Marika Jones", "j2": "Gala Arangio", "inicio": HOY, "torneo": "UTR Women", "en_juego": True}]
fu.FUENTES["fanduel"]._eventos = [  # en juego Hurkacz-Davidovich; Hurkacz-Tien es OTRO partido (siguiente ronda)
    {"id": 3, "j1": "Hubert Hurkacz", "j2": "Alejandro Davidovich Fokina", "inicio": HOY, "torneo": "", "en_juego": True,
     "slug": "x", "comp_slug": "y"},
    {"id": 4, "j1": "Learner Tien", "j2": "Hubert Hurkacz", "inicio": HOY, "torneo": "", "en_juego": False,
     "slug": "x", "comp_slug": "y"}]
cob = cobertura_m.calcular(conn)
ok(cob["partidos"] == 2, f"cobertura: base = solo los partidos que una casa marca en juego (2, no el terminado): {cob['partidos']}")
ok(cob["por_casa"]["kambi"]["encontrados"] == 1 and cob["por_casa"]["kambi"]["pct"] == 50
   and cob["por_casa"]["fanduel"]["pct"] == 50, "cobertura: cada casa encuentra 1 de 2 (50 %)")
ok(cob["por_casa"]["kambi"]["sin_emparejar"] == 1 and "Arangio" in cob["por_casa"]["kambi"]["ejemplos_sin_emparejar"][0],
   "cobertura: el partido UTR en juego que FullTenis no tiene sale en «sin emparejar»")
ok(cob["por_casa"]["fanduel"]["sin_emparejar"] == 0,
   "cobertura: la siguiente ronda del mismo jugador ya NO cuenta como fallo")
ok("cobertura" in cli2.get("/salud").json(), "/salud incluye la cobertura")
for _m in fu.FUENTES:
    fu.FUENTES[_m]._eventos = []

# Casas OCULTAS: fuera de la pestaña, de "Mis casas" y sin leer su web
cli2.put("/api/mis-casas", json={"providers": ["betplay_co", "bet365_nc", "caesars_nc"]}, headers=H)
config.CASAS_OCULTAS = {"bet365_nc", "caesars_nc", "betano_co"}
ids_cat = {c["id"] for c in cli2.get("/api/catalogo", headers=H).json()["providers"]}
ok(not ({"bet365_nc", "caesars_nc", "betano_co"} & ids_cat) and "betplay_co" in ids_cat,
   "ocultas: bet365, Caesars y Betano no salen en la pestaña")
ok([c["id"] for c in cli2.get("/api/mis-casas", headers=H).json()["providers"]] == ["betplay_co"],
   "ocultas: desaparecen de «Mis casas» de quien ya las tenía guardadas")
ok(cli2.put("/api/mis-casas", json={"providers": ["caesars_nc"]}, headers=H).status_code == 400,
   "ocultas: no se pueden volver a elegir")
ok(res_f("bet365_nc", clave_hr)["estado"] == "NO_DISPONIBLE", "ocultas: el resolver las da por no disponibles")
ok(not fu.FUENTES["caesars"].configurada() and not fu.FUENTES["betano"].configurada()
   and fu.FUENTES["kambi"].configurada(), "ocultas: el BOT deja de leer Caesars y Betano (Kambi sigue)")
config.CASAS_OCULTAS = set()
ok("betano_co" in {c["id"] for c in cli2.get("/api/catalogo", headers=H).json()["providers"]},
   "quitar una casa de CASAS_OCULTAS la recupera")
os.environ.pop("CASAS_OCULTAS", None)
import importlib as _il  # noqa: E402
_cfg = _il.reload(__import__("buscador.config", fromlist=["x"]))
ok(_cfg.CASAS_OCULTAS == {"bet365_nc", "caesars_nc"},
   "por defecto (sin variable) quedan ocultas bet365 y Caesars; Betano se queda")
_cfg.CASAS_OCULTAS = set()

# CORS: diagnóstico del origen rechazado
import logging as _lg  # noqa: E402
_capt = []


class _Capt(_lg.Handler):
    def emit(self, rec):
        _capt.append(rec.getMessage())


_lg.getLogger("buscador").addHandler(_Capt())
r_cors = cli2.options("/api/catalogo", headers={"Origin": "https://otro-dominio.example",
                                               "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "authorization"})
ok(r_cors.status_code == 400 and any("https://otro-dominio.example" in m and "RECHAZADA" in m for m in _capt),
   "CORS: el origen no permitido se rechaza y el log dice la dirección exacta")
r_bien = cli2.options("/api/catalogo", headers={"Origin": config.ALLOWED_ORIGINS[0],
                                               "Access-Control-Request-Method": "GET",
                                               "Access-Control-Request-Headers": "authorization"})
ok(r_bien.status_code == 200, "CORS: el origen permitido pasa (con Authorization)")
ok(cli2.get("/salud").json().get("cors_permitidos") == config.ALLOWED_ORIGINS,
   "/salud muestra las direcciones permitidas (ALLOWED_ORIGINS)")

sal = cli2.get("/salud").json()
ok(set(sal.get("fuentes", {})) >= {"kambi", "fanduel", "draftkings", "caesars"}, "/salud muestra el estado de cada fuente")

print("\n20. Emparejamiento mejorado (08/10/2026: «que siempre encuentre los partidos»)")
from buscador.providers import fuentes as _fu2  # noqa: E402
_hoy_iso = __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()
ok(claves.apellidos("Carlos Alcaraz Garfia") == {"alcaraz", "garfia"}, "nombre + dos apellidos: los dos cuentan")
ok("potro" in claves.apellidos("Juan Martin del Potro") and "del" not in claves.apellidos("Juan Martin del Potro"), "partículas ('del') no cuentan")
ok(claves.apellidos("Zhizhen Zhang") == {"zhang"} and claves.apellidos("Zhang Z.") == {"zhang"}, "orden asiático en los dos formatos")
ok(claves.parecidos("schwartzman", "schwarzman") and claves.parecidos("kecmanovic", "kecmanovich")
   and not claves.parecidos("lee", "lei") and not claves.parecidos("perez", "pedro"), "grafías cercanas sí; cortas o distintas no")
_evs = [{"id": "1", "j1": "C. Alcaraz", "j2": "J. Sinner", "inicio": _hoy_iso, "en_juego": True},
        {"id": "2", "j1": "Diego Schwarzman", "j2": "F. Cerundolo", "inicio": _hoy_iso, "en_juego": True},
        {"id": "3", "j1": "Zhang Zhizhen", "j2": "Y. Bu", "inicio": _hoy_iso, "en_juego": False}]
ok(_fu2.emparejar(Partido("a", "Carlos Alcaraz Garfia", "Jannik Sinner", _hoy_iso, True), _evs)[1]["id"] == "1",
   "Alcaraz Garfia ↔ 'C. Alcaraz': ahora casa")
ok(_fu2.emparejar(Partido("b", "Schwartzman D.", "Cerundolo F.", _hoy_iso, True), _evs)[1]["id"] == "2",
   "Schwartzman ↔ Schwarzman: casa por parecido")
ok(_fu2.emparejar(Partido("c", "Zhizhen Zhang", "Yunchaokete Bu", _hoy_iso, True), _evs)[1]["id"] == "3",
   "Zhang Zhizhen ↔ Zhizhen Zhang")
ok(_fu2.emparejar(Partido("d", "Novak Djokovic", "Jannik Sinner", _hoy_iso, True), _evs)[0] == NO_ENCONTRADO,
   "los dos apellidos siguen siendo obligatorios")
# Casa solo EN VIVO y partido que todavía no empezó → SoloEnVivo (NO_ENCONTRADO con motivo, sin respaldo)
_manana = (__import__('datetime').datetime.now(__import__('datetime').timezone.utc) + __import__('datetime').timedelta(hours=6)).isoformat()
_kambi = _fu2.FUENTES["kambi"]
_kambi._eventos, _kambi._cuando = [], __import__('time').monotonic()
try:
    asyncio.run(_kambi.resolver_directo(None, Partido("e", "Novak Djokovic", "Jannik Sinner", _manana, True), "betplay_co"))
    ok(False, "casa solo en vivo + partido futuro: debe avisar")
except _fu2.SoloEnVivo as e:
    ok("solo partidos en juego" in str(e), "casa solo en vivo + partido futuro: avisa 'publica solo partidos en juego'")
_ya = (__import__('datetime').datetime.now(__import__('datetime').timezone.utc) - __import__('datetime').timedelta(minutes=30)).isoformat()
ok(asyncio.run(_kambi.resolver_directo(None, Partido("f", "Novak Djokovic", "Jannik Sinner", _ya, True), "betplay_co"))[0] == NO_ENCONTRADO,
   "casa solo en vivo + partido ya empezado y no está: NO_ENCONTRADO normal")
ok(_fu2.FUENTES["fanduel"].SOLO_EN_VIVO is False and _fu2.FUENTES["kambi"].SOLO_EN_VIVO is True, "FanDuel publica próximos; Kambi solo en vivo")

print()
print("TODO BIEN" if not fallos else f"{fallos} FALLO(S)")
sys.exit(1 if fallos else 0)
