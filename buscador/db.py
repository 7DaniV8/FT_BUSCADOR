"""
buscador/db.py — La base PROPIA de BOT_BUSCADOR.

Nada de esto vive en la base de FullTenis. Si mañana se borra el servicio,
se borra esta base con él y FullTenis no pierde nada.

Tablas:
  provider_catalog    casas y fuentes, con región, estado y método
  user_providers      "Mis casas": qué casas usa cada usuario de FullTenis
  fixtures_cache      partidos leídos de FullTenis (solo lectura allí)
  provider_event_map  clave de partido -> provider -> evento externo + URL
  validaciones        cada prueba manual o automática de la matriz
  sync_estado         cuándo se sincronizó por última vez y cómo fue
  oddspapi_fixtures   partidos de OddsPapi (para emparejarlos con los de FullTenis)
  oddspapi_enlaces    enlace de cada casa a cada partido (solo el enlace)
  oddspapi_consultas  cuándo se pidieron los enlaces de un partido
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS provider_catalog (
    id                   TEXT PRIMARY KEY,
    nombre               TEXT NOT NULL,
    region               TEXT NOT NULL,         -- CO | US-NC | GLOBAL
    estado               TEXT NOT NULL,         -- ver catalogo.ESTADOS
    metodo               TEXT NOT NULL,         -- oddspapi | opticodds | ninguno
    soporta_deep_link    TEXT NOT NULL DEFAULT 'desconocido',   -- si | no | desconocido
    dominios             TEXT NOT NULL DEFAULT '[]',            -- JSON: dominios que puede abrir
    ultima_verificacion  TEXT,
    nota                 TEXT
);

CREATE TABLE IF NOT EXISTS user_providers (
    usuario_id     TEXT NOT NULL,       -- 'sub' del token de FullTenis
    provider_id    TEXT NOT NULL,
    habilitado     INTEGER NOT NULL DEFAULT 1,
    actualizado_en TEXT NOT NULL,
    PRIMARY KEY (usuario_id, provider_id)
);

-- Clave compuesta: fixture_id + fecha + jugador1 + jugador2 (el fixture_id
-- de FullTenis es un CRC32 y puede chocar). Ver claves.py.
CREATE TABLE IF NOT EXISTS fixtures_cache (
    clave          TEXT PRIMARY KEY,
    fixture_id     TEXT,
    fecha          TEXT NOT NULL,       -- tal cual llega; en ITF puede no traer hora
    hora_conocida  INTEGER NOT NULL,    -- 0 si solo hay día: NO se inventa hora
    jugador1       TEXT NOT NULL,
    jugador2       TEXT NOT NULL,
    torneo         TEXT,
    categoria      TEXT,                -- deducida aquí (categoria.py), no importada
    genero         TEXT,
    superficie     TEXT,
    origen         TEXT NOT NULL,       -- fixtures | en_vivo
    actualizado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fix_fecha ON fixtures_cache(fecha);

CREATE TABLE IF NOT EXISTS provider_event_map (
    clave              TEXT NOT NULL,
    provider_id        TEXT NOT NULL,
    estado             TEXT NOT NULL,   -- ENCONTRADO | NO_ENCONTRADO | AMBIGUO | ...
    external_event_id  TEXT,
    external_url       TEXT,
    confianza          REAL,
    found_at           TEXT NOT NULL,
    verified_at        TEXT,
    PRIMARY KEY (clave, provider_id)
);

CREATE TABLE IF NOT EXISTS validaciones (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_id      TEXT NOT NULL,
    columna          TEXT NOT NULL,     -- deep_link | abre_sin_login | evento_correcto
    resultado        TEXT NOT NULL,     -- ver validacion.RESULTADOS
    clave            TEXT,
    url              TEXT,
    probador         TEXT,
    region_prueba    TEXT,
    navegador_limpio INTEGER NOT NULL DEFAULT 1,
    detalle          TEXT,
    creado_en        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_val_prov ON validaciones(provider_id, columna);

CREATE TABLE IF NOT EXISTS oddspapi_fixtures (
    fixture_id     TEXT PRIMARY KEY,
    dia            TEXT NOT NULL,       -- día UTC de startTime
    inicio         TEXT NOT NULL,       -- startTime tal cual (ISO)
    jugador1       TEXT NOT NULL,
    jugador2       TEXT NOT NULL,
    torneo         TEXT,
    categoria      TEXT,                -- categorySlug de OddsPapi
    torneo_id      TEXT,                -- tournamentId de OddsPapi (para el barrido)
    tiene_cuotas   INTEGER NOT NULL,
    actualizado_en TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_opf_dia ON oddspapi_fixtures(dia);

CREATE TABLE IF NOT EXISTS oddspapi_enlaces (
    fixture_id   TEXT NOT NULL,
    bookmaker    TEXT NOT NULL,         -- clave de la casa en OddsPapi
    url          TEXT NOT NULL,
    obtenido_en  TEXT NOT NULL,
    PRIMARY KEY (fixture_id, bookmaker)
);

CREATE TABLE IF NOT EXISTS oddspapi_consultas (
    fixture_id     TEXT PRIMARY KEY,
    consultado_en  TEXT NOT NULL,
    resultado      TEXT NOT NULL        -- ok | sin_casas | en_vivo_sin_acceso
);

CREATE TABLE IF NOT EXISTS sync_estado (
    clave  TEXT PRIMARY KEY,
    valor  TEXT
);
"""


def conectar(ruta: str | None = None) -> sqlite3.Connection:
    ruta = ruta or config.BUSCADOR_DB_PATH
    Path(ruta).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def inicializar(conn: sqlite3.Connection) -> None:
    conn.executescript(ESQUEMA)
    # Bases creadas antes de 30/09/2026: añadir las columnas nuevas.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(oddspapi_fixtures)")}
    if "torneo_id" not in cols:
        conn.execute("ALTER TABLE oddspapi_fixtures ADD COLUMN torneo_id TEXT")
    conn.commit()
