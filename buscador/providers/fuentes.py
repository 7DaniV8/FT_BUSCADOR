"""
providers/fuentes.py — Fuentes GRATUITAS: los datos públicos que usa la web de
cada casa (sin clave, sin cookies, sin sesión). Descubiertas con capturas HAR
reales el 30/09/2026.

  kambi       BetPlay + Rushbet   1 petición = todo el tenis EN VIVO; el mismo
                                  número de evento sirve para las dos casas
  fanduel     FanDuel             1 petición = todo el tenis (en vivo y próximo)
  draftkings  DraftKings          1 petición = todo el tenis EN VIVO
  caesars     Caesars             1 petición = calendario de tenis
  kalshi      Kalshi              API OFICIAL pública; 1 petición por serie de
                                  tenis (ATP, WTA, Challenger, ITF)
  betmgm      BetMGM + Bwin CO    1 petición = tenis EN VIVO (plataforma Entain);
                                  el mismo número sirve para bwin.co
  betano      Betano CO           1 petición = partidos en vivo (con deporte) +
                                  1 por partido de tenis NUEVO (nombres; se guardan)
  wplay       Wplay               1 página HTML: su barra de partidos en vivo
  hardrock    Hard Rock Bet       1-2 peticiones = tenis EN VIVO (por estado)
  polymarket  Polymarket          API OFICIAL pública (Gamma), eventos de tenis

Cada fuente:
  - se lee como máximo cada FUENTES_TTL_S segundos (caché en memoria) y se
    refresca en segundo plano: la petición del usuario casi nunca espera;
  - solo guarda por partido: número, jugador 1, jugador 2, inicio, torneo,
    si está en juego y lo necesario para el enlace. Nada de cuotas;
  - si falla o la casa la bloquea, esa casa da ERROR y las demás siguen.

Emparejamiento (común): los DOS jugadores de FullTenis, cada uno en su lado
del partido de la casa (en cualquier orden), y fecha compatible. Dobles fuera.
Dos partidos distintos que encajan igual: AMBIGUO (nunca se adivina).

AVISO: son datos no oficiales. Pueden cambiar sin aviso; la casa afectada cae
al respaldo (sección de tenis) sin romper nada.
"""
from __future__ import annotations

import asyncio
import html as html_mod
import logging
from json import loads as json_loads
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx

from .. import config
from ..claves import apellidos, dia, normalizar, tiene_hora
from ..resolver import AMBIGUO, ENCONTRADO, NO_ENCONTRADO, Partido
from .base import Provider, ProviderError

log = logging.getLogger("buscador.fuentes")
NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


def cabeceras_web(origen: str) -> dict:
    """Los encabezados que envía la propia web de la casa al pedir sus datos.
    Medido el 30/09/2026: DraftKings responde 403 sin ellos y 200 con ellos."""
    return {"Origin": origen, "Referer": origen + "/", "Accept-Language": "en-US,en;q=0.9",
            "sec-ch-ua": '"Chromium";v="130", "Google Chrome";v="130", "Not?A_Brand";v="99"',
            "sec-ch-ua-mobile": "?0", "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty", "sec-fetch-mode": "cors", "sec-fetch-site": "same-site"}
UMBRAL, EMPATE = 0.80, 0.10
TIEMPO_MAX_FUENTE_S = 15          # una fuente lenta nunca frena a las demás


class ErrorRed(ProviderError):
    """No hay conexión con la fuente (caída, bloqueada o inalcanzable)."""


async def _curl_get(url: str, params: dict, headers: dict, timeout: float, proxy: str | None = None):
    """GET con la huella de conexión de Chrome (curl_cffi). Devuelve (status, bytes).
    Solo para las fuentes de FUENTES_IMITAR_CHROME. `proxy`: salida por otro país."""
    try:
        from curl_cffi.requests import AsyncSession
    except ImportError:
        raise ProviderError("falta la librería curl_cffi (pip install curl_cffi)") from None
    try:
        extra = {"proxies": {"http": proxy, "https": proxy}} if proxy else {}
        async with AsyncSession(impersonate="chrome", timeout=timeout, **extra) as s:
            r = await s.get(url, params=params, headers=headers)
            return r.status_code, r.content
    except Exception as e:
        raise ErrorRed(f"sin conexión ({type(e).__name__})") from None


def _slug(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")


def _tokens(nombre: str) -> set[str]:
    return {t for t in normalizar(nombre).split() if len(t) > 1}


def _dobles(*nombres: str) -> bool:
    return any("/" in (n or "") for n in nombres)


def emparejar(p: Partido, eventos: list[dict]) -> tuple[str, dict | None, float]:
    """(estado, evento, confianza). Evento: {id, j1, j2, inicio, en_juego, ...}."""
    a1, a2 = apellidos(p.jugador1), apellidos(p.jugador2)
    if not a1 or not a2:
        return NO_ENCONTRADO, None, 0.0
    try:
        d0 = datetime.fromisoformat(dia(p.fecha)).date()
    except ValueError:
        d0 = None
    grupos: dict[str, tuple[float, dict]] = {}
    for ev in eventos:
        t1, t2 = _tokens(ev["j1"]), _tokens(ev["j2"])
        if not ((a1 & t1 and a2 & t2) or (a1 & t2 and a2 & t1)):
            continue
        conf = 0.9
        ini = str(ev.get("inicio") or "")
        if d0 and ini[:10]:
            try:
                dd = abs((datetime.fromisoformat(ini[:10]).date() - d0).days)
            except ValueError:
                dd = 0
            if dd > 1:
                continue                      # otro partido de los mismos jugadores
            conf += 0.05 if dd == 0 else 0.0
        if ev.get("en_juego"):
            conf += 0.03                      # flujo MTO: el partido está en juego
        if tiene_hora(p.fecha) and ini:
            try:
                fp = datetime.fromisoformat(p.fecha.replace("Z", "+00:00"))
                fe = datetime.fromisoformat(ini.replace("Z", "+00:00"))
                if fp.tzinfo and fe.tzinfo and abs((fe - fp).total_seconds()) > 8 * 3600:
                    conf -= 0.2
            except ValueError:
                pass
        clave = str(ev["id"])
        if clave not in grupos or conf > grupos[clave][0]:
            grupos[clave] = (min(conf, 1.0), ev)
    if not grupos:
        return NO_ENCONTRADO, None, 0.0
    if len(grupos) == 1:
        # Un ÚNICO partido de esos dos jugadores en ±1 día: es ese (02/10/2026,
        # medido en producción: Bu vs Djokovic salía "dudoso" en 7 casas porque
        # FullTenis lo tenía a las 01:00 y las casas a su hora real, más tarde).
        # La diferencia de hora solo sirve para elegir entre VARIOS candidatos.
        conf, ev = next(iter(grupos.values()))
        return ENCONTRADO, ev, max(conf, UMBRAL)
    orden = sorted(grupos.values(), key=lambda x: -x[0])
    if len(orden) > 1 and orden[0][0] - orden[1][0] < EMPATE:
        return AMBIGUO, None, orden[0][0]
    conf, ev = orden[0]
    return (ENCONTRADO if conf >= UMBRAL else AMBIGUO), ev, conf


class FuenteEnVivo(Provider):
    """Lista de partidos cacheada + emparejamiento + enlace por casa."""
    nombre = "fuente"
    ENLACES: dict[str, str] = {}             # provider_id -> plantilla

    def __init__(self):
        self._eventos: list[dict] = []
        self._cuando = 0.0
        self._error = ""
        self._fallo_en = 0.0                  # última lectura fallida (monotonic)
        self._candado = asyncio.Lock()
        self._transporte = None               # las pruebas lo sustituyen

    def configurada(self) -> bool:
        return not self.oculta()

    def oculta(self) -> bool:
        """Todas las casas de esta fuente están ocultas (CASAS_OCULTAS): no se lee su web."""
        return bool(self.ENLACES) and all(c in config.CASAS_OCULTAS for c in self.ENLACES)

    def _proxy(self) -> str | None:
        return config.FUENTES_PROXY.get(self.metodo)

    def _cliente(self) -> httpx.AsyncClient:
        proxy = self._proxy() if self._transporte is None else None
        return httpx.AsyncClient(timeout=config.TIMEOUT_PROVIDER_S, transport=self._transporte,
                                 headers={"User-Agent": NAVEGADOR,
                                          "Accept": "application/json, text/plain, */*"},
                                 **({"proxy": proxy} if proxy else {}))

    async def _cargar(self, cli: httpx.AsyncClient) -> list[dict]:
        raise NotImplementedError

    async def _get(self, cli, url, **kw):
        if self.metodo in config.FUENTES_IMITAR_CHROME and self._transporte is None:
            cab = {"User-Agent": NAVEGADOR, "Accept": "application/json, text/plain, */*",
                   **(kw.get("headers") or {})}
            try:
                status, cuerpo = await _curl_get(url, kw.get("params") or {}, cab,
                                                 config.TIMEOUT_PROVIDER_S, self._proxy())
            except ProviderError as e:
                raise type(e)(f"{self.nombre}: {e}") from None
            if status != 200:
                raise ProviderError(f"{self.nombre}: HTTP {status}")
            try:
                return json_loads(cuerpo)
            except ValueError:
                raise ProviderError(f"{self.nombre}: respuesta no es JSON") from None
        try:
            r = await cli.get(url, **kw)
        except httpx.HTTPError as e:
            raise ErrorRed(f"{self.nombre}: sin conexión ({type(e).__name__})") from None
        if r.status_code != 200:
            raise ProviderError(f"{self.nombre}: HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise ProviderError(f"{self.nombre}: respuesta no es JSON") from None

    async def _get_texto(self, cli, url, **kw) -> str:
        try:
            r = await cli.get(url, **kw)
        except httpx.HTTPError as e:
            raise ErrorRed(f"{self.nombre}: sin conexión ({type(e).__name__})") from None
        if r.status_code != 200:
            raise ProviderError(f"{self.nombre}: HTTP {r.status_code}")
        return r.text

    async def refrescar(self) -> int:
        async with self._candado:
            try:
                async with self._cliente() as cli:
                    evs = await self._cargar(cli)
                self._eventos = [e for e in evs if not _dobles(e["j1"], e["j2"])]
                self._cuando, self._error = time.monotonic(), ""
            except ProviderError as e:
                self._error, self._fallo_en = str(e), time.monotonic()
                raise
            return len(self._eventos)

    def _edad(self) -> float:
        return time.monotonic() - self._cuando if self._cuando else 1e9

    async def eventos(self, forzar: bool = False) -> list[dict]:
        """Lista cacheada. Se relee si está vieja (o si se fuerza); si la
        relectura falla, se sirve la última lista buena mientras no sea muy vieja."""
        if forzar or self._edad() > config.FUENTES_TTL_S:
            muy_vieja = self._edad() > config.FUENTES_TTL_S * 10
            fallo_reciente = self._fallo_en and time.monotonic() - self._fallo_en < config.FUENTES_TTL_S
            # Respuesta RÁPIDA (30/09/2026): si la fuente acaba de fallar o ya la está
            # leyendo la tarea de fondo, no se hace esperar al usuario: con datos
            # recientes se sirven; sin ellos, error inmediato (la pestaña abre la
            # sección de tenis de la casa en vez de agotar su tiempo).
            if muy_vieja and (fallo_reciente or self._candado.locked()):
                raise ProviderError(self._error or f"{self.nombre}: leyendo la casa, aún sin datos")
            if self._candado.locked():
                return self._eventos
            try:
                await self.refrescar()
            except ProviderError:
                if muy_vieja:
                    raise
        return self._eventos

    def estado(self) -> dict:
        return {"partidos": len(self._eventos), "error": self._error,
                "proxy": bool(self._proxy()),              # solo si hay: nunca la dirección
                "edad_s": round(time.monotonic() - self._cuando) if self._cuando else None}

    async def resolver_directo(self, conn, p: Partido, provider_id: str):
        plantilla = self.ENLACES.get(provider_id)
        if not plantilla:
            raise ProviderError(f"'{provider_id}' no es de la fuente {self.nombre}")
        estado, ev, conf = emparejar(p, await self.eventos())
        if estado == NO_ENCONTRADO and self._edad() > 15:
            # Flujo MTO: el partido pudo empezar después de la última lectura.
            estado, ev, conf = emparejar(p, await self.eventos(forzar=True))
        if estado != ENCONTRADO:
            return estado, None, conf, None
        return ENCONTRADO, plantilla.format(**ev), conf, str(ev["id"])

    async def candidatos(self, partido):      # el núcleo usa resolver_directo
        return []


# ── Kambi: BetPlay + Rushbet ──────────────────────────────────────────────
class Kambi(FuenteEnVivo):
    metodo, nombre = "kambi", "kambi"
    ENLACES = {"betplay_co": "https://tienda.betplay.com.co/apuestas#event/{id}",
               "rushbet_co": "https://www.rushbet.co/?page=sportsbook#event/{id}"}

    async def _cargar(self, cli):
        d = await self._get(
            cli, f"https://{config.KAMBI_HOST}/offering/v2018/{config.KAMBI_OPERADOR}/event/live/open.json",
            params={"lang": "es_CO", "market": "CO", "client_id": "200", "channel_id": "1",
                    "ncid": str(int(time.time() * 1000))})
        salida = []
        for x in (d or {}).get("liveEvents") or []:
            ev = (x or {}).get("event") or {}
            if ev.get("sport") != "TENNIS" or not ev.get("id"):
                continue
            salida.append({"id": ev["id"], "j1": ev.get("homeName", ""), "j2": ev.get("awayName", ""),
                           "inicio": ev.get("start", ""), "torneo": ev.get("group", ""),
                           "en_juego": ev.get("state") == "STARTED"})
        return salida


# ── FanDuel ───────────────────────────────────────────────────────────────
class FanDuel(FuenteEnVivo):
    metodo, nombre = "fanduel", "fanduel"
    ENLACES = {"fanduel_nc": "https://sportsbook.fanduel.com/tennis/{comp_slug}/{slug}-{id}"}

    def configurada(self) -> bool:
        return bool(config.FANDUEL_AK) and not self.oculta()

    async def _cargar(self, cli):
        if not config.FANDUEL_AK:
            raise ProviderError("fanduel: falta FANDUEL_AK")
        d = await self._get(
            cli, "https://api.sportsbook.fanduel.com/sbapi/content-managed-page",
            params={"page": "SPORT", "eventTypeId": "2", "_ak": config.FANDUEL_AK,
                    "timezone": "America/New_York"},
            headers={**cabeceras_web("https://sportsbook.fanduel.com"),
                     "x-sportsbook-region": config.FUENTES_ESTADO_US.upper()})
        att = (d or {}).get("attachments") or {}
        comps = att.get("competitions") or {}
        salida = []
        for ev in (att.get("events") or {}).values():
            nombre = str(ev.get("name") or "")
            if " v " not in nombre or not ev.get("eventId"):
                continue                      # fuera torneos 'a futuro' y similares
            j1, j2 = nombre.split(" v ", 1)
            comp = (comps.get(str(ev.get("competitionId"))) or {}).get("name", "")
            salida.append({"id": ev["eventId"], "j1": j1, "j2": j2, "inicio": ev.get("openDate", ""),
                           "torneo": comp, "en_juego": bool(ev.get("inPlay")),
                           "slug": _slug(nombre), "comp_slug": _slug(comp) or "e"})
        return salida


# ── DraftKings ────────────────────────────────────────────────────────────
class DraftKings(FuenteEnVivo):
    metodo, nombre = "draftkings", "draftkings"
    ENLACES = {"draftkings_nc": "https://sportsbook.draftkings.com/event/{seo}/{id}"}

    async def _cargar(self, cli):
        d = await self._get(
            cli, "https://sportsbook-nash.draftkings.com/api/sportscontent/views/dkuswv/v1/live",
            params={"tabId": "6"},
            headers={**cabeceras_web("https://sportsbook.draftkings.com"),
                     "x-client-name": "web", "x-client-page": "Live", "x-client-feature": "live-page",
                     "x-client-version": config.DK_CLIENT_VERSION})
        salida = []
        for ev in (d or {}).get("events") or []:
            if str(ev.get("sportId")) not in ("6", "") or not ev.get("id"):
                continue
            ps = sorted(ev.get("participants") or [], key=lambda x: x.get("sortOrder", 0))
            if len(ps) < 2:
                continue
            salida.append({"id": ev["id"], "j1": ps[0].get("name", ""), "j2": ps[1].get("name", ""),
                           "inicio": ev.get("startEventDate", ""), "torneo": "",
                           "en_juego": ev.get("status") == "STARTED",
                           "seo": ev.get("seoIdentifier") or _slug(ev.get("name", ""))})
        return salida


# ── Caesars ───────────────────────────────────────────────────────────────
class Caesars(FuenteEnVivo):
    metodo, nombre = "caesars", "caesars"
    ENLACES = {"caesars_nc": "https://sportsbook.caesars.com/tennis/{id}/{slug}"}
    _dispositivo = str(uuid.uuid4())        # identificador aleatorio del BOT, no de una persona

    async def _cargar(self, cli):
        d = await self._get(
            cli, f"https://api.americanwagering.com/regions/us/locations/{config.FUENTES_ESTADO_US}"
                 f"/brands/czr/sb/v4/sports/tennis/schedule",
            headers={**cabeceras_web("https://sportsbook.caesars.com"),
                     "x-app-version": config.CAESARS_APP_VERSION, "x-platform": "cordova-desktop",
                     "x-unique-device-id": self._dispositivo})
        salida = []
        for ev in d if isinstance(d, list) else []:
            eq = ((ev or {}).get("eventDisplay") or {}).get("teams") or []
            if len(eq) != 2 or not ev.get("eventId"):
                continue
            salida.append({"id": ev["eventId"], "j1": eq[0], "j2": eq[1],
                           "inicio": ev.get("startTime", ""), "torneo": ev.get("competitionName", ""),
                           "en_juego": bool(ev.get("started")),
                           "slug": _slug(f"{eq[0]} vs {eq[1]}")})
        return salida


# ── Kalshi (API oficial) ──────────────────────────────────────────────────
class Kalshi(FuenteEnVivo):
    """Eventos abiertos de cada serie de partidos de tenis. Página del partido:
    kalshi.com/markets/<SERIE>/x/<EVENTO> (el tramo del medio es de relleno).
    La fecha NO se toma de los cierres del mercado (no son la hora del partido):
    se deja vacía y el emparejamiento se hace por los jugadores."""
    metodo, nombre = "kalshi", "kalshi"
    ENLACES = {"kalshi": "https://kalshi.com/markets/{serie}/x/{id}"}

    async def _cargar(self, cli):
        salida, errores = [], 0
        for serie in config.KALSHI_SERIES:
            try:
                d = await self._get(cli, f"{config.KALSHI_API}/events",
                                    params={"series_ticker": serie, "status": "open",
                                            "with_nested_markets": "true", "limit": "200"})
            except ErrorRed:
                raise                         # Kalshi inalcanzable: no probar las demás series
            except ProviderError:
                errores += 1                  # serie inexistente (404) o fallo puntual
                continue
            for ev in (d or {}).get("events") or []:
                ticker = str(ev.get("event_ticker") or "").upper()
                if not ticker:
                    continue
                nombres = []
                for m in ev.get("markets") or []:
                    n = (m or {}).get("yes_sub_title") or ""
                    if n and n not in nombres:
                        nombres.append(n)
                if len(nombres) != 2:
                    t = re.split(r"\s+vs\.?\s+", str(ev.get("title") or ""), maxsplit=1)
                    nombres = [t[0].strip(), t[1].strip()] if len(t) == 2 else []
                if len(nombres) != 2:
                    continue
                salida.append({"id": ticker, "serie": str(ev.get("series_ticker") or serie).upper(),
                               "j1": nombres[0], "j2": nombres[1], "inicio": "",
                               "torneo": str(ev.get("sub_title") or ""), "en_juego": False})
        if errores == len(config.KALSHI_SERIES):
            raise ProviderError("kalshi: ninguna serie respondió")
        return salida


# ── BetMGM (Entain) ───────────────────────────────────────────────────────
class BetMGM(FuenteEnVivo):
    """Lista de partidos de tenis (deporte 5) EN VIVO. Enlace confirmado con la
    captura: /en/sports/events/<nombre-en-slug>-<id>, p. ej.
    jiri-lehecka-cze-zizou-bergs-bel-19972424."""
    metodo, nombre = "betmgm", "betmgm"
    # Bwin es de la misma empresa (Entain) y usa el mismo número de partido:
    # probado en Colombia con sports.bwin.co/es/sports/eventos/<id>.
    ENLACES = {"betmgm_nc": "https://{host}/en/sports/events/{slug}-{id}",
               "bwin_co": "https://sports.bwin.co/es/sports/eventos/{id}"}

    def configurada(self) -> bool:
        return bool(config.BETMGM_ACCESSID) and not self.oculta()

    async def _cargar(self, cli):
        if not config.BETMGM_ACCESSID:
            raise ProviderError("betmgm: falta BETMGM_ACCESSID")
        d = await self._get(
            cli, f"https://{config.BETMGM_HOST}/cds-api/bettingoffer/fixtures",
            params={"x-bwin-accessid": config.BETMGM_ACCESSID, "lang": "en-us", "country": "US",
                    "userCountry": "US", "subdivision": config.BETMGM_SUBDIVISION,
                    "fixtureTypes": "Standard", "state": "Live", "offerMapping": "Filtered",
                    "sportIds": "5", "skip": "0", "take": "200", "sortBy": "StartDate"},
            headers=cabeceras_web(f"https://{config.BETMGM_HOST}"))
        salida = []
        for fx in (d or {}).get("fixtures") or []:
            ps = [((p or {}).get("name") or {}).get("value", "") for p in fx.get("participants") or []]
            nombre = ((fx.get("name") or {}).get("value") or " - ".join(ps))
            if len(ps) != 2 or not fx.get("id"):
                continue
            sport = (fx.get("sport") or {}).get("id")
            if sport not in (None, 5, "5"):
                continue
            limpio = [re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", n) for n in ps]   # 'Lehecka (CZE)' -> 'Lehecka'
            salida.append({"id": fx["id"], "j1": limpio[0], "j2": limpio[1],
                           "inicio": fx.get("startDate", ""), "torneo": "",
                           "en_juego": str(fx.get("stage")) == "Live",
                           "slug": _slug(nombre), "host": config.BETMGM_HOST})
        return salida


# ── Polymarket (API oficial Gamma) ────────────────────────────────────────
class Polymarket(FuenteEnVivo):
    """Eventos abiertos con etiqueta de tenis. Página: polymarket.com/event/<slug>.
    Las fechas de los mercados NO son la hora del partido; la fecha del partido
    va al final del slug (itf-rocha3-schoen1-2026-09-23) y es la que se usa.
    Medido: siguen 'abiertos' partidos de hace meses; se descartan (> 2 días)."""
    metodo, nombre = "polymarket", "polymarket"
    ENLACES = {"polymarket": "https://polymarket.com/event/{id}"}
    _NO_NOMBRE = {"yes", "no", "si", "sí"}

    async def _cargar(self, cli):
        salida, vistos, errores = [], set(), 0
        limite = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
        for tag in config.POLYMARKET_TAGS:
            try:
                d = await self._get(cli, f"{config.POLYMARKET_API}/events",
                                    params={"tag_slug": tag, "closed": "false", "active": "true",
                                            "limit": "500"})
            except ErrorRed:
                raise
            except ProviderError:
                errores += 1
                continue
            for ev in d if isinstance(d, list) else []:
                slug = str((ev or {}).get("slug") or "")
                if not slug or slug in vistos:
                    continue
                nombres = []
                for m in ev.get("markets") or []:
                    try:
                        oc = m.get("outcomes")
                        oc = json_loads(oc) if isinstance(oc, str) else (oc or [])
                    except ValueError:
                        oc = []
                    if len(oc) == 2 and not ({normalizar(x) for x in oc} & self._NO_NOMBRE):
                        nombres = [str(oc[0]), str(oc[1])]
                        break
                if not nombres:
                    t = str(ev.get("title") or "").split(":")[-1]
                    t = re.split(r"\s+vs\.?\s+", t, maxsplit=1)
                    nombres = [t[0].strip(), t[1].strip()] if len(t) == 2 else []
                if len(nombres) != 2:
                    continue
                fecha = re.search(r"(\d{4}-\d{2}-\d{2})$", slug)
                fecha = fecha.group(1) if fecha else ""
                if fecha and fecha < limite:
                    continue                  # partido pasado que sigue 'abierto'
                vistos.add(slug)
                salida.append({"id": slug, "j1": nombres[0], "j2": nombres[1], "inicio": fecha,
                               "torneo": str(ev.get("title") or ""), "en_juego": False})
        if errores == len(config.POLYMARKET_TAGS):
            raise ProviderError("polymarket: ninguna etiqueta respondió")
        return salida


# ── Betano Colombia ──────────────────────────────────────────────────────
class Betano(FuenteEnVivo):
    """1) availabilities: TODOS los partidos en vivo con su deporte (TENN = tenis).
    2) De cada partido de tenis NUEVO, su ficha (nombres y dirección); se guarda
       mientras siga en vivo, así que en régimen normal es 1 petición por lectura.
    El número es el mismo en todos los países de Betano: se puede leer de otra
    web (BETANO_HOST) y enlazar siempre a la colombiana (BETANO_ENLACE_HOST):
    /live/<jugador-jugador>/<id>/ (formato de la captura)."""
    metodo, nombre = "betano", "betano"
    ENLACES = {"betano_co": "https://{host}/live/{slug}/{id}/"}

    def __init__(self):
        super().__init__()
        self._fichas: dict[str, dict] = {}

    def _cab(self):
        c = {**cabeceras_web(f"https://{config.BETANO_HOST}"), "sec-fetch-site": "same-origin"}
        if config.BETANO_X_LANGUAGE:
            c["x-language"] = config.BETANO_X_LANGUAGE
        if config.BETANO_X_OPERATOR:
            c["x-operator"] = config.BETANO_X_OPERATOR
        return c

    async def _ficha(self, cli, id_):
        try:
            d = await self._get(cli, f"https://{config.BETANO_HOST}/danae-webapi/api/live/events/{id_}/latest",
                                headers=self._cab())
        except ErrorRed:
            raise
        except ProviderError:
            return None                        # ese partido acaba de terminar, etc.
        ev = (d or {}).get("event") or {}
        ps = [p.get("name", "") for p in ev.get("participants") or []]
        if len(ps) != 2:
            return None
        ms = ev.get("startTime")
        ini = (datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")
               if isinstance(ms, (int, float)) else "")
        return {"id": ev.get("id", id_), "j1": ps[0], "j2": ps[1], "inicio": ini, "torneo": "",
                "en_juego": True, "slug": _slug(f"{ps[0]} {ps[1]}"), "host": config.BETANO_ENLACE_HOST}

    async def _cargar(self, cli):
        d = await self._get(cli, f"https://{config.BETANO_HOST}/danae-webapi/api/live/availabilities/latest",
                            headers=self._cab())
        le = (d or {}).get("liveEvents") if isinstance(d, dict) else None
        lista = le.values() if isinstance(le, dict) else (le if isinstance(le, list) else [])
        vivos = [str(v.get("eventId")) for v in lista
                 if isinstance(v, dict) and v.get("sportId") == "TENN" and v.get("eventId")]
        nuevos = [i for i in vivos if i not in self._fichas][:config.BETANO_MAX_NUEVOS]
        for i in range(0, len(nuevos), 5):                     # de 5 en 5
            fichas = await asyncio.gather(*(self._ficha(cli, x) for x in nuevos[i:i + 5]))
            for x, f in zip(nuevos[i:i + 5], fichas):
                if f:
                    self._fichas[x] = f
        self._fichas = {k: v for k, v in self._fichas.items() if k in vivos}   # fuera los acabados
        return list(self._fichas.values())


# ── Wplay ─────────────────────────────────────────────────────────────────
_WPLAY = re.compile(r'class="expander event sport-TENN[^"]*"[^>]*>\s*<h6[^>]*title="([^"]+)"[^>]*>'
                    r'\s*<a href="(/es/e/(\d+)/[^"?#]+)"', re.S)


_WPLAY_CUALQUIERA = re.compile(r'class="expander event sport-[A-Z]+[^"]*"[^>]*>\s*<h6[^>]*>'
                               r'\s*<a href="(/es/e/\d+/[^"?#]+)"', re.S)


class Wplay(FuenteEnVivo):
    """Las páginas de Wplay llevan una barra de partidos EN VIVO; cada uno marcado
    con su deporte (sport-TENN), su nombre y su dirección /es/e/<id>/<slug>.
    Medido: la portada trae pocos (destacados) y la página de un partido trae la
    barra completa. Así que: 1) portada; 2) la página de cualquier partido en
    vivo que aparezca en ella; se juntan ambas listas."""
    metodo, nombre = "wplay", "wplay"
    ENLACES = {"wplay_co": "https://apuestas.wplay.co{ruta}"}
    _CAB = {"Accept": "text/html,application/xhtml+xml", "Accept-Language": "es-CO,es;q=0.9"}

    @staticmethod
    def _leer(pagina: str) -> dict[str, dict]:
        salida = {}
        for titulo, ruta, id_ in _WPLAY.findall(pagina):
            titulo = html_mod.unescape(titulo)
            if " v " not in titulo:
                continue
            j1, j2 = titulo.split(" v ", 1)
            salida[id_] = {"id": id_, "j1": j1.strip(), "j2": j2.strip(), "inicio": "",
                           "torneo": "", "en_juego": True, "ruta": ruta}
        return salida

    async def _cargar(self, cli):
        portada = await self._get_texto(cli, config.WPLAY_URL, headers=self._CAB)
        if "expander event sport-" not in portada:
            raise ProviderError("wplay: la página no trae la barra de partidos en vivo")
        eventos = self._leer(portada)
        otro = _WPLAY_CUALQUIERA.search(portada)
        if otro:
            try:
                completa = await self._get_texto(cli, "https://apuestas.wplay.co" + otro.group(1),
                                                 headers=self._CAB)
                eventos.update(self._leer(completa))
            except ProviderError:
                pass                          # nos quedamos con lo de la portada
        return list(eventos.values())


# ── Hard Rock Bet ─────────────────────────────────────────────────────────
def _camel(texto: str) -> str:
    """'WTA Beijing' → 'wtaBeijing' (formato de la dirección de Hard Rock)."""
    palabras = [p for p in re.split(r"[^0-9A-Za-z]+", normalizar(texto)) if p]
    return (palabras[0] + "".join(p[:1].upper() + p[1:] for p in palabras[1:])) if palabras else "tennis"


class HardRock(FuenteEnVivo):
    """Tenis EN VIVO de Hard Rock Bet (captura del 02/10/2026). Sin cookies.
    Enlace: app.hardrock.bet/competition/<torneoEnCamelCase>/<id>, p. ej.
    /competition/wtaBeijing/5750617385245737388."""
    metodo, nombre = "hardrock", "hardrock"
    ENLACES = {"hardrock_fl": "https://app.hardrock.bet/competition/{comp_slug}/{id}"}

    async def _cargar(self, cli):
        salida, offset = [], 0
        desde = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)
        for _ in range(4):                                        # hasta 200 partidos
            d = await self._get(
                cli, "https://api.hardrocksportsbook.com/java-graphql/events",
                params={"channel": config.HARDROCK_CHANNEL, "segment": config.HARDROCK_SEGMENT,
                        "region": "us", "language": "enus", "sports": "TENNIS", "outright": "false",
                        "inplay": "true", "start": str(desde), "sort": "compEventWeightingV2",
                        "sortDesc": "false", "offset": str(offset), "limit": "50",
                        "includeCount": "true", "includeMarkets": "false"},
                headers=cabeceras_web("https://app.hardrock.bet"))
            lote = (d or {}).get("data") or []
            for ev in lote:
                nombre = str(ev.get("name") or "")
                if " vs " not in nombre or not ev.get("id"):
                    continue
                j1, j2 = nombre.split(" vs ", 1)
                ms = ev.get("eventTime")
                try:
                    ini = datetime.fromtimestamp(int(ms) / 1000, timezone.utc).isoformat(timespec="seconds")
                except (TypeError, ValueError):
                    ini = ""
                salida.append({"id": str(ev["id"]), "j1": j1.strip(), "j2": j2.strip(), "inicio": ini,
                               "torneo": str(ev.get("compName") or ""), "en_juego": bool(ev.get("inplay")),
                               "comp_slug": _camel(str(ev.get("compName") or ""))})
            if len(lote) < 50:
                break
            offset += 50
        return salida


FUENTES = {f.metodo: f for f in (Kambi(), FanDuel(), DraftKings(), Caesars(), Kalshi(),
                                 BetMGM(), Polymarket(), Betano(), Wplay(), HardRock())}


async def refrescar_todas() -> dict[str, str]:
    """Lee TODAS las fuentes configuradas A LA VEZ, cada una con tiempo máximo.
    Devuelve {fuente: 'N partidos' | 'error'}."""
    async def una(f):
        if not f.configurada():
            return f.metodo, "sin configurar"
        try:
            n = await asyncio.wait_for(f.refrescar(), TIEMPO_MAX_FUENTE_S)
            return f.metodo, f"{n} partidos"
        except asyncio.TimeoutError:
            f._error = f"{f.nombre}: sin respuesta en {TIEMPO_MAX_FUENTE_S} s"
            f._fallo_en = time.monotonic()
            return f.metodo, f"✗ {f._error}"
        except Exception as e:
            return f.metodo, f"✗ {e}"
    return dict(await asyncio.gather(*(una(f) for f in FUENTES.values())))


PROXY_DIAG: dict[str, dict] = {}            # fuente -> {pais, region, ms, error, cuando}


async def diagnosticar_proxies() -> dict[str, dict]:
    """¿Por dónde sale de verdad cada proxy y cuánto tarda? (ipinfo.io, a través
    del propio proxy). Solo país/región/tiempo: nunca la dirección del proxy."""
    for fuente, proxy in config.FUENTES_PROXY.items():
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=25, proxy=proxy) as cli:
                r = await cli.get("https://ipinfo.io/json")
            d = r.json()
            PROXY_DIAG[fuente] = {"pais": d.get("country"), "region": d.get("region"),
                                  "ms": round((time.monotonic() - t0) * 1000), "error": "",
                                  "cuando": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        except Exception as e:
            PROXY_DIAG[fuente] = {"pais": None, "region": None,
                                  "ms": round((time.monotonic() - t0) * 1000),
                                  "error": type(e).__name__,
                                  "cuando": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    return PROXY_DIAG


async def bucle(intervalo_s: int | None = None) -> None:
    """Refresca en segundo plano las fuentes configuradas (tarea del BOT) y, cada
    ~5 min, comprueba por dónde salen los proxies."""
    vuelta = 0
    while True:
        if config.FUENTES_PROXY and vuelta % 7 == 0:
            try:
                for f_, d_ in (await diagnosticar_proxies()).items():
                    if d_["error"] or d_["pais"] != "CO":
                        log.warning(f"[proxy {f_}] sale por {d_['pais']} en {d_['ms']} ms {d_['error']}")
            except Exception as e:
                log.warning(f"[proxy] diagnóstico falló: {type(e).__name__}")
        vuelta += 1
        for m, r in (await refrescar_todas()).items():
            if r.startswith("✗"):
                log.warning(f"[{m}] {r}")
        await asyncio.sleep(intervalo_s or config.FUENTES_TTL_S)
