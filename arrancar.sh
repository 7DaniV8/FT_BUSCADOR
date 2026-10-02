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

TS_BIN=""

if [ -n "$TS_AUTHKEY" ]; then
  # Versión ACTUAL de Tailscale (02/10/2026): la de la imagen de Railway es la
  # 1.76 y el aparato de salida va por la 1.102; con la 1.76 la salida no
  # funcionaba aunque hubiera conexión. Se descarga la última oficial; si falla,
  # se usa la de la imagen y el BOT arranca igual.
  mkdir -p /tmp/tailscale /tmp/ts-reciente
  if python3 - /tmp/ts-reciente >/tmp/tailscale/version.txt 2>/tmp/tailscale/descarga.log <<'PY'
import io, json, os, sys, tarfile
import httpx
dest = sys.argv[1]
info = httpx.get("https://pkgs.tailscale.com/stable/?mode=json", timeout=20).json()
nombre = info["Tarballs"]["amd64"]
datos = httpx.get("https://pkgs.tailscale.com/stable/" + nombre, timeout=90, follow_redirects=True).content
n = 0
with tarfile.open(fileobj=io.BytesIO(datos), mode="r:gz") as t:
    for m in t.getmembers():
        base = os.path.basename(m.name)
        if m.isfile() and base in ("tailscale", "tailscaled"):
            ruta = os.path.join(dest, base)
            with open(ruta, "wb") as f:
                f.write(t.extractfile(m).read())
            os.chmod(ruta, 0o755)
            n += 1
if n != 2:
    sys.exit(1)
print(info.get("TarballsVersion", "?"))
PY
  then
    TS_BIN="/tmp/ts-reciente/"
    echo "[tailscale] usando la versión $(cat /tmp/tailscale/version.txt) (descargada)"
  else
    echo "[tailscale] no se pudo descargar la versión actual ($(tail -1 /tmp/tailscale/descarga.log)): se usa la de la imagen"
  fi
fi

TS="${TS_BIN}tailscale --socket=/tmp/tailscale/tailscaled.sock"

if [ -n "$TS_AUTHKEY" ]; then
  if [ -n "$TS_BIN" ] || command -v tailscaled >/dev/null 2>&1; then
    mkdir -p /tmp/tailscale
    ${TS_BIN}tailscaled --tun=userspace-networking --socks5-server=localhost:1055 \
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
          # Diagnóstico (01/10/2026): ¿responde el aparato de salida y por qué vía?
          if $TS ping -c 1 --timeout=10s "$TS_EXIT_NODE" >/tmp/tailscale/ping.log 2>&1; then
            echo "[tailscale] ping a '${TS_EXIT_NODE}': $(tail -1 /tmp/tailscale/ping.log)"
          else
            echo "[tailscale] '${TS_EXIT_NODE}' NO responde al ping: $(tail -1 /tmp/tailscale/ping.log)"
          fi
          echo "[tailscale] estado: $($TS status 2>/dev/null | grep -i "$TS_EXIT_NODE" | head -1)"
          # Vigilancia (01/10/2026): cada 5 min se PRUEBA la salida de verdad
          # (ipinfo.io a través del proxy). Medido en producción: si el BOT arranca
          # con el aparato apagado, la salida se queda atascada aunque luego vuelva.
          # Si la prueba falla, se reinicia la salida (quitar y volver a poner).
          (
            sleep 120
            while true; do
              # Se prueban las dos formas: socks5h (el aparato de salida resuelve los
              # nombres) y socks5 (los resuelve el BOT). Medido el 02/10/2026: con
              # conexión directa y "exit node" activo, socks5h daba ConnectTimeout.
              RES=$(python3 -c "
import httpx
r = {}
for modo in ('socks5h', 'socks5'):
    try:
        r[modo] = httpx.get('https://ipinfo.io/json', proxy=modo + '://localhost:1055', timeout=20).json().get('country', '?')
    except Exception as e:
        r[modo] = 'error:' + type(e).__name__
print(r['socks5h'] + ' ' + r['socks5'])
" 2>/dev/null)
              H_RES=${RES%% *}; S_RES=${RES##* }
              if [ "$RES" != "$ULTIMO_RES" ]; then
                echo "[tailscale] prueba de salida → socks5h: ${H_RES:-?} | socks5: ${S_RES:-?}"
                ULTIMO_RES="$RES"
              fi
              case "$S_RES" in error:*|"") PAIS="$H_RES" ;; *) PAIS="$S_RES" ;; esac
              case "$PAIS" in
                error:*|"")
                  echo "[tailscale] la salida por '${TS_EXIT_NODE}' no funciona (${PAIS:-sin respuesta}): reiniciándola"
                  $TS set --exit-node= >/dev/null 2>&1
                  sleep 3
                  $TS set --exit-node="$TS_EXIT_NODE" >/tmp/tailscale/exit.log 2>&1 \
                    || echo "[tailscale] no se pudo volver a fijar: $(tail -1 /tmp/tailscale/exit.log)"
                  if ! $TS ping -c 1 --timeout=10s "$TS_EXIT_NODE" >/tmp/tailscale/ping.log 2>&1; then
                    echo "[tailscale] '${TS_EXIT_NODE}' NO responde al ping: $(tail -1 /tmp/tailscale/ping.log)"
                  fi
                  ;;
                *)
                  [ -n "$AVISADO_OK" ] || echo "[tailscale] salida comprobada: sale por $PAIS"
                  AVISADO_OK=1
                  ;;
              esac
              sleep 300
            done
          ) &
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
