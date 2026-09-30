# Prueba definitiva en staging antes de producción

Orden acordado: 1) BOT_BUSCADOR independiente · 2) `FTR_LECTURA_SECRET` ·
3) integración mínima visual en staging · 4) pruebas de aislamiento ·
5) solo después, producción.

## Preparación

1. En Railway, un **entorno de staging** con:
   - una copia de RankingFTR con los cambios, apuntando a una **copia** de la
     base (nunca la de producción);
   - el servicio BOT_BUSCADOR, con su propio volumen.
2. Variables en **RankingFTR (staging)**:
   - `FTR_LECTURA_SECRET` = un valor nuevo, distinto de `FTR_INTERNAL_SECRET`
   - `BUSCADOR_PUBLIC_URL` = `https://<dominio-del-buscador-de-staging>`
   - `BUSCADOR_TOKEN_SECRET` = un valor nuevo (16+ caracteres)
3. Variables en **BOT_BUSCADOR (staging)**: `FTR_SERVICE_URL` (el RankingFTR de
   staging), el mismo `FTR_LECTURA_SECRET`, el mismo `BUSCADOR_TOKEN_SECRET`,
   `ALLOWED_ORIGINS` (el dominio del RankingFTR de staging), `FANDUEL_AK`,
   `MODO_PRUEBA` vacío. **Región del servicio: EE. UU.** (las casas de EE. UU.
   solo responden desde allí). En `/salud`, cada fuente debe mostrar partidos y
   ningún error al poco de arrancar.
4. En RankingFTR de staging: `bash tests/correr_todo.sh`. Debe salir igual que
   antes de los cambios más la suite nueva en verde. La única suite que falla,
   y ya fallaba antes, es `test_export_sugerencias.js`.

## Escenarios

En **cada** escenario, además del resultado del buscador, se comprueba que
siguen funcionando con normalidad: **LIVE, PRE, rankings, FTR, Elo, MatchUp,
alertas, Discord/Telegram y FT Intelligence**. La casilla solo se marca si todo
eso sigue bien.

| # | Escenario | Cómo se provoca | Qué debe verse en 🔎 BOT BUSCADOR | Resto de FullTenis |
| --- | --- | --- | --- | --- |
| 1 | Funcionando | Todo normal | Busca un partido de hoy, Mis casas (BetPlay, Rushbet), ABRIR abre las casas en ese partido | ☐ igual |
| 2 | Completamente apagado | Parar el servicio BOT_BUSCADOR | "temporalmente no disponible" | ☐ igual |
| 3 | Lento | `MODO_PRUEBA=lento` | Aviso tras ~4 s (tiempo máximo del navegador) | ☐ igual, sin esperas |
| 4 | Timeout de una fuente | `TIMEOUT_PROVIDER_S=1` (o red cortada a una casa) | Esa casa ⛔ ERROR, sin colgarse; las demás normales | ☐ igual |
| 5 | Error 500 | `MODO_PRUEBA=error500` | "temporalmente no disponible" | ☐ igual |
| 6 | CORS incorrecto | `ALLOWED_ORIGINS` con otro dominio | "temporalmente no disponible" | ☐ igual |
| 7 | Una fuente caída | `MODO_PRUEBA=fuente_caida:kambi` | BetPlay y Rushbet ⛔ ERROR; FanDuel/DraftKings/Caesars normales | ☐ igual |
| 8 | Una casa fallando | `MODO_PRUEBA=casa_falla:betplay_co` | BetPlay ⛔ ERROR, Rushbet normal | ☐ igual |

Extra, antes de producción:

- ☐ Con `BUSCADOR_PUBLIC_URL` vacía en RankingFTR: la cabecera CSP es idéntica a
  la de producción actual y la pestaña dice "no está disponible todavía".
- ☐ Un usuario con rol `lectura` no ve la pestaña ni obtiene token (403).
- ☐ `curl -H "X-FTR-Lectura-Secret: <valor>" https://<ftr>/ft-intel/padron` → 403.
- ☐ Los logs de RankingFTR no muestran ninguna petición hacia el dominio del
  buscador (RankingFTR nunca lo llama).

## Paso a producción

Solo con todas las casillas marcadas. En producción, `MODO_PRUEBA` vacío y
`ver_tab_buscador` solo para admin (piloto). Abrirlo a otros roles se hace
desde Admin → Permisos, sin deploy.

## Retirada

Para quitar el buscador: vaciar `BUSCADOR_PUBLIC_URL` (efecto inmediato en la
CSP y la pestaña al reiniciar), o retirar los permisos desde el panel. Para
borrarlo del todo: eliminar los 4 archivos nuevos de RankingFTR y deshacer las
líneas marcadas "BOT BUSCADOR (28/09/2026)" en `app.py`, `deps.py`,
`routes_ft_intel.py`, `permisos.py` y `research.html`.

## Betano por Tailscale (staging)

Con `TS_AUTHKEY`, `TS_EXIT_NODE` y `FUENTES_PROXY=betano=socks5h://localhost:1055`
(ver README):

| # | Prueba | Esperado | Resultado |
| --- | --- | --- | --- |
| T1 | Desplegar | Log: `[tailscale] conectado`; en Tailscale → Machines aparece `bot-buscador` | ☐ |
| T2 | `/salud` | `fuentes.betano`: partidos > 0, `proxy: true`, sin error | ☐ |
| T3 | Buscar un partido de tenis en vivo con Betano marcado | Betano ✅ y el enlace abre el partido (desde Colombia) | ☐ |
| T4 | Apagar el aparato de salida | Betano ⛔/respaldo; el resto de casas siguen ✅ | ☐ |
| T5 | Encender el aparato | Betano vuelve solo en la siguiente lectura | ☐ |

