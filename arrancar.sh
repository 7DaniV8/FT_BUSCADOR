#!/bin/sh
# arrancar.sh — Arranque del BOT en Railway.
#
# Si hay TS_AUTHKEY, conecta Tailscale en modo "userspace" (no toca la red del
# contenedor) y ofrece un proxy SOCKS5 en localhost:1055 que sale a internet por
# el aparato de TS_EXIT_NODE (p. ej. un ordenador en Colombia). Solo las fuentes
# de FUENTES_PROXY lo usan (betano=socks5h://localhost:1055); el resto sale
# directamente desde Railway.
#
# Si Tailscale falla, el BOT arranca IGUAL: Betano pasa al respaldo y lo dice /salud.

if [ -n "$TS_AUTHKEY" ]; then
  if command -v tailscaled >/dev/null 2>&1; then
    mkdir -p /tmp/tailscale
    tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
               --state=mem: --socket=/tmp/tailscale/tailscaled.sock \
               >/tmp/tailscale/tailscaled.log 2>&1 &
    sleep 3
    if tailscale --socket=/tmp/tailscale/tailscaled.sock up \
         --authkey="$TS_AUTHKEY" \
         --hostname="${TS_HOSTNAME:-bot-buscador}" \
         --exit-node="${TS_EXIT_NODE}" \
         --accept-dns=false --timeout=30s; then
      echo "[tailscale] conectado; salida por '${TS_EXIT_NODE}' en socks5h://localhost:1055"
    else
      echo "[tailscale] NO se pudo conectar: las fuentes con proxy irán al respaldo"
    fi
  else
    echo "[tailscale] no está instalado en la imagen: las fuentes con proxy irán al respaldo"
  fi
fi

exec uvicorn buscador.app:app --host 0.0.0.0 --port "${PORT:-8080}"
