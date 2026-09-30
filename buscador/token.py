"""
buscador/token.py — Verificación del token corto que emite FullTenis.

Formato: JWT estándar HS256 (header.payload.firma en base64url), sin librería
externa: son 30 líneas y así no hay dependencia que actualizar.

Claims obligatorios:
  sub      id de usuario de FullTenis (texto)
  usuario  nombre de la cuenta
  rol      rol en FullTenis (informativo; el buscador no da permisos de FTR)
  aud      "bot_buscador"
  iat      emitido (epoch s)
  exp      caduca (epoch s) — FullTenis lo emite a 10 minutos

FullTenis firma con BUSCADOR_TOKEN_SECRET y este servicio verifica con la
misma clave. La cookie de sesión de FullTenis nunca llega aquí.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

MARGEN_RELOJ_S = 30          # tolerancia entre relojes de los dos servicios
VIDA_MAXIMA_S = 15 * 60      # ningún token vale más de esto, diga lo que diga exp


class TokenInvalido(Exception):
    pass


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def emitir(secreto: str, sub: str, usuario: str, rol: str, aud: str = "bot_buscador",
           vida_s: int = 600, ahora: int | None = None) -> str:
    """Solo para pruebas. En producción el token lo emite FullTenis."""
    ahora = int(time.time()) if ahora is None else ahora
    cab = _b64e(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    carga = _b64e(json.dumps({"sub": str(sub), "usuario": usuario, "rol": rol, "aud": aud,
                              "iat": ahora, "exp": ahora + vida_s},
                             separators=(",", ":")).encode())
    firma = hmac.new(secreto.encode(), f"{cab}.{carga}".encode(), hashlib.sha256).digest()
    return f"{cab}.{carga}.{_b64e(firma)}"


def verificar(token: str, secreto: str, audiencia: str, ahora: int | None = None) -> dict:
    if not secreto:
        raise TokenInvalido("servicio sin BUSCADOR_TOKEN_SECRET")
    try:
        cab_b, carga_b, firma_b = token.split(".")
        cab = json.loads(_b64d(cab_b))
        carga = json.loads(_b64d(carga_b))
        firma = _b64d(firma_b)
    except Exception:
        raise TokenInvalido("formato")
    if cab.get("alg") != "HS256":
        raise TokenInvalido("algoritmo")          # nada de "none" ni otros
    esperada = hmac.new(secreto.encode(), f"{cab_b}.{carga_b}".encode(),
                        hashlib.sha256).digest()
    if not hmac.compare_digest(firma, esperada):
        raise TokenInvalido("firma")
    ahora = int(time.time()) if ahora is None else ahora
    try:
        iat, exp = int(carga["iat"]), int(carga["exp"])
    except (KeyError, TypeError, ValueError):
        raise TokenInvalido("iat/exp")
    if carga.get("aud") != audiencia:
        raise TokenInvalido("audiencia")
    if exp < ahora - MARGEN_RELOJ_S:
        raise TokenInvalido("caducado")
    if iat > ahora + MARGEN_RELOJ_S:
        raise TokenInvalido("emitido en el futuro")
    if exp - iat > VIDA_MAXIMA_S:
        raise TokenInvalido("vida demasiado larga")
    if not str(carga.get("sub", "")).strip():
        raise TokenInvalido("sin sub")
    return carga
