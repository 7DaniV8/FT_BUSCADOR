"""
buscador/config.py — Configuración de BOT_BUSCADOR (todo por variables de entorno).

BOT_BUSCADOR es un servicio INDEPENDIENTE y DESECHABLE:
  * su propia base (BUSCADOR_DB_PATH), en su propio volumen
  * lee partidos de FullTenis SOLO por GET /ft-intel/fixtures y
    GET /ft-intel/en-vivo, con FTR_LECTURA_SECRET (solo lectura, solo esas
    dos rutas). Nunca usa FTR_INTERNAL_SECRET.
  * RankingFTR nunca lo llama. Si este servicio se apaga, FullTenis sigue igual.
"""
from __future__ import annotations

import os


def _int(nombre: str, defecto: int, minimo: int, maximo: int) -> int:
    try:
        v = int(os.getenv(nombre, str(defecto)))
    except ValueError:
        v = defecto
    return max(minimo, min(maximo, v))


# ── FullTenis (solo lectura) ─────────────────────────────────────────
FTR_SERVICE_URL = os.getenv("FTR_SERVICE_URL", "").rstrip("/")
FTR_LECTURA_SECRET = os.getenv("FTR_LECTURA_SECRET", "")

# Sincronización de fixtures: 5-10 minutos (regla definitiva). Se acota
# para que un valor mal puesto no convierta al buscador en carga para FTR.
SYNC_MINUTOS = _int("SYNC_MINUTOS", 7, 5, 10)
SYNC_HORAS_ATRAS = _int("SYNC_HORAS_ATRAS", 12, 0, 72)
SYNC_HORAS_ADELANTE = _int("SYNC_HORAS_ADELANTE", 48, 1, 96)
SYNC_ACTIVO = os.getenv("SYNC_ACTIVO", "1") == "1"

# ── Token del usuario (emitido por FullTenis) ────────────────────────
BUSCADOR_TOKEN_SECRET = os.getenv("BUSCADOR_TOKEN_SECRET", "")
TOKEN_AUDIENCIA = "bot_buscador"

# ── Web ──────────────────────────────────────────────────────────────
# Orígenes que pueden llamar desde el navegador (el dominio de FullTenis).
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in
                   os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# ── Base propia ──────────────────────────────────────────────────────
BUSCADOR_DB_PATH = os.getenv("BUSCADOR_DB_PATH", "/data/bot_buscador.db")

# ── Tiempos máximos ──────────────────────────────────────────────────
# Por casa: una que tarda no retrasa a las demás (el navegador las pide en
# paralelo) y tampoco se queda colgada en el servidor.
TIMEOUT_PROVIDER_S = float(os.getenv("TIMEOUT_PROVIDER_S", "6"))
TIMEOUT_FTR_S = float(os.getenv("TIMEOUT_FTR_S", "15"))

# ── Fuentes gratuitas (datos públicos de la web de cada casa) ────────────
# Ver providers/fuentes.py. Ninguna usa cookies ni sesión.
FUENTES_TTL_S = _int("FUENTES_TTL_S", 45, 15, 600)          # cada cuánto se relee cada fuente
FUENTES_ESTADO_US = (os.getenv("FUENTES_ESTADO_US", "nc").strip().lower() or "nc")[:2]
KAMBI_HOST = os.getenv("KAMBI_HOST", "us.offering-api.kambicdn.com").strip()
KAMBI_OPERADOR = os.getenv("KAMBI_OPERADOR", "betplay").strip()   # mismo número para BetPlay y Rushbet
FANDUEL_AK = os.getenv("FANDUEL_AK", "").strip()             # parámetro _ak público de su web
DK_CLIENT_VERSION = os.getenv("DK_CLIENT_VERSION", "2640.2.1.7").strip()
# Casas OCULTAS (02/10/2026): no aparecen en la pestaña, se quitan de "Mis casas"
# y el BOT deja de leer su web. Para recuperar una, quitarla de la variable.
# Por defecto: bet365 (nunca abre el partido) y Caesars (bloquea al programa).
# Betano se queda: funcionó y, si su salida por Colombia falla, responde al
# instante con su sección de tenis.
CASAS_OCULTAS = {x.strip().lower() for x in os.getenv(
    "CASAS_OCULTAS", "bet365_nc,caesars_nc").split(",") if x.strip()}
# Fuentes que solo responden a una conexión con la huella de Chrome (curl_cffi).
# Medido el 30/09/2026: BetMGM y Betano rechazan (403) a cualquier programa salvo así.
# Riesgo: la casa no lo permite y puede bloquear la IP; se apaga dejándolo vacío.
FUENTES_IMITAR_CHROME = {x.strip().lower() for x in os.getenv(
    "FUENTES_IMITAR_CHROME", "betmgm,betano").split(",") if x.strip()}
# Proxy por fuente (p. ej. Betano solo responde a IPs colombianas y el servidor
# está en EE. UU.). Formato: "betano=http://usuario:clave@host:puerto,otra=...".
# Es un SECRETO: nunca se muestra en logs ni en /salud.
def normalizar_proxy(texto: str) -> str:
    """Acepta los dos formatos que dan los proveedores y devuelve
    http://usuario:clave@host:puerto (usuario y clave codificados).
      - http://usuario:clave@host:puerto   (se deja igual)
      - host:puerto:usuario:clave          (se convierte)
      - host:puerto                        (sin usuario)"""
    from urllib.parse import quote
    t = (texto or "").strip()
    if not t or "://" in t:
        return t
    partes = t.split(":")
    if len(partes) >= 4:
        host, puerto, usuario, clave = partes[0], partes[1], partes[2], ":".join(partes[3:])
        return f"http://{quote(usuario, safe='')}:{quote(clave, safe='')}@{host}:{puerto}"
    return f"http://{t}"


def _proxies(texto: str) -> dict:
    salida = {}
    for trozo in (texto or "").split(","):
        if "=" in trozo:
            fuente, url = trozo.split("=", 1)
            if fuente.strip() and url.strip():
                salida[fuente.strip().lower()] = normalizar_proxy(url)
    return salida


FUENTES_PROXY = _proxies(os.getenv("FUENTES_PROXY", ""))
# BetMGM (plataforma Entain): código público de acceso de su web (x-bwin-accessid).
BETMGM_ACCESSID = os.getenv("BETMGM_ACCESSID", "").strip()
BETMGM_HOST = os.getenv("BETMGM_HOST", "www.nc.betmgm.com").strip()
BETMGM_SUBDIVISION = os.getenv("BETMGM_SUBDIVISION", "US-NorthCarolina").strip()
# Polymarket: API oficial (Gamma). Etiquetas de tenis a leer.
POLYMARKET_API = os.getenv("POLYMARKET_API", "https://gamma-api.polymarket.com").rstrip("/")
POLYMARKET_TAGS = [x.strip() for x in os.getenv("POLYMARKET_TAGS", "tennis").split(",") if x.strip()]
# Betano: usa el MISMO número de partido en todos sus países. Se lee de la web
# de BETANO_HOST (la que responda desde el servidor) y se enlaza SIEMPRE a
# BETANO_ENLACE_HOST (Colombia). Encabezados x-* de la web colombiana; vacíos = no se envían.
BETANO_HOST = os.getenv("BETANO_HOST", "www.betano.co").strip()
BETANO_ENLACE_HOST = os.getenv("BETANO_ENLACE_HOST", "www.betano.co").strip()
BETANO_X_LANGUAGE = os.getenv("BETANO_X_LANGUAGE", "8").strip()
BETANO_X_OPERATOR = os.getenv("BETANO_X_OPERATOR", "17").strip()
BETANO_MAX_NUEVOS = _int("BETANO_MAX_NUEVOS", 20, 1, 100)   # detalles nuevos por lectura
# Wplay: cualquier página suya lleva la barra de partidos en vivo.
WPLAY_URL = os.getenv("WPLAY_URL", "https://apuestas.wplay.co/es").strip()
# Hard Rock Bet: su web pide los partidos por estado (canal y segmento).
# Valores de la captura del 02/10/2026 (Florida); cambiar si se usa otro estado.
HARDROCK_CHANNEL = os.getenv("HARDROCK_CHANNEL", "FLORIDA_ONLINE").strip()
HARDROCK_SEGMENT = os.getenv("HARDROCK_SEGMENT", "fl").strip()
# Kalshi: API oficial y pública. Series de partidos de tenis (las que no existan se saltan).
KALSHI_API = os.getenv("KALSHI_API", "https://api.elections.kalshi.com/trade-api/v2").rstrip("/")
KALSHI_SERIES = [x.strip().upper() for x in os.getenv(
    "KALSHI_SERIES", "KXATPMATCH,KXWTAMATCH,KXATPCHALLENGERMATCH,KXWTACHALLENGERMATCH,"
                     "KXITFMATCH,KXITFWMATCH").split(",") if x.strip()]
CAESARS_APP_VERSION = os.getenv("CAESARS_APP_VERSION", "7.56.2").strip()

# ── Fuentes externas ─────────────────────────────────────────────────
# OddsPapi: de cada partido solo se usa el ENLACE de cada casa (fixturePath).
# Cuotas, mercados y betslip se ignoran. Ver providers/oddspapi.py.
ODDSPAPI_API_KEY = os.getenv("ODDSPAPI_API_KEY", "")
ODDSPAPI_API = os.getenv("ODDSPAPI_API", "https://api.oddspapi.io/v4").rstrip("/")
# Lista de partidos de OddsPapi: 1 petición por ciclo.
ODDSPAPI_SYNC_MINUTOS = _int("ODDSPAPI_SYNC_MINUTOS", 120, 30, 720)
ODDSPAPI_DIAS_ADELANTE = _int("ODDSPAPI_DIAS_ADELANTE", 1, 0, 3)
# Si una casa no traía enlace, no se vuelve a preguntar antes de esto.
ODDSPAPI_REINTENTO_MIN = _int("ODDSPAPI_REINTENTO_MIN", 30, 5, 720)
# PRECARGA: pedir los enlaces ANTES de que empiece cada partido, porque con el
# plan gratuito OddsPapi no da enlaces de partidos en juego. 0 = desactivada.
# Ventana en minutos antes del inicio (p. ej. 90). Cuesta 1 petición por partido.
ODDSPAPI_PRECARGA_MIN = _int("ODDSPAPI_PRECARGA_MIN", 0, 0, 720)
ODDSPAPI_PRECARGA_CADA_MIN = _int("ODDSPAPI_PRECARGA_CADA_MIN", 10, 2, 120)
ODDSPAPI_PRECARGA_POR_CICLO = _int("ODDSPAPI_PRECARGA_POR_CICLO", 30, 1, 500)
ODDSPAPI_PAUSA_MS = _int("ODDSPAPI_PAUSA_MS", 1500, 0, 10000)   # entre peticiones (evita el 429)
# BARRIDO POR TORNEOS: cada N horas, /odds-by-tournaments trae los enlaces de
# TODOS los partidos de 5 torneos por petición y casa (~50 partidos cada una).
# Es la forma barata de tenerlos guardados antes de que empiecen (flujo MTO).
# 0 = desactivado. Coste por barrido ~ casas × (torneos / 5).
ODDSPAPI_BARRIDO_HORAS = _int("ODDSPAPI_BARRIDO_HORAS", 0, 0, 48)
ODDSPAPI_BARRIDO_VENTANA_H = _int("ODDSPAPI_BARRIDO_VENTANA_H", 30, 1, 240)
ODDSPAPI_BARRIDO_MAX_PETICIONES = _int("ODDSPAPI_BARRIDO_MAX_PETICIONES", 200, 1, 5000)
# Estado de EE. UU. para las casas cuyo enlace lleva el estado (BetMGM).
ODDSPAPI_ESTADO_US = (os.getenv("ODDSPAPI_ESTADO_US", "nc").strip().lower() or "nc")[:2]
OPTICODDS_API_KEY = os.getenv("OPTICODDS_API_KEY", "")

# ── Modo de prueba (SOLO staging) ────────────────────────────────────
# Simula fallos para las pruebas de aislamiento. Valores separados por coma:
#   lento            todas las respuestas de /api tardan 20 s
#   error500         todas las respuestas de /api devuelven 500
#   oddspapi_caido   los providers que dependen de OddsPapi dan ERROR
#   opticodds_caido  los providers que dependen de OpticOdds dan ERROR
#   casa_falla:ID    ese provider concreto da ERROR
# En producción debe estar vacío. El servicio lo avisa en /salud.
MODO_PRUEBA = {m.strip() for m in os.getenv("MODO_PRUEBA", "").split(",") if m.strip()}


def casa_que_falla() -> set[str]:
    return {m.split(":", 1)[1] for m in MODO_PRUEBA if m.startswith("casa_falla:")}
