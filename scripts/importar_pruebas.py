#!/usr/bin/env python3
"""
scripts/importar_pruebas.py — Pasa a la matriz las pruebas manuales de un CSV.

    python scripts/importar_pruebas.py enlaces_para_probar.csv
    python scripts/importar_pruebas.py enlaces_para_probar.csv --dry-run

Cada fila rellenada genera hasta tres pruebas INDEPENDIENTES (deep link, abre
sin login, evento correcto). Las celdas vacías no cuentan. Una fila con
navegador_limpio = "no" se guarda pero no entra en ABRE SIN LOGIN.
Al final imprime la matriz recalculada de cada provider tocado.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from buscador import catalogo, db, validacion  # noqa: E402

MAPA = {"deep_link": "deep_link (ok/fallo)",
        "abre_sin_login": "abre_sin_login (abrio/pidio_login/pidio_ubicacion/no_cargo)",
        "evento_correcto": "evento_correcto (ok/fallo)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    conn = db.conectar()
    db.inicializar(conn)
    catalogo.sembrar(conn)
    tocados, n, malos = set(), 0, []
    with open(args.csv, encoding="utf-8") as fh:
        for i, fila in enumerate(csv.DictReader(fh), start=2):
            pid = (fila.get("provider") or "").strip()
            if not catalogo.obtener(conn, pid):
                malos.append(f"línea {i}: provider '{pid}' desconocido")
                continue
            limpio = (fila.get("navegador_limpio (si/no)") or "si").strip().lower() != "no"
            for col, cab in MAPA.items():
                res = (fila.get(cab) or "").strip().lower()
                if not res:
                    continue
                if res not in validacion.RESULTADOS[col]:
                    malos.append(f"línea {i}: '{res}' no vale para {col}")
                    continue
                if not args.dry_run:
                    validacion.registrar(conn, pid, col, res, fila.get("clave"), fila.get("url"),
                                         probador=fila.get("probador", ""),
                                         region_prueba=fila.get("region_prueba", ""),
                                         navegador_limpio=limpio, detalle=fila.get("notas", ""))
                n += 1
                tocados.add(pid)
    print(f"{n} pruebas {'válidas (dry-run, nada guardado)' if args.dry_run else 'guardadas'}")
    for m in malos:
        print("  ⚠️ " + m)
    for pid in sorted(tocados):
        m = validacion.matriz_provider(conn, pid)
        print(f"\n{pid}")
        for col in validacion.COLUMNAS:
            print(f"  {col:<16} {m[col]['icono']} {m[col]['estado']:<13} {m[col]['texto']}")
        if m["abre_sin_login"].get("descartadas_perfil_no_limpio"):
            print(f"  ({m['abre_sin_login']['descartadas_perfil_no_limpio']} pruebas con perfil "
                  f"no limpio fuera del cálculo)")


if __name__ == "__main__":
    main()
