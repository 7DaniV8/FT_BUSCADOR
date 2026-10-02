"""
buscador/app.py — API de BOT_BUSCADOR.

La consume el navegador del usuario desde la pestaña 🔎 BOT BUSCADOR de
FullTenis (CORS solo para ALLOWED_ORIGINS). RankingFTR no la llama nunca.

Rutas
  GET  /salud                          sin token: vivo, modo de prueba y última sincronización
  GET  /api/partidos?q=Damm            busca en la caché propia (nunca en FullTenis)
  GET  /api/catalogo?region=CO         casas visibles para una región
  GET  /api/mis-casas                  casas marcadas por el usuario del token
  PUT  /api/mis-casas                  {"providers": [...]} (solo ACTIVE/TESTING)
  GET  /api/resolver?clave=..&provider=..   UNA casa: estado + URL pública
  GET  /api/matriz?region=CO           matriz de validación calculada
  POST /api/validaciones               registrar una prueba (solo rol admin)

Aislamiento
  * Cada casa se resuelve en su propia petición y con su propio tiempo
    máximo: una casa lenta o caída no retrasa ni rompe a las demás.
  * Nunca se devuelve una URL fuera de los dominios de esa casa.
  * Nada de sesiones, cookies, login, mercados, cuotas ni betslip. De
    OddsPapi solo se usa el enlace del partido (fixturePath).
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import catalogo, config, db, providers, sync, validacion
from .claves import apellidos, normalizar
from .resolver import AMBIGUO, ENCONTRADO, NO_ENCONTRADO, Partido, elegir
from . import categoria as categoria_mod
from . import cobertura as cobertura_mod
from .claves import clave_partido
from .providers import fuentes as fuentes_mod
from .providers.oddspapi import SinAccesoEnVivo
from .token import TokenInvalido, verificar

log = logging.getLogger("buscador")

# Estados de resultado que ve el usuario, además de los del resolver.
LOGIN_REQUERIDO = "LOGIN_REQUERIDO"
UBICACION_REQUERIDA = "UBICACION_REQUERIDA"
ERROR = "ERROR"
PENDIENTE = "PROVIDER_PENDING"
NO_DISPONIBLE = "NO_DISPONIBLE"
REUSO_MAPEO_H = 6


def _conn():
    return db.conectar()


@asynccontextmanager
async def ciclo(app: FastAPI):
    conn = _conn()
    try:
        db.inicializar(conn)
        catalogo.sembrar(conn)
    finally:
        conn.close()
    tareas = []
    if config.SYNC_ACTIVO:
        tareas.append(asyncio.create_task(sync.bucle(_conn)))
        tareas.append(asyncio.create_task(fuentes_mod.bucle()))
        tareas.append(asyncio.create_task(cobertura_mod.bucle(_conn)))
        if config.ODDSPAPI_API_KEY:
            tareas.append(asyncio.create_task(providers.ODDSPAPI.bucle(_conn)))
            if config.ODDSPAPI_BARRIDO_HORAS:
                tareas.append(asyncio.create_task(providers.ODDSPAPI.bucle_barrido(_conn)))
            if config.ODDSPAPI_PRECARGA_MIN:
                tareas.append(asyncio.create_task(providers.ODDSPAPI.bucle_precarga(_conn)))
    if config.MODO_PRUEBA:
        log.warning(f"MODO_PRUEBA ACTIVO: {sorted(config.MODO_PRUEBA)} -- solo para staging")
    yield
    for t in tareas:
        t.cancel()


app = FastAPI(title="BOT_BUSCADOR", lifespan=ciclo)
app.add_middleware(CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS,
                   allow_methods=["GET", "PUT", "POST"],
                   allow_headers=["Authorization", "Content-Type"],
                   allow_credentials=False, max_age=600)


@app.middleware("http")
async def _avisar_origen_rechazado(request: Request, call_next):
    """Diagnóstico: si el navegador llama desde una web que NO está en
    ALLOWED_ORIGINS, se escribe en el log la dirección exacta (es pública) para
    poder copiarla. No cambia la respuesta: CORS la sigue rechazando."""
    origen = request.headers.get("origin", "")
    if origen and origen.rstrip("/") not in config.ALLOWED_ORIGINS:
        log.warning(f"[cors] petición RECHAZADA desde {origen!r}: no está en ALLOWED_ORIGINS "
                    f"{config.ALLOWED_ORIGINS!r}. Añade esa dirección exacta a la variable.")
    return await call_next(request)


@app.middleware("http")
async def modo_prueba(request: Request, call_next):
    """Simulación de fallos para las pruebas de aislamiento en staging."""
    if request.url.path.startswith("/api/") and request.method != "OPTIONS":
        if "lento" in config.MODO_PRUEBA:
            await asyncio.sleep(20)
        if "error500" in config.MODO_PRUEBA:
            return JSONResponse(status_code=500, content={"detail": "MODO_PRUEBA error500"})
    return await call_next(request)


def usuario(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Falta el token de FullTenis")
    try:
        return verificar(authorization[7:].strip(), config.BUSCADOR_TOKEN_SECRET,
                         config.TOKEN_AUDIENCIA)
    except TokenInvalido as e:
        raise HTTPException(401, f"Token no válido ({e})")


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@app.get("/salud")
def salud():
    conn = _conn()
    try:
        est = {f["clave"]: f["valor"] for f in conn.execute("SELECT * FROM sync_estado")}
        n = conn.execute("SELECT COUNT(*) FROM fixtures_cache").fetchone()[0]
        n_op = conn.execute("SELECT COUNT(*) FROM oddspapi_fixtures").fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "modo_prueba": sorted(config.MODO_PRUEBA),
            "cors_permitidos": config.ALLOWED_ORIGINS,
            "fixtures_en_cache": n, "sync": est,
            "oddspapi": {"configurado": bool(config.ODDSPAPI_API_KEY), "partidos": n_op,
                         "precarga_min": config.ODDSPAPI_PRECARGA_MIN,
                         "precarga": est.get("oddspapi_precarga", ""),
                         "barrido_horas": config.ODDSPAPI_BARRIDO_HORAS,
                         "barrido": est.get("oddspapi_barrido", "")},
            "fuentes": {m: {"configurada": f.configurada(), **f.estado()}
                        for m, f in fuentes_mod.FUENTES.items()},
            "proxies": fuentes_mod.PROXY_DIAG,
            "cobertura": cobertura_mod.COBERTURA}


@app.get("/api/partidos")
def partidos(q: str = Query("", max_length=80), limite: int = Query(20, ge=1, le=50),
             u: dict = Depends(usuario)):
    palabras = [p for p in normalizar(q).split() if len(p) > 1]
    if not palabras:
        return {"partidos": []}
    conn = _conn()
    try:
        filas = conn.execute(
            "SELECT * FROM fixtures_cache ORDER BY fecha LIMIT 5000").fetchall()
    finally:
        conn.close()
    salida, vistos = [], []

    def _mismo(n1: str, n2: str) -> bool:
        """El mismo jugador escrito de dos formas ("Jiri Lehecka" / "Lehecka")."""
        t1 = {x for x in normalizar(n1).split() if len(x) > 1}
        t2 = {x for x in normalizar(n2).split() if len(x) > 1}
        return bool((apellidos(n1) & t2) or (apellidos(n2) & t1))

    def _duplicado(f) -> bool:
        """El mismo partido ya listado: mismos dos jugadores (por apellidos, en
        cualquier orden) y menos de 12 h de diferencia; si una de las dos fechas
        no trae hora, basta con los jugadores."""
        a, b = f["jugador1"], f["jugador2"]
        fecha = str(f["fecha"] or "")
        try:
            t = datetime.fromisoformat(fecha.replace("Z", "+00:00")[:19]) if len(fecha) > 10 else None
        except ValueError:
            t = None
        for (x, y), t_v in vistos:
            mismo_par = (_mismo(a, x) and _mismo(b, y)) or (_mismo(a, y) and _mismo(b, x))
            if mismo_par and (t is None or t_v is None or abs((t - t_v).total_seconds()) <= 12 * 3600):
                return True
        vistos.append(((a, b), t))
        return False

    for f in filas:
        if "/" in f"{f['jugador1']}{f['jugador2']}":
            continue                      # dobles: ninguna fuente da su enlace
        texto = normalizar(f"{f['jugador1']} {f['jugador2']} {f['torneo']}")
        if all(p in texto for p in palabras) and not _duplicado(f):
            salida.append({"clave": f["clave"], "jugador1": f["jugador1"],
                           "jugador2": f["jugador2"], "torneo": f["torneo"],
                           "categoria": f["categoria"], "fecha": f["fecha"],
                           "hora_conocida": bool(f["hora_conocida"])})
            if len(salida) >= limite:
                break
    # Partidos que tienen las CASAS y FullTenis no (UTR, ITF que falten...). Se
    # guardan como partido "casas" para poder resolverlos igual que los demás.
    if len(salida) < limite:
        extra = []
        for metodo, f_ in fuentes_mod.FUENTES.items():
            for ev in list(f_._eventos):
                if len(salida) + len(extra) >= limite:
                    break
                j1, j2 = str(ev.get("j1") or ""), str(ev.get("j2") or "")
                if not (j1 and j2) or "/" in j1 + j2:
                    continue
                torneo = str(ev.get("torneo") or "")
                if not all(p in normalizar(f"{j1} {j2} {torneo}") for p in palabras):
                    continue
                inicio = str(ev.get("inicio") or "")
                if _duplicado({"jugador1": j1, "jugador2": j2, "fecha": inicio}):
                    continue
                fecha = inicio if len(inicio) >= 10 else datetime.now(timezone.utc).date().isoformat()
                fid = f"casa:{metodo}:{ev.get('id')}"
                extra.append({"fixture_id": fid, "fecha": fecha, "jugador1": j1, "jugador2": j2,
                              "torneo": torneo, "genero": "", "_casa": f_.nombre})
        if extra:
            conn = _conn()
            try:
                for x in extra:
                    sync.guardar_fixture(conn, x, "casas")
                conn.commit()
            finally:
                conn.close()
            for x in extra:
                salida.append({"clave": clave_partido(x["fixture_id"], x["fecha"], x["jugador1"], x["jugador2"]),
                               "jugador1": x["jugador1"], "jugador2": x["jugador2"],
                               "torneo": (x["torneo"] + " · " if x["torneo"] else "") + f"desde {x['_casa']}",
                               "categoria": categoria_mod.deducir(x["torneo"], ""),
                               "fecha": x["fecha"], "hora_conocida": len(x["fecha"]) > 10})
    return {"partidos": salida}


@app.get("/api/catalogo")
def ver_catalogo(region: str = "", u: dict = Depends(usuario)):
    conn = _conn()
    try:
        return {"providers": catalogo.listar(conn, region or None)}
    finally:
        conn.close()


@app.get("/api/mis-casas")
def mis_casas(u: dict = Depends(usuario)):
    conn = _conn()
    try:
        filas = conn.execute(
            "SELECT p.id, p.nombre, p.region, p.estado FROM user_providers up "
            "JOIN provider_catalog p ON p.id = up.provider_id "
            "WHERE up.usuario_id = ? AND up.habilitado = 1 ORDER BY p.nombre",
            (str(u["sub"]),)).fetchall()
        # Las casas ocultas o que dejaron de estar disponibles desaparecen solas.
        return {"providers": [dict(f) for f in filas
                              if f["id"] not in config.CASAS_OCULTAS
                              and f["estado"] in catalogo.SELECCIONABLES]}
    finally:
        conn.close()


@app.put("/api/mis-casas")
def guardar_mis_casas(datos: dict = Body(...), u: dict = Depends(usuario)):
    ids = datos.get("providers")
    if not isinstance(ids, list) or len(ids) > 60:
        raise HTTPException(400, "providers debe ser una lista")
    ids = list(dict.fromkeys(str(x) for x in ids))      # sin repetidos
    conn = _conn()
    try:
        for pid in ids:
            p = catalogo.obtener(conn, str(pid))
            if not p or p["estado"] not in catalogo.SELECCIONABLES:
                raise HTTPException(400, f"'{pid}' no está disponible todavía")
        uid = str(u["sub"])
        conn.execute("DELETE FROM user_providers WHERE usuario_id = ?", (uid,))
        conn.executemany(
            "INSERT INTO user_providers (usuario_id, provider_id, habilitado, actualizado_en) "
            "VALUES (?,?,1,?)", [(uid, str(pid), _ahora()) for pid in ids])
        conn.commit()
        return {"ok": True, "providers": ids}
    finally:
        conn.close()


def _url_permitida(url: str, dominios: list[str]) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    host = (p.hostname or "").lower()
    return p.scheme == "https" and any(host == d or host.endswith("." + d) for d in dominios)


# Estados de EE. UU. (y DC) admitidos en el parámetro `estado`.
ESTADOS_US = {"al", "ak", "az", "ar", "ca", "co", "ct", "de", "dc", "fl", "ga", "hi", "id", "il", "in",
              "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh",
              "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut",
              "vt", "va", "wa", "wv", "wi", "wy"}
_HOST_POR_ESTADO = __import__("re").compile(r"^https://www\.[a-z]{2}\.(betmgm|bet365)\.com/")


def _url_estado(url: str | None, estado: str | None) -> str | None:
    """BetMGM y bet365 tienen una web por estado (www.nc.betmgm.com, www.il.bet365.com…):
    se cambia el estado de la dirección por el del usuario. El resto no cambia."""
    if not url or not estado:
        return url
    return _HOST_POR_ESTADO.sub(lambda m: f"https://www.{estado}.{m.group(1)}.com/", url)


@app.get("/api/resolver")
async def resolver(clave: str = Query(..., max_length=40), provider: str = Query(..., max_length=40),
                   estado: str | None = Query(None, max_length=2), u: dict = Depends(usuario)):
    """UNA casa. Si no hay enlace directo al partido (no encontrado, dudoso o
    error de la fuente), añade `respaldo`: la sección de tenis de esa casa,
    solo si pertenece a sus dominios. Nunca en casas pendientes/no disponibles."""
    r = await _resolver(clave, provider)
    if r.get("estado") in (NO_ENCONTRADO, AMBIGUO, ERROR) and not r.get("url"):
        conn = _conn()
        try:
            prov = catalogo.obtener(conn, provider)
        finally:
            conn.close()
        destino = catalogo.RESPALDO.get(provider)
        if prov and destino and _url_permitida(destino, prov["dominios"]):
            r["respaldo"] = destino
    est = (estado or "").lower()
    operan = catalogo.ESTADOS_CASA.get(provider)
    if est in ESTADOS_US and operan is not None and est not in operan:
        # La casa no opera en el estado del usuario: decirlo, sin abrir nada.
        return {"provider": r.get("provider", provider), "nombre": r.get("nombre", provider),
                "estado": NO_DISPONIBLE, "detalle": f"no opera en {est.upper()}"}
    if est in ESTADOS_US:
        for k in ("url", "respaldo"):
            if r.get(k):
                r[k] = _url_estado(r[k], est)
    return r


async def _resolver(clave: str, provider: str):
    conn = _conn()
    try:
        prov = catalogo.obtener(conn, provider)
        fila = conn.execute("SELECT * FROM fixtures_cache WHERE clave = ?", (clave,)).fetchone()
        if not prov:
            raise HTTPException(404, "provider desconocido")
        if not fila:
            raise HTTPException(404, "partido no está en la caché")
        base = {"provider": prov["id"], "nombre": prov["nombre"]}
        if prov["estado"] in (catalogo.PROVIDER_PENDING, catalogo.COMING_SOON):
            return {**base, "estado": PENDIENTE, "detalle": prov["estado"]}
        if prov["estado"] in (catalogo.NOT_AVAILABLE_REGION, catalogo.MAINTENANCE,
                              catalogo.DISABLED):
            return {**base, "estado": NO_DISPONIBLE, "detalle": prov["estado"]}
        if prov["id"] in config.casa_que_falla() or \
                (prov["metodo"] == "opticodds" and "opticodds_caido" in config.MODO_PRUEBA) or \
                (prov["metodo"] == "oddspapi" and "oddspapi_caido" in config.MODO_PRUEBA):
            return {**base, "estado": ERROR, "detalle": "MODO_PRUEBA"}
        if prov["metodo"] == "opticodds" and not config.OPTICODDS_API_KEY:
            return {**base, "estado": PENDIENTE, "detalle": "sin OpticOdds"}
        if prov["metodo"] == "oddspapi" and not config.ODDSPAPI_API_KEY:
            return {**base, "estado": PENDIENTE, "detalle": "sin OddsPapi"}
        if prov["metodo"] == "respaldo":
            # Casa sin lectura posible (p. ej. bet365): siempre su sección de tenis.
            return {**base, "estado": NO_ENCONTRADO, "detalle": "solo sección de tenis"}
        f_ = fuentes_mod.FUENTES.get(prov["metodo"])
        if f_ is not None and not f_.configurada():
            return {**base, "estado": PENDIENTE, "detalle": f"falta configurar {f_.nombre}"}
        if f"fuente_caida:{prov['metodo']}" in config.MODO_PRUEBA:
            return {**base, "estado": ERROR, "detalle": "MODO_PRUEBA"}

        aviso = validacion.aviso_apertura(validacion.matriz_provider(conn, prov["id"]))
        prev = conn.execute("SELECT * FROM provider_event_map WHERE clave=? AND provider_id=?",
                            (clave, prov["id"])).fetchone()
        limite = (datetime.now(timezone.utc) - timedelta(hours=REUSO_MAPEO_H)).isoformat()
        if prev and prev["estado"] == ENCONTRADO and prev["found_at"] >= limite \
                and _url_permitida(prev["external_url"], prov["dominios"]):
            return {**base, "estado": aviso or ENCONTRADO, "url": prev["external_url"],
                    "confianza": prev["confianza"], "cache": True}

        partido = Partido(clave=clave, jugador1=fila["jugador1"], jugador2=fila["jugador2"],
                          fecha=fila["fecha"], hora_conocida=bool(fila["hora_conocida"]),
                          torneo=fila["torneo"] or "", categoria=fila["categoria"] or "")
        fuente = providers.obtener(prov["metodo"])
        try:
            if hasattr(fuente, "resolver_directo"):
                estado, url, conf, id_ext = await asyncio.wait_for(
                    fuente.resolver_directo(conn, partido, prov["id"]),
                    timeout=config.TIMEOUT_PROVIDER_S)
            else:
                cands = await asyncio.wait_for(fuente.candidatos(partido),
                                               timeout=config.TIMEOUT_PROVIDER_S)
                estado, elegido, conf = elegir(partido, cands)
                url = elegido.url if elegido else None
                id_ext = elegido.id_externo if elegido else None
        except asyncio.TimeoutError:
            return {**base, "estado": ERROR, "detalle": "tiempo agotado"}
        except SinAccesoEnVivo:
            return {**base, "estado": ERROR, "detalle": "partido en juego sin enlace guardado"}
        except Exception as e:
            log.warning(f"[{prov['id']}] {type(e).__name__}: {e}")
            return {**base, "estado": ERROR, "detalle": "fuente no disponible"}

        if url and not _url_permitida(url, prov["dominios"]):
            log.warning(f"[{prov['id']}] URL fuera de sus dominios descartada: {url}")
            return {**base, "estado": ERROR, "detalle": "URL fuera de dominio"}
        conn.execute(
            "INSERT OR REPLACE INTO provider_event_map (clave, provider_id, estado, "
            "external_event_id, external_url, confianza, found_at) VALUES (?,?,?,?,?,?,?)",
            (clave, prov["id"], estado, id_ext, url, conf, _ahora()))
        conn.commit()
        if estado == ENCONTRADO:
            return {**base, "estado": aviso or ENCONTRADO, "url": url, "confianza": conf}
        if estado == AMBIGUO:
            return {**base, "estado": AMBIGUO, "confianza": conf}
        return {**base, "estado": NO_ENCONTRADO}
    finally:
        conn.close()


@app.get("/api/matriz")
def matriz(region: str = "", u: dict = Depends(usuario)):
    conn = _conn()
    try:
        return {"providers": [{**p, "matriz": validacion.matriz_provider(conn, p["id"])}
                              for p in catalogo.listar(conn, region or None)]}
    finally:
        conn.close()


@app.post("/api/validaciones")
def nueva_validacion(datos: dict = Body(...), u: dict = Depends(usuario)):
    if u.get("rol") != "admin":
        raise HTTPException(403, "Solo admin registra pruebas")
    conn = _conn()
    try:
        if not catalogo.obtener(conn, str(datos.get("provider_id", ""))):
            raise HTTPException(400, "provider desconocido")
        try:
            vid = validacion.registrar(
                conn, str(datos["provider_id"]), str(datos.get("columna", "")),
                str(datos.get("resultado", "")), datos.get("clave"), datos.get("url"),
                probador=str(u.get("usuario", "")), region_prueba=str(datos.get("region", "")),
                navegador_limpio=bool(datos.get("navegador_limpio", True)),
                detalle=str(datos.get("detalle", ""))[:500])
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e))
        return {"ok": True, "id": vid}
    finally:
        conn.close()
