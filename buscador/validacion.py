"""
buscador/validacion.py — Matriz de validación por provider.

Tres columnas COMPLETAMENTE INDEPENDIENTES:
  DEEP LINK        ¿la fuente dio una URL directa del evento?       ok | fallo
  ABRE SIN LOGIN   ¿un navegador limpio, sin sesión previa, lo ve?
                   abrio | pidio_login | pidio_ubicacion | no_cargo  (por separado)
  EVENTO CORRECTO  ¿la URL llevó al partido pedido?                 ok | fallo

Escala (por columna):
  0-2 pruebas          ⚪ SIN DATOS
  3-19 pruebas         🟡 EN PRUEBA   "X/Y correctas · Z%"
  20+ y >= 90 %        ✅ VALIDADO
  20+ y < 90 %         🔴 NO CONFIABLE

ABRE SIN LOGIN solo cuenta pruebas hechas con PERFIL LIMPIO. Una prueba con un
navegador que ya tenía sesión en esa casa daría un falso positivo: se guarda,
pero no entra en el cálculo, y el informe dice cuántas se descartaron.
El estado se CALCULA siempre desde las pruebas; nunca se escribe a mano.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

COLUMNAS = ("deep_link", "abre_sin_login", "evento_correcto")
RESULTADOS = {
    "deep_link": ("ok", "fallo"),
    "abre_sin_login": ("abrio", "pidio_login", "pidio_ubicacion", "no_cargo"),
    "evento_correcto": ("ok", "fallo"),
}
ACIERTO = {"deep_link": "ok", "abre_sin_login": "abrio", "evento_correcto": "ok"}

SIN_DATOS, EN_PRUEBA, VALIDADO, NO_CONFIABLE = (
    "SIN_DATOS", "EN_PRUEBA", "VALIDADO", "NO_CONFIABLE")
ICONO = {SIN_DATOS: "⚪", EN_PRUEBA: "🟡", VALIDADO: "✅", NO_CONFIABLE: "🔴"}


def escala(correctas: int, total: int) -> dict:
    pct = round(100.0 * correctas / total, 1) if total else None
    if total <= 2:
        estado = SIN_DATOS
    elif total <= 19:
        estado = EN_PRUEBA
    elif pct is not None and pct >= 90.0:
        estado = VALIDADO
    else:
        estado = NO_CONFIABLE
    texto = (f"{correctas}/{total} correctas · {pct}%" if total else "sin pruebas")
    return {"estado": estado, "icono": ICONO[estado], "correctas": correctas,
            "total": total, "pct": pct, "texto": texto}


def registrar(conn: sqlite3.Connection, provider_id: str, columna: str, resultado: str,
              clave: str | None = None, url: str | None = None, probador: str = "",
              region_prueba: str = "", navegador_limpio: bool = True,
              detalle: str = "") -> int:
    if columna not in COLUMNAS:
        raise ValueError(f"columna desconocida: {columna}")
    if resultado not in RESULTADOS[columna]:
        raise ValueError(f"resultado '{resultado}' no válido para {columna}")
    cur = conn.execute(
        "INSERT INTO validaciones (provider_id, columna, resultado, clave, url, probador, "
        "region_prueba, navegador_limpio, detalle, creado_en) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (provider_id, columna, resultado, clave, url, probador, region_prueba,
         1 if navegador_limpio else 0, detalle,
         datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    return cur.lastrowid


def matriz_provider(conn: sqlite3.Connection, provider_id: str) -> dict:
    salida = {}
    for col in COLUMNAS:
        filas = conn.execute(
            "SELECT resultado, navegador_limpio FROM validaciones "
            "WHERE provider_id = ? AND columna = ?", (provider_id, col)).fetchall()
        descartadas = 0
        if col == "abre_sin_login":
            descartadas = sum(1 for f in filas if not f["navegador_limpio"])
            filas = [f for f in filas if f["navegador_limpio"]]
        total = len(filas)
        correctas = sum(1 for f in filas if f["resultado"] == ACIERTO[col])
        d = escala(correctas, total)
        d["desglose"] = {r: sum(1 for f in filas if f["resultado"] == r)
                         for r in RESULTADOS[col]}
        if col == "abre_sin_login":
            d["descartadas_perfil_no_limpio"] = descartadas
        salida[col] = d
    return salida


def aviso_apertura(matriz: dict) -> str | None:
    """Si las pruebas limpias muestran que la casa pide login o ubicación para
    ver el evento, se avisa al usuario. FullTenis NO intenta evitarlo."""
    d = matriz.get("abre_sin_login", {}).get("desglose", {})
    total = sum(d.values())
    if total < 3:
        return None
    if d.get("pidio_login", 0) / total >= 0.5:
        return "LOGIN_REQUERIDO"
    if d.get("pidio_ubicacion", 0) / total >= 0.5:
        return "UBICACION_REQUERIDA"
    return None
