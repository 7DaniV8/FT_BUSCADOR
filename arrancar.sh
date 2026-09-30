#!/bin/sh
# arrancar.sh — Arranque del BOT en Railway.
#
# Si hay TS_AUTHKEY, conecta Tailscale en modo "userspace" (no toca la red del
# contenedor) y ofrece un proxy SOCKS5 en localhost:1055 que sale a internet por
# el aparato de TS_EXIT_NODE (p. ej. un ordenador en Colombia). Solo las fuentes
# de FUENTES_PROXY lo usan (betano=socks5h://localhost:1055); el resto sale
# directamente desde Railway.
#
# Dos pasos (30/09/2026): primero se CONECTA y después se fija la SALIDA. En el
# primer arranque Tailscale todavía no conoce los aparatos de la red, así que
# pedir la salida en la misma orden hacía fallar la conexión entera.
#
# Si Tailscale falla, el BOT arranca IGUAL: Betano pasa al respaldo y lo dice /salud.

TS="tailscale --socket=/tmp/tailscale/tailscaled.sock"

if [ -n "$TS_AUTHKEY" ]; then
  if command -v tailscaled >/dev/null 2>&1; then
    mkdir -p /tmp/tailscale
    tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
               --state=mem: --socket=/tmp/tailscale/tailscaled.sock \
               >/tmp/tailscale/tailscaled.log 2>&1 &
    sleep 3
    # 1) Conectarse a la red
    if $TS up --authkey="$TS_AUTHKEY" --hostname="${TS_HOSTNAME:-bot-buscador}" \
              --accept-dns=false --timeout=45s >/tmp/tailscale/up.log 2>&1; then
      echo "[tailscale] conectado a la red como '${TS_HOSTNAME:-bot-buscador}'"
      # 2) Fijar la salida (con reintentos: la lista de aparatos tarda un poco)
      if [ -n "$TS_EXIT_NODE" ]; then
        ok=0
        for intento in 1 2 3 4 5 6 7 8; do
          if $TS set --exit-node="$TS_EXIT_NODE" >/tmp/tailscale/exit.log 2>&1; then ok=1; break; fi
          sleep 5
        done
        if [ "$ok" = 1 ]; then
          echo "[tailscale] salida por '${TS_EXIT_NODE}' en socks5h://localhost:1055"
        else
          echo "[tailscale] NO se pudo usar '${TS_EXIT_NODE}' como salida: $(tail -3 /tmp/tailscale/exit.log | tr '\n' ' ')"
          echo "[tailscale] revisa que '${TS_EXIT_NODE}' esté encendido, con 'Run exit node' y aprobado como Exit Node"
        fi
      fi
    else
      echo "[tailscale] NO se pudo conectar: $(tail -3 /tmp/tailscale/up.log | tr '\n' ' ')"
      echo "[tailscale] (tailscaled) $(tail -3 /tmp/tailscale/tailscaled.log | tr '\n' ' ')"
      echo "[tailscale] las fuentes con proxy irán al respaldo"
    fi
  else
    echo "[tailscale] no está instalado en la imagen: las fuentes con proxy irán al respaldo"
  fi
fi

exec uvicorn buscador.app:app --host 0.0.0.0 --port "${PORT:-8080}"
