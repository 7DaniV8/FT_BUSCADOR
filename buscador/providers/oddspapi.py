"""
providers/oddspapi.py — Enlace de cada casa al partido, vía OddsPapi.

SOLO ENLACES. De la respuesta de OddsPapi se usa únicamente `fixturePath` de
cada casa (la página del partido). Cuotas, mercados y `betslip` se descartan
sin leerlos: el buscador no apuesta ni toca el boleto.

Flujo
  1. Cada ODDSPAPI_SYNC_MINUTOS: GET /fixtures (tenis, hoy + N días), 1 petición.
     Se guardan en oddspapi_fixtures. Fuera: partidos simulados (SRL), dobles
     y cancelados.
  2. Al resolver una casa para un partido de FullTenis:
       a) se empareja con un partido de OddsPapi: los DOS jugadores, cada uno
          en su lado, y el mismo día (±1 por husos horarios);
       b) si ese partido aún no tiene enlaces guardados, 1 petición a
          /odds?fixtureId=...&bookmakers=<casas del catálogo>, y se guarda el
          fixturePath de cada casa. Un candado por partido garantiza UNA sola
          petición aunque el navegador pida varias casas a la vez;
       c) el enlace se lee de la base. Una vez guardado sirve también cuando
          el partido ya está en juego (el plan gratuito no da partidos en vivo).
  3. Nunca se devuelve una URL fuera de los dominios de la casa (lo comprueba
     app.py con el catálogo).
  4. BARRIDO POR TORNEOS (ODDSPAPI_BARRIDO_HORAS > 0): el flujo real empieza
     con un MTO, así que el partido SIEMPRE está en juego cuando se busca, y el
     plan gratuito no da enlaces en juego. Cada N horas, /odds-by-tournaments
     trae los enlaces de todos los partidos de 5 torneos por petición y casa,
     y quedan guardados antes de que empiecen. Es la vía principal.
  5. PRECARGA partido a partido (ODDSPAPI_PRECARGA_MIN > 0): complemento para
     los partidos que el barrido no cubrió; 1 petición por partido.

La clave de la API va en la URL (así lo pide OddsPapi): nunca se registra en
los logs; los errores de red se reducen a su tipo.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone

import httpx

from .. import config
from ..claves import apellidos, dia, normalizar, tiene_hora
from ..resolver import AMBIGUO, ENCONTRADO, NO_ENCONTRADO, Partido
from .base import Provider, ProviderError

log = logging.getLogger("buscador.oddspapi")
# httpx registra cada URL a nivel INFO, y la clave de OddsPapi va en la URL:
# así nunca llega a los logs de Railway.
logging.getLogger("httpx").setLevel(logging.WARNING)

TENIS = 12
CABECERAS = {"User-Agent": "Mozilla/5.0 (compatible; FullTenis-BOT_BUSCADOR/1.0)",
             "Accept": "application/json"}

# provider_id del catálogo -> clave de la casa en OddsPapi.
CASAS = {
    "betplay_co": "betplay",
    "rushbet_co": "rushbet.co",
    "draftkings_nc": "draftkings",
    "fanduel_nc": "fanduel",
    "betmgm_nc": "betmgm",
    "kalshi": "kalshi",
    "polymarket": "polymarket",
}

UMBRAL_ENCONTRADO = 0.80
EMPATE = 0.10
DIAS_RETENCION = 2
_BETMGM = re.compile(r"^https://sports\.(?:[a-z]{2}|\{state\})\.betmgm\.com", re.I)
# OddsPapi da https://kalshi.com/markets/<serie>/e#<evento>: el evento va tras '#'
# y Kalshi solo enseña la serie. La página del partido es
# /markets/<SERIE>/<relleno>/<EVENTO> (p. ej. /markets/KXATPMATCH/x/KXATPMATCH-26AUG30TIRMAN).
_KALSHI = re.compile(r"^https://kalshi\.com/markets/([a-z0-9]+)/[^/#?]*#([a-z0-9-]+)$", re.I)


class SinAccesoEnVivo(ProviderError):
    """OddsPapi no da enlaces de un partido ya en juego con este plan."""


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _estado(conn, clave, valor):
    conn.execute("INSERT OR REPLACE INTO sync_estado (clave, valor) VALUES (?,?)",
                 (clave, str(valor)))


def ajustar_url(provider_id: str, url: str) -> str:
    """Correcciones de formato conocidas.
    BetMGM: el estado de EE. UU. del dominio (nj, {state}...) pasa a ODDSPAPI_ESTADO_US.
    Kalshi: el evento pasa de detrás de '#' a la ruta de la página del partido."""
    if provider_id == "betmgm_nc":
        url = _BETMGM.sub(f"https://sports.{config.ODDSPAPI_ESTADO_US}.betmgm.com", url)
    if provider_id == "kalshi":
        m = _KALSHI.match(url)
        if m:
            url = f"https://kalshi.com/markets/{m.group(1).upper()}/x/{m.group(2).upper()}"
    return url.replace("{state}", config.ODDSPAPI_ESTADO_US)


def _tokens(nombre: str) -> set[str]:
    return {t for t in normalizar(nombre).split() if len(t) > 1 and t != "srl"}


def _es_valido(f: dict) -> bool:
    cat = str(f.get("categorySlug") or "")
    n1, n2 = str(f.get("participant1Name") or ""), str(f.get("participant2Name") or "")
    if "simulated" in cat or "(srl)" in f"{n1} {n2}".lower():
        return False                       # partidos virtuales con nombres reales
    if "/" in n1 or "/" in n2:
        return False                       # dobles
    if str(f.get("statusName") or "") in ("Cancelled", "Canceled"):
        return False
    return bool(n1 and n2 and f.get("fixtureId") and f.get("startTime"))


def guardar_fixtures(conn: sqlite3.Connection, lista: list) -> int:
    n = 0
    ahora = _iso(_ahora())
    for f in lista or []:
        if not isinstance(f, dict) or not _es_valido(f):
            continue
        inicio = str(f["startTime"])
        conn.execute(
            "INSERT OR REPLACE INTO oddspapi_fixtures (fixture_id, dia, inicio, jugador1, "
            "jugador2, torneo, categoria, tiene_cuotas, actualizado_en, torneo_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (str(f["fixtureId"]), inicio[:10], inicio, str(f["participant1Name"]),
             str(f["participant2Name"]), str(f.get("tournamentName") or ""),
             str(f.get("categorySlug") or ""), 1 if f.get("hasOdds") else 0, ahora,
             str(f.get("tournamentId") or "")))
        n += 1
    limite = (_ahora() - timedelta(days=DIAS_RETENCION)).date().isoformat()
    viejos = [r[0] for r in conn.execute(
        "SELECT fixture_id FROM oddspapi_fixtures WHERE dia < ?", (limite,))]
    for fid in viejos:
        for tabla in ("oddspapi_fixtures", "oddspapi_enlaces", "oddspapi_consultas"):
            conn.execute(f"DELETE FROM {tabla} WHERE fixture_id = ?", (fid,))
    return n


def emparejar(conn: sqlite3.Connection, p: Partido) -> tuple[str, list[str], float]:
    """(estado, fixture_ids ordenados por preferencia, confianza).

    Los dos jugadores obligatorios y cada uno en su lado (así un dobles o un
    partido de uno solo de ellos nunca cuenta). Mismo día: 0.95; ±1 día: 0.85.
    Un mismo partido puede venir repetido con dos ids (fuentes distintas): se
    agrupan y se prueban en orden. Dos partidos DISTINTOS casi empatados:
    AMBIGUO."""
    a1, a2 = apellidos(p.jugador1), apellidos(p.jugador2)
    if not a1 or not a2:
        return NO_ENCONTRADO, [], 0.0
    try:
        d0 = datetime.fromisoformat(dia(p.fecha)).date()
    except ValueError:
        return NO_ENCONTRADO, [], 0.0
    desde, hasta = (d0 - timedelta(days=1)).isoformat(), (d0 + timedelta(days=1)).isoformat()
    grupos: dict[tuple, dict] = {}
    for f in conn.execute("SELECT * FROM oddspapi_fixtures WHERE dia BETWEEN ? AND ?",
                          (desde, hasta)):
        t1, t2 = _tokens(f["jugador1"]), _tokens(f["jugador2"])
        if not ((a1 & t1 and a2 & t2) or (a1 & t2 and a2 & t1)):
            continue
        conf = 0.95 if f["dia"] == d0.isoformat() else 0.85
        if tiene_hora(p.fecha):
            try:
                fp = datetime.fromisoformat(p.fecha.replace("Z", "+00:00"))
                fo = datetime.fromisoformat(f["inicio"].replace("Z", "+00:00"))
                if fp.tzinfo and abs((fo - fp).total_seconds()) > 6 * 3600:
                    conf -= 0.2
            except ValueError:
                pass
        clave = (tuple(sorted([" ".join(sorted(t1)), " ".join(sorted(t2))])), f["dia"])
        g = grupos.setdefault(clave, {"conf": 0.0, "ids": []})
        g["conf"] = max(g["conf"], conf)
        # Preferencia: con cuotas y de origen Betradar ('id...') primero; los
        # 'pn...' (origen Pinnacle) suelen traer menos casas.
        g["ids"].append((0 if f["tiene_cuotas"] else 1,
                         0 if str(f["fixture_id"]).startswith("id") else 1, f["fixture_id"]))
    if not grupos:
        return NO_ENCONTRADO, [], 0.0
    orden = sorted(grupos.values(), key=lambda g: -g["conf"])
    mejor = orden[0]
    if len(orden) > 1 and mejor["conf"] - orden[1]["conf"] < EMPATE:
        return AMBIGUO, [], mejor["conf"]
    ids = [x[2] for x in sorted(mejor["ids"])]
    if mejor["conf"] < UMBRAL_ENCONTRADO:
        return AMBIGUO, ids, mejor["conf"]
    return ENCONTRADO, ids, mejor["conf"]


class OddsPapi(Provider):
    metodo = "oddspapi"

    def __init__(self):
        self._candados: dict[str, asyncio.Lock] = {}
        self._transporte = None            # las pruebas lo sustituyen

    def _cliente(self, timeout: float) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, headers=CABECERAS, transport=self._transporte)

    async def _pedir(self, cli: httpx.AsyncClient, ruta: str, **params):
        params["apiKey"] = config.ODDSPAPI_API_KEY
        try:
            r = await cli.get(f"{config.ODDSPAPI_API}/{ruta}", params=params)
        except httpx.HTTPError as e:
            raise ProviderError(f"red: {type(e).__name__}") from None
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        if r.status_code != 200:
            codigo = ((cuerpo or {}).get("error") or {}).get("code") if isinstance(cuerpo, dict) else None
            if codigo == "RESTRICTED_ACCESS":
                raise SinAccesoEnVivo("partido en juego: sin acceso con este plan")
            raise ProviderError(f"HTTP {r.status_code} {codigo or ''}".strip())
        return cuerpo

    # ── 1. Lista de partidos ─────────────────────────────────────────────
    async def sincronizar_fixtures(self, conn: sqlite3.Connection) -> int:
        hoy = _ahora().date()
        async with self._cliente(config.TIMEOUT_FTR_S) as cli:
            lista = await self._pedir(
                cli, "fixtures", sportId=TENIS,
                **{"from": hoy.isoformat(),
                   "to": (hoy + timedelta(days=config.ODDSPAPI_DIAS_ADELANTE)).isoformat()})
        if not isinstance(lista, list):
            raise ProviderError("respuesta de /fixtures inesperada")
        n = guardar_fixtures(conn, lista)
        _estado(conn, "oddspapi_ultimo_ok", _iso(_ahora()))
        _estado(conn, "oddspapi_resumen", f"partidos={n}")
        conn.commit()
        return n

    async def bucle(self, conectar) -> None:
        """Tarea de fondo de BOT_BUSCADOR (nunca dentro de RankingFTR)."""
        while True:
            conn = conectar()
            try:
                n = await self.sincronizar_fixtures(conn)
                log.info(f"[oddspapi] {n} partidos")
            except Exception as e:
                _estado(conn, "oddspapi_ultimo_error", f"{_iso(_ahora())} {type(e).__name__}: {e}")
                conn.commit()
                log.warning(f"[oddspapi] lista de partidos no disponible: {type(e).__name__}: {e}")
            finally:
                conn.close()
            await asyncio.sleep(config.ODDSPAPI_SYNC_MINUTOS * 60)

    # ── 2. Enlaces de un partido ─────────────────────────────────────────
    def _enlaces_guardados(self, conn, fixture_id: str) -> dict[str, str]:
        return {r["bookmaker"]: r["url"] for r in conn.execute(
            "SELECT bookmaker, url FROM oddspapi_enlaces WHERE fixture_id = ?", (fixture_id,))}

    def _hay_que_preguntar(self, conn, fixture_id: str, slug: str) -> bool:
        if slug in self._enlaces_guardados(conn, fixture_id):
            return False
        c = conn.execute("SELECT consultado_en FROM oddspapi_consultas WHERE fixture_id = ?",
                         (fixture_id,)).fetchone()
        if not c:
            return True
        limite = _ahora() - timedelta(minutes=config.ODDSPAPI_REINTENTO_MIN)
        return datetime.fromisoformat(c["consultado_en"]) < limite

    async def enlaces(self, conn: sqlite3.Connection, fixture_id: str, slug: str) -> dict[str, str]:
        """Enlaces guardados del partido; pide a OddsPapi solo si hace falta.
        Una sola petición por partido aunque lleguen varias casas a la vez."""
        if not self._hay_que_preguntar(conn, fixture_id, slug):
            return self._enlaces_guardados(conn, fixture_id)
        candado = self._candados.setdefault(fixture_id, asyncio.Lock())
        async with candado:
            if not self._hay_que_preguntar(conn, fixture_id, slug):   # otra petición ya lo trajo
                return self._enlaces_guardados(conn, fixture_id)
            try:
                async with self._cliente(config.TIMEOUT_PROVIDER_S) as cli:
                    datos = await self._pedir(cli, "odds", fixtureId=fixture_id,
                                              bookmakers=",".join(sorted(set(CASAS.values()))))
            except SinAccesoEnVivo:
                conn.execute("INSERT OR REPLACE INTO oddspapi_consultas VALUES (?,?,?)",
                             (fixture_id, _iso(_ahora()), "en_vivo_sin_acceso"))
                conn.commit()
                if self._enlaces_guardados(conn, fixture_id):
                    return self._enlaces_guardados(conn, fixture_id)
                raise
            casas = (datos or {}).get("bookmakerOdds") or {}
            ahora = _iso(_ahora())
            for bm, info in casas.items():
                url = (info or {}).get("fixturePath") if isinstance(info, dict) else None
                if bm in CASAS.values() and isinstance(url, str) and url.startswith("https://"):
                    conn.execute("INSERT OR REPLACE INTO oddspapi_enlaces VALUES (?,?,?,?)",
                                 (fixture_id, bm, url, ahora))
            conn.execute("INSERT OR REPLACE INTO oddspapi_consultas VALUES (?,?,?)",
                         (fixture_id, ahora, "ok" if casas else "sin_casas"))
            conn.commit()
            return self._enlaces_guardados(conn, fixture_id)

    # ── 3. Resolver una casa ─────────────────────────────────────────────
    async def resolver_directo(self, conn: sqlite3.Connection, p: Partido,
                               provider_id: str) -> tuple[str, str | None, float, str | None]:
        """(estado, url, confianza, fixture_id)."""
        slug = CASAS.get(provider_id)
        if not slug:
            raise ProviderError(f"'{provider_id}' sin clave de OddsPapi")
        estado, ids, conf = emparejar(conn, p)
        if estado != ENCONTRADO:
            return estado, None, conf, None
        for fid in ids[:2]:
            url = (await self.enlaces(conn, fid, slug)).get(slug)
            if url:
                return ENCONTRADO, ajustar_url(provider_id, url), conf, fid
        c = conn.execute("SELECT resultado FROM oddspapi_consultas WHERE fixture_id = ?",
                         (ids[0],)).fetchone()
        if c and c["resultado"] == "en_vivo_sin_acceso":
            raise SinAccesoEnVivo("partido en juego: sin acceso con este plan")
        return NO_ENCONTRADO, None, conf, ids[0]

    async def candidatos(self, partido):   # el núcleo usa resolver_directo
        return []

    # ── 4. Barrido por torneos ──────────────────────────────────────────
    def torneos_para_barrido(self, conn, ventana_h: int) -> list[str]:
        """Torneos con partidos entre hace 3 h y dentro de `ventana_h` horas,
        los de más partidos primero."""
        ahora = _ahora()
        filas = conn.execute(
            "SELECT torneo_id, COUNT(*) n FROM oddspapi_fixtures WHERE torneo_id != '' "
            "AND substr(inicio,1,19) BETWEEN ? AND ? GROUP BY torneo_id ORDER BY n DESC",
            ((ahora - timedelta(hours=3)).isoformat()[:19],
             (ahora + timedelta(hours=ventana_h)).isoformat()[:19])).fetchall()
        return [r["torneo_id"] for r in filas]

    async def barrer(self, conn, ventana_h: int, max_peticiones: int,
                     casas: list[str] | None = None) -> dict:
        """1 petición por casa y lote de 5 torneos. Guarda SOLO el enlace
        (fixturePath) de cada partido; las cuotas se descartan."""
        torneos = self.torneos_para_barrido(conn, ventana_h)
        lotes = [torneos[i:i + 5] for i in range(0, len(torneos), 5)]
        casas = casas or sorted(set(CASAS.values()))
        r = {"torneos": len(torneos), "lotes": len(lotes), "casas": len(casas),
             "peticiones": 0, "enlaces": 0, "errores": 0, "cortado": ""}
        ahora = _iso(_ahora())
        async with self._cliente(max(config.TIMEOUT_FTR_S, 30)) as cli:
            for slug in casas:
                for lote in lotes:
                    if r["peticiones"] >= max_peticiones:
                        r["cortado"] = "máximo por barrido"
                        break
                    if r["peticiones"]:
                        await asyncio.sleep(config.ODDSPAPI_PAUSA_MS / 1000)
                    r["peticiones"] += 1
                    try:
                        datos = await self._pedir(cli, "odds-by-tournaments", bookmaker=slug,
                                                  tournamentIds=",".join(lote))
                    except ProviderError as e:
                        r["errores"] += 1
                        if "429" in str(e):
                            r["cortado"] = "429"
                            break
                        continue
                    for p in datos if isinstance(datos, list) else []:
                        info = ((p or {}).get("bookmakerOdds") or {}).get(slug)
                        url = info.get("fixturePath") if isinstance(info, dict) else None
                        if p.get("fixtureId") and isinstance(url, str) and url.startswith("https://"):
                            conn.execute("INSERT OR REPLACE INTO oddspapi_enlaces VALUES (?,?,?,?)",
                                         (str(p["fixtureId"]), slug, url, ahora))
                            r["enlaces"] += 1
                    conn.commit()
                if r["cortado"]:
                    break
        _estado(conn, "oddspapi_barrido",
                f"{_iso(_ahora())} torneos={r['torneos']} peticiones={r['peticiones']} "
                f"enlaces={r['enlaces']} errores={r['errores']}"
                f"{' cortado=' + r['cortado'] if r['cortado'] else ''}")
        conn.commit()
        return r

    async def bucle_barrido(self, conectar) -> None:
        """Tarea de fondo de BOT_BUSCADOR (solo si ODDSPAPI_BARRIDO_HORAS > 0)."""
        await asyncio.sleep(30)            # que llegue antes la lista de partidos
        while True:
            conn = conectar()
            try:
                r = await self.barrer(conn, config.ODDSPAPI_BARRIDO_VENTANA_H,
                                      config.ODDSPAPI_BARRIDO_MAX_PETICIONES)
                log.info(f"[oddspapi] barrido: {r}")
            except Exception as e:
                log.warning(f"[oddspapi] barrido: {type(e).__name__}: {e}")
            finally:
                conn.close()
            await asyncio.sleep(config.ODDSPAPI_BARRIDO_HORAS * 3600)

    # ── 5. Precarga partido a partido ───────────────────────────────────
    def _pendientes_de_precarga(self, conn, ventana_min: int) -> list[str]:
        """fixture_id de OddsPapi de los partidos de FullTenis que empiezan en
        los próximos `ventana_min` minutos (ITF sin hora: los de hoy) y cuyos
        enlaces aún no se han pedido. Los más próximos primero."""
        ahora = _ahora()
        limite = ahora + timedelta(minutes=ventana_min)
        hoy = ahora.date().isoformat()
        filas = conn.execute(
            "SELECT * FROM fixtures_cache WHERE substr(fecha,1,10) BETWEEN ? AND ? ORDER BY fecha",
            ((ahora - timedelta(days=1)).date().isoformat(), limite.date().isoformat())).fetchall()
        salida, vistos = [], set()
        for f in filas:
            if f["hora_conocida"]:
                try:
                    ini = datetime.fromisoformat(f["fecha"].replace("Z", "+00:00"))
                    if ini.tzinfo is None:
                        ini = ini.replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
                if not (ahora < ini <= limite):
                    continue
            elif f["fecha"][:10] != hoy:
                continue
            p = Partido(f["clave"], f["jugador1"], f["jugador2"], f["fecha"],
                        bool(f["hora_conocida"]), f["torneo"] or "", f["categoria"] or "")
            estado, ids, _ = emparejar(conn, p)
            if estado != ENCONTRADO or ids[0] in vistos:
                continue
            vistos.add(ids[0])
            if not conn.execute("SELECT 1 FROM oddspapi_consultas WHERE fixture_id = ?",
                                (ids[0],)).fetchone():
                salida.append(ids[0])
        return salida

    async def precargar(self, conn, ventana_min: int, maximo: int) -> dict:
        pendientes = self._pendientes_de_precarga(conn, ventana_min)
        r = {"pendientes": len(pendientes), "pedidos": 0, "errores": 0, "cortado": ""}
        slug = next(iter(CASAS.values()))
        for i, fid in enumerate(pendientes[:maximo]):
            if i:
                await asyncio.sleep(config.ODDSPAPI_PAUSA_MS / 1000)
            try:
                await self.enlaces(conn, fid, slug)
                r["pedidos"] += 1
            except SinAccesoEnVivo:
                r["errores"] += 1          # empezó justo ahora: queda anotado
            except ProviderError as e:
                r["errores"] += 1
                if "429" in str(e):        # límite de OddsPapi: seguir en el próximo ciclo
                    r["cortado"] = "429"
                    break
        _estado(conn, "oddspapi_precarga",
                f"{_iso(_ahora())} pendientes={r['pendientes']} pedidos={r['pedidos']} "
                f"errores={r['errores']}{' cortado=429' if r['cortado'] else ''}")
        conn.commit()
        return r

    async def bucle_precarga(self, conectar) -> None:
        """Tarea de fondo de BOT_BUSCADOR (solo si ODDSPAPI_PRECARGA_MIN > 0)."""
        await asyncio.sleep(20)            # que llegue antes la lista de partidos
        while True:
            conn = conectar()
            try:
                r = await self.precargar(conn, config.ODDSPAPI_PRECARGA_MIN,
                                         config.ODDSPAPI_PRECARGA_POR_CICLO)
                if r["pedidos"] or r["errores"]:
                    log.info(f"[oddspapi] precarga: {r}")
            except Exception as e:
                log.warning(f"[oddspapi] precarga: {type(e).__name__}: {e}")
            finally:
                conn.close()
            await asyncio.sleep(config.ODDSPAPI_PRECARGA_CADA_MIN * 60)
