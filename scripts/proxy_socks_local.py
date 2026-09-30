#!/usr/bin/env python3
"""
scripts/proxy_socks_local.py — Proxy SOCKS5 mínimo para PRUEBAS en tu ordenador.

Hace lo mismo que el proxy que dará Tailscale (socks5://localhost:1055): recibe
las peticiones y las saca por la conexión de este ordenador. Sirve para
comprobar que el BOT sabe leer Betano a través de un proxy.

    python scripts/proxy_socks_local.py            (escucha en 127.0.0.1:1080)
    python scripts/proxy_socks_local.py --puerto 1081

Solo escucha en 127.0.0.1 (nadie de fuera puede usarlo). Muestra cada
conexión que pasa por él. Ctrl+C para parar. Solo Python estándar.
"""
import argparse
import asyncio
import ipaddress
import struct

ap = argparse.ArgumentParser()
ap.add_argument("--puerto", type=int, default=1080)
A = ap.parse_args()


async def tubo(origen, destino):
    try:
        while datos := await origen.read(65536):
            destino.write(datos)
            await destino.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        try:
            destino.close()
        except Exception:
            pass


async def cliente(r: asyncio.StreamReader, w: asyncio.StreamWriter):
    try:
        ver, n = await r.readexactly(2)
        await r.readexactly(n)                          # métodos ofrecidos
        if ver != 5:
            w.close()
            return
        w.write(b"\x05\x00")                            # sin usuario ni clave
        await w.drain()
        ver, cmd, _, tipo = await r.readexactly(4)
        if tipo == 1:
            host = str(ipaddress.IPv4Address(await r.readexactly(4)))
        elif tipo == 3:
            host = (await r.readexactly((await r.readexactly(1))[0])).decode()
        elif tipo == 4:
            host = str(ipaddress.IPv6Address(await r.readexactly(16)))
        else:
            w.close()
            return
        (puerto,) = struct.unpack(">H", await r.readexactly(2))
        if cmd != 1:                                    # solo CONNECT
            w.write(b"\x05\x07\x00\x01" + b"\x00" * 6)
            await w.drain()
            w.close()
            return
        try:
            dr, dw = await asyncio.wait_for(asyncio.open_connection(host, puerto), 15)
        except Exception as e:
            print(f"  ✗ {host}:{puerto}  ({type(e).__name__})")
            w.write(b"\x05\x05\x00\x01" + b"\x00" * 6)
            await w.drain()
            w.close()
            return
        print(f"  → {host}:{puerto}")
        w.write(b"\x05\x00\x00\x01" + b"\x00" * 6)
        await w.drain()
        await asyncio.gather(tubo(r, dw), tubo(dr, w))
    except (asyncio.IncompleteReadError, ConnectionError, OSError):
        try:
            w.close()
        except Exception:
            pass


async def main():
    srv = await asyncio.start_server(cliente, "127.0.0.1", A.puerto)
    print(f"Proxy SOCKS5 escuchando en socks5://127.0.0.1:{A.puerto}  (Ctrl+C para parar)")
    print("Cada conexión que pase por aquí aparecerá abajo:\n")
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProxy parado.")
