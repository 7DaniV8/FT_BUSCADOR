"""
buscador/catalogo.py — Catálogo de providers, multirregión.

El núcleo NO conoce detalles de ninguna casa: solo este catálogo (qué existe,
dónde, en qué estado y con qué método) y el registro de providers.

ESTADOS
  ACTIVE                funciona y está validado
  TESTING               integrado, midiéndose
  COMING_SOON           previsto, todavía no
  NOT_AVAILABLE_REGION  no opera en esa región
  MAINTENANCE           apagado temporalmente
  DISABLED              retirado
  PROVIDER_PENDING      queremos integrarlo, pero todavía no hay vía limpia

Un provider en PROVIDER_PENDING nunca bloquea a los demás: responde su estado
y listo. No se fuerza ninguna integración (nada de sesiones, cookies, login
automático ni betslip).

La semilla se inserta SOLO si falta: un cambio de estado hecho a mano tras las
pruebas (p. ej. BetPlay -> ACTIVE) no lo pisa un redeploy. MIGRACIONES solo
toca filas que siguen exactamente como las dejó una semilla anterior.
"""
from __future__ import annotations

import json
import sqlite3

from . import config
from datetime import datetime, timezone

ACTIVE, TESTING, COMING_SOON = "ACTIVE", "TESTING", "COMING_SOON"
NOT_AVAILABLE_REGION, MAINTENANCE, DISABLED = "NOT_AVAILABLE_REGION", "MAINTENANCE", "DISABLED"
PROVIDER_PENDING = "PROVIDER_PENDING"
ESTADOS = (ACTIVE, TESTING, COMING_SOON, NOT_AVAILABLE_REGION, MAINTENANCE,
           DISABLED, PROVIDER_PENDING)
# Estados que un usuario puede marcar en "Mis casas".
SELECCIONABLES = (ACTIVE, TESTING)

CO, GLOBAL = "CO", "GLOBAL"
# EE. UU. es UNA región (02/10/2026): las direcciones de casi todas las casas son
# iguales en todos los estados; las que cambian (BetMGM, bet365) las ajusta el
# resolver al estado que elige el usuario (parámetro `estado`).
US = "US"
NC = FL = US


def _p(id_, nombre, region, estado, metodo, dominios=(), nota=""):
    return dict(id=id_, nombre=nombre, region=region, estado=estado, metodo=metodo,
                dominios=list(dominios), nota=nota)


_NOTA_OP = ("Enlace vía OddsPapi (solo fixturePath; sin cuotas ni betslip). "
            "Validar EVENTO CORRECTO y ABRE SIN LOGIN.")

SEMILLA = [
    # ── Otros providers (fuentes públicas) ──────────────────────────
    _p("kalshi", "Kalshi", GLOBAL, TESTING, "kalshi", ["kalshi.com"],
       "API oficial pública (series de tenis). Enlace kalshi.com/markets/<SERIE>/x/<EVENTO>."),
    _p("polymarket", "Polymarket", GLOBAL, TESTING, "polymarket", ["polymarket.com"],
       "API oficial pública (Gamma). Enlace polymarket.com/event/<slug>."),

    # ── North Carolina ───────────────────────────────────────────────
    _p("bet365_nc", "bet365", NC, TESTING, "respaldo", ["bet365.com"],
       nota="Solo tenis EN VIVO: bet365 usa un formato propio cifrado y una protección "
            "antibots; los enlaces de OddsPapi no abren el partido una vez empezado "
            "(probado el 02/10/2026)."),
    _p("hardrock_fl", "Hard Rock Bet", FL, TESTING, "hardrock", ["hardrock.bet"],
       nota="Datos públicos de su web (tenis en vivo, por estado: HARDROCK_CHANNEL/SEGMENT)."),
    _p("caesars_nc", "Caesars Sportsbook", NC, TESTING, "caesars", ["caesars.com"],
       "Datos públicos de su web (calendario de tenis). Enlace /tennis/<id>/<a-vs-b>."),
    _p("fanduel_nc", "FanDuel", NC, TESTING, "fanduel", ["fanduel.com"],
       "Datos públicos de su web (todo el tenis). Necesita FANDUEL_AK."),
    _p("betmgm_nc", "BetMGM", NC, TESTING, "betmgm", ["betmgm.com"],
       "Datos públicos de su web (tenis en vivo). Necesita BETMGM_ACCESSID. "
       "Petición de la lista deducida: confirmar con probar_bloqueos.py."),
    _p("draftkings_nc", "DraftKings", NC, TESTING, "draftkings", ["draftkings.com"],
       "Datos públicos de su web (tenis en vivo). Enlace /event/<seo>/<id>."),
    _p("fanatics_nc", "Fanatics Sportsbook", NC, PROVIDER_PENDING, "opticodds",
       nota="Sin web pública de apuestas (solo app); betfanatics.com es informativa. Respaldo."),
    _p("thescore_nc", "theScore Bet", NC, PROVIDER_PENDING, "opticodds",
       nota="OddsPapi no da enlace. Depende del trial de OpticOdds."),
    _p("betrivers_nc", "BetRivers", NC, NOT_AVAILABLE_REGION, "ninguno",
       nota="En catálogo, no habilitado para NC mientras no esté autorizado allí."),
    _p("underdog_nc", "Underdog", NC, COMING_SOON, "ninguno"),

    # ── Colombia ─────────────────────────────────────────────────────
    _p("betplay_co", "BetPlay", CO, TESTING, "kambi", ["betplay.com.co"],
       "Kambi (datos públicos, en vivo). Mismo número de evento que Rushbet."),
    _p("rushbet_co", "Rushbet", CO, TESTING, "kambi", ["rushbet.co"],
       "Kambi (datos públicos, en vivo). Mismo número de evento que BetPlay."),
    _p("betano_co", "Betano", CO, TESTING, "betano", ["betano.co"],
       "Datos públicos de su web (partidos en vivo + ficha de cada partido de tenis)."),
    _p("wplay_co", "Wplay", CO, TESTING, "wplay", ["wplay.co"],
       "Barra de partidos en vivo de su web (HTML). Enlace /es/e/<id>/<slug>."),
    _p("bwin_co", "Bwin", CO, TESTING, "betmgm", ["bwin.co"],
       "Mismo número de partido que BetMGM (Entain). Necesita BETMGM_ACCESSID."),
    *[_p(f"{i}_co", n, CO, PROVIDER_PENDING, "ninguno", nota=nota)
      for i, n, nota in (
          ("betsson", "Betsson", "OddsPapi da un enlace roto: buscador de la casa."),
          ("codere", "Codere", "Su web no pone el partido en la dirección: solo respaldo."),
          ("luckia", "Luckia", "No está en OddsPapi: buscador de la casa."),
          ("yajuego", "YaJuego", "No está en OddsPapi: buscador de la casa."),
          ("rivalo", "Rivalo", "No está en OddsPapi: buscador de la casa."),
          ("sportium", "Sportium", "No está en OddsPapi: buscador de la casa."),
          ("zamba", "Zamba", "No está en OddsPapi: buscador de la casa."),
          ("stake", "Stake", "OddsPapi solo trae stake.com: buscador de la casa."),
          ("bingocasino", "Bingo Casino", "No está en OddsPapi: buscador de la casa."),
          ("mryoker", "Mr. Yoker", "No está en OddsPapi: buscador de la casa."))],
]

# Sección de tenis de cada casa: adónde ir si no hay enlace directo al partido
# (el usuario busca el apellido, que la pestaña deja copiado). Solo se entrega
# si cae dentro de los dominios de la casa (lo comprueba app.py).
# Estados de EE. UU. donde opera cada casa con web por estado (fuente: listas
# públicas de septiembre de 2026). Si el usuario elige otro, la casa dice "no
# opera en tu estado" en vez de abrir una ventana inútil. Actualizar al cambiar.
ESTADOS_CASA = {
    "bet365_nc": {"az", "co", "il", "in", "ia", "ks", "ky", "la", "md", "mi", "mo", "nj", "nc",
                  "oh", "pa", "tn", "va"},
}

RESPALDO = {
    "betplay_co": "https://tienda.betplay.com.co/apuestas#filter/tennis",
    "rushbet_co": "https://www.rushbet.co/?page=sportsbook#filter/tennis",
    "betano_co": "https://www.betano.co/live/",
    "wplay_co": "https://apuestas.wplay.co/es",
    "bwin_co": "https://sports.bwin.co/es/sports/tenis-5",
    "draftkings_nc": "https://sportsbook.draftkings.com/sports/tennis",
    "fanduel_nc": "https://sportsbook.fanduel.com/tennis",
    "betmgm_nc": "https://www.nc.betmgm.com/en/sports/tennis-5",
    "caesars_nc": "https://sportsbook.caesars.com/tennis",
    "kalshi": "https://kalshi.com/sports/tennis",
    "polymarket": "https://polymarket.com/sports/tennis",
    # bet365: su tenis EN VIVO (tras un MTO el partido ya está en juego).
    "bet365_nc": "https://www.nc.bet365.com/#/IP/B13",
    "hardrock_fl": "https://app.hardrock.bet/",
}

# Filas ya sembradas con la configuración anterior. Solo se actualizan si
# siguen EXACTAMENTE como se sembraron (mismo método y estado de semilla): un
# cambio hecho a mano tras las pruebas nunca se pisa.
MIGRACIONES = {
    "kalshi": [("kalshi_api", TESTING), ("oddspapi", TESTING), ("ninguno", PROVIDER_PENDING)],
    "bet365_nc": [("opticodds", PROVIDER_PENDING)],
    "polymarket": [("polymarket_gamma", TESTING), ("oddspapi", TESTING), ("ninguno", PROVIDER_PENDING)],
    "fanduel_nc": [("opticodds", PROVIDER_PENDING), ("oddspapi", TESTING)],
    "betmgm_nc": [("opticodds", PROVIDER_PENDING), ("oddspapi", TESTING), ("ninguno", PROVIDER_PENDING)],
    "draftkings_nc": [("opticodds", PROVIDER_PENDING), ("oddspapi", TESTING)],
    "caesars_nc": [("opticodds", PROVIDER_PENDING)],
    "betplay_co": [("ninguno", PROVIDER_PENDING), ("oddspapi", TESTING)],
    "rushbet_co": [("ninguno", PROVIDER_PENDING), ("oddspapi", TESTING)],
    "betano_co": [("ninguno", PROVIDER_PENDING)],
    "wplay_co": [("ninguno", PROVIDER_PENDING)],
    "bwin_co": [("ninguno", PROVIDER_PENDING)],
}


def sembrar(conn: sqlite3.Connection) -> int:
    ahora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    nuevos = 0
    for p in SEMILLA:
        cur = conn.execute(
            "INSERT OR IGNORE INTO provider_catalog "
            "(id, nombre, region, estado, metodo, dominios, ultima_verificacion, nota) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (p["id"], p["nombre"], p["region"], p["estado"], p["metodo"],
             json.dumps(p["dominios"]), None, p["nota"]))
        nuevos += cur.rowcount
        if p["region"] == US:                 # bases antiguas: US-NC / US-FL → US
            conn.execute("UPDATE provider_catalog SET region=? WHERE id=? AND region LIKE 'US-%'",
                         (US, p["id"]))
        for viejo_metodo, viejo_estado in MIGRACIONES.get(p["id"], []):
            conn.execute(
                "UPDATE provider_catalog SET metodo=?, estado=?, dominios=?, nota=? "
                "WHERE id=? AND metodo=? AND estado=?",
                (p["metodo"], p["estado"], json.dumps(p["dominios"]), p["nota"],
                 p["id"], viejo_metodo, viejo_estado))
    conn.commit()
    if nuevos:
        conn.execute("INSERT OR REPLACE INTO sync_estado (clave, valor) VALUES (?,?)",
                     ("catalogo_sembrado_en", ahora))
        conn.commit()
    return nuevos


def listar(conn: sqlite3.Connection, region: str | None = None) -> list[dict]:
    q = "SELECT * FROM provider_catalog WHERE estado != ?"
    args: list = [DISABLED]
    if region:
        q += " AND (region = ? OR region = ?)"
        args += [region, GLOBAL]
    q += " ORDER BY region, nombre"
    salida = []
    for f in conn.execute(q, args):
        d = dict(f)
        if d["id"] in config.CASAS_OCULTAS:
            continue                          # oculta: ni se lista ni se elige
        d["dominios"] = json.loads(d["dominios"] or "[]")
        d["seleccionable"] = d["estado"] in SELECCIONABLES
        salida.append(d)
    return salida


def obtener(conn: sqlite3.Connection, provider_id: str) -> dict | None:
    f = conn.execute("SELECT * FROM provider_catalog WHERE id = ?", (provider_id,)).fetchone()
    if not f:
        return None
    d = dict(f)
    d["dominios"] = json.loads(d["dominios"] or "[]")
    if d["id"] in config.CASAS_OCULTAS:
        d["estado"] = DISABLED                # oculta: el resolver la trata como no disponible
    return d
