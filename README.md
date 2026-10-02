# BOT_BUSCADOR

Buscador y abridor multiplataforma de eventos de tenis para FullTenis.

**Para el usuario todo es FullTenis. Para la infraestructura, BOT_BUSCADOR es
independiente y desechable.** Si mañana se borra este servicio, RankingFTR
sigue funcionando prácticamente igual que hoy.

```
FULLTENIS → LOCALIZA PARTIDO → OBTIENE URL PÚBLICA → ABRE EVENTO → FIN
```

No apuesta. No inicia sesión, no guarda ni lee cookies o sesiones de ninguna
casa, no selecciona mercados ni cuotas, no toca el betslip ni introduce
cantidades. Si una casa exige login o ubicación para ver el evento, se avisa
(🟡 LOGIN REQUERIDO / 🟡 UBICACIÓN REQUERIDA) y FullTenis termina ahí.

## Reglas definitivas

- RankingFTR nunca llama a BOT_BUSCADOR.
- BOT_BUSCADOR lee partidos de FullTenis solo por `GET /ft-intel/fixtures` y
  `GET /ft-intel/en-vivo`, con `FTR_LECTURA_SECRET` (nunca con
  `FTR_INTERNAL_SECRET`).
- Sincroniza cada 5-10 minutos y después trabaja con su propia caché y base.
- `user_providers` ("Mis casas") y toda la configuración viven solo aquí.
- Ninguna lógica de sportsbooks, OpticOdds ni providers dentro de RankingFTR.
- Ningún proceso de fondo del buscador corre dentro de RankingFTR.

## Variables de entorno

| Variable | Para qué |
| --- | --- |
| `FTR_SERVICE_URL` | URL de FullTenis (RankingFTR) |
| `FTR_LECTURA_SECRET` | Credencial de solo lectura (la misma que en RankingFTR) |
| `BUSCADOR_TOKEN_SECRET` | Verifica el token corto que emite FullTenis (la misma que en RankingFTR, 16+ caracteres) |
| `ALLOWED_ORIGINS` | Dominio de FullTenis para CORS, p. ej. `https://fulltenis.com` |
| `BUSCADOR_DB_PATH` | Base propia, por defecto `/data/bot_buscador.db` (montar un volumen en `/data`) |
| `SYNC_MINUTOS` | 5-10, por defecto 7 |
| `TIMEOUT_PROVIDER_S` | Tiempo máximo por casa, por defecto 6 s |
| `FANDUEL_AK` | Parámetro `_ak` público de la web de FanDuel (sin él, FanDuel queda pendiente) |
| `FUENTES_ESTADO_US` | Estado de EE. UU. para FanDuel y Caesars (por defecto `nc`) |
| `FUENTES_TTL_S` | Cada cuánto se relee cada fuente (por defecto 45 s) |
| `KAMBI_HOST`, `KAMBI_OPERADOR` | Kambi (por defecto `us.offering-api.kambicdn.com`, `betplay`) |
| `CASAS_OCULTAS` | Casas que no aparecen en la pestaña ni se leen. Por defecto `bet365_nc,caesars_nc`. Para recuperar una, quitarla de la lista; para ocultar otra, añadirla |
| `FUENTES_IMITAR_CHROME` | Fuentes que se leen con la huella de conexión de Chrome (`curl_cffi`). Por defecto `betmgm` (solo responde así). Vacío = desactivado |
| `FUENTES_PROXY` | **Secreto.** Proxy por fuente: `betano=http://usuario:clave@host:puerto`. Betano solo responde a IPs colombianas: con el servidor en EE. UU. necesita un proxy RESIDENCIAL en Colombia. Nunca se muestra en logs ni en `/salud` |
| `BETANO_HOST` | Web de Betano de la que se LEE (cualquier país que responda desde el servidor; mismo número de partido en todos) |
| `BETANO_ENLACE_HOST` | Web a la que se ENLAZA (por defecto `www.betano.co`) |
| `BETMGM_ACCESSID` | Código público `x-bwin-accessid` de la web de BetMGM (sin él, BetMGM queda pendiente) |
| `DK_CLIENT_VERSION`, `CAESARS_APP_VERSION` | Versión de web que envían DraftKings y Caesars (actualizar si alguna fuente empieza a fallar) |
| `ODDSPAPI_API_KEY` | **Desactivado** (decisión del 30/09/2026): ninguna casa usa OddsPapi |
| `ODDSPAPI_SYNC_MINUTOS` | Cada cuánto se baja la lista de partidos de OddsPapi (30-720, por defecto 120) |
| `ODDSPAPI_DIAS_ADELANTE` | Días de partidos por delante (0-3, por defecto 1) |
| `ODDSPAPI_REINTENTO_MIN` | Si una casa no traía enlace, cuándo volver a preguntar (por defecto 30) |
| `ODDSPAPI_ESTADO_US` | Estado de EE. UU. para BetMGM (por defecto `nc`) |
| `ODDSPAPI_BARRIDO_HORAS` | **Barrido por torneos** cada N horas (0 = desactivado; recomendado 6-8 con plan de pago) |
| `ODDSPAPI_BARRIDO_VENTANA_H` | Torneos con partidos en las próximas N horas (por defecto 30) |
| `ODDSPAPI_BARRIDO_MAX_PETICIONES` | Tope de peticiones por barrido (por defecto 200) |
| `ODDSPAPI_PRECARGA_MIN` | **Precarga**: pide los enlaces de los partidos que empiezan en los próximos N minutos (0 = desactivada; recomendado 90 con plan de pago) |
| `ODDSPAPI_PRECARGA_CADA_MIN` | Cada cuánto corre la precarga (por defecto 10) |
| `ODDSPAPI_PRECARGA_POR_CICLO` | Máximo de partidos por ciclo (por defecto 30) |
| `ODDSPAPI_PAUSA_MS` | Pausa entre peticiones para no chocar con el límite (por defecto 1500) |
| `OPTICODDS_API_KEY` | Solo cuando exista el trial |
| `MODO_PRUEBA` | **Solo staging**: `lento`, `error500`, `oddspapi_caido`, `opticodds_caido`, `casa_falla:ID` |

## Despliegue (Railway)

Servicio nuevo, repositorio propio, volumen propio en `/data`. `railway.json`
arranca `uvicorn buscador.app:app` con healthcheck en `/salud`.

## API

| Ruta | Qué hace |
| --- | --- |
| `GET /salud` | Vivo, modo de prueba, última sincronización |
| `GET /api/partidos?q=Damm` | Busca en la caché propia |
| `GET /api/catalogo?region=CO` | Casas de una región (+ globales) |
| `GET/PUT /api/mis-casas` | "Mis casas" del usuario del token (solo ACTIVE/TESTING) |
| `GET /api/resolver?clave=&provider=` | Una casa: estado + URL pública |
| `GET /api/matriz?region=CO` | Matriz de validación calculada |
| `POST /api/validaciones` | Registrar una prueba (solo rol admin) |

Todas las `/api/*` exigen `Authorization: Bearer <token de FullTenis>`.

## Estados

- **De provider:** ACTIVE, TESTING, COMING_SOON, NOT_AVAILABLE_REGION,
  MAINTENANCE, DISABLED, PROVIDER_PENDING.
- **De resultado:** ENCONTRADO, NO_ENCONTRADO, AMBIGUO, LOGIN_REQUERIDO,
  UBICACION_REQUERIDA, PROVIDER_PENDING, NO_DISPONIBLE, ERROR.

## Matriz de validación

Tres columnas independientes: DEEP LINK, ABRE SIN LOGIN (abrió / pidió login /
pidió ubicación / no cargó, por separado) y EVENTO CORRECTO. Escala: 0-2 ⚪ SIN
DATOS · 3-19 🟡 EN PRUEBA · 20+ y ≥90 % ✅ VALIDADO · 20+ y <90 % 🔴 NO
CONFIABLE. ABRE SIN LOGIN solo cuenta pruebas con **perfil de navegador
limpio**.

## Enlaces: fuentes gratuitas (principal)

El proyecto NO usa OddsPapi. Cada casa se lee de los datos públicos que usa su
propia web (sin clave, sin cookies, sin sesión), descubiertos con capturas HAR
reales (`buscador/providers/fuentes.py`):

| Fuente | Casas | Qué trae (1 petición) | Enlace |
| --- | --- | --- | --- |
| Kambi | BetPlay, Rushbet | todo el tenis EN VIVO; mismo número para las dos | `#event/<id>` |
| FanDuel | FanDuel | todo el tenis (en vivo y próximo) | `/tennis/<torneo>/<a-v-b>-<id>` |
| DraftKings | DraftKings | todo el tenis EN VIVO | `/event/<seo>/<id>` |
| Caesars | Caesars | calendario de tenis | `/tennis/<id>/<a-vs-b>` |
| Kalshi (API oficial) | Kalshi | eventos abiertos de cada serie de tenis | `/markets/<SERIE>/x/<EVENTO>` |
| BetMGM (Entain) | BetMGM | tenis EN VIVO (deporte 5) | `/en/sports/events/<nombre>-<id>` |
| Polymarket (API oficial) | Polymarket | eventos de tenis abiertos | `/event/<slug>` |
| Betano | Betano CO | partidos en vivo con su deporte + ficha de cada partido de tenis nuevo | `/live/<slug>/<id>/` |
| Wplay | Wplay | barra de partidos en vivo de cualquier página (HTML) | `/es/e/<id>/<slug>` |
| (BetMGM) | Bwin CO | mismo número que BetMGM | `sports.bwin.co/es/sports/eventos/<id>` |

- Caché en memoria de `FUENTES_TTL_S` y relectura en segundo plano. Si un partido
  no está (acaba de empezar tras un MTO), se relee la fuente en ese momento.
- Si una fuente falla un momento se sirve la última lista buena; si la casa la
  bloquea, SOLO esa casa da ERROR.
- Emparejamiento: los dos jugadores, cada uno en su lado, y fecha compatible.
  Dobles fuera (también de la búsqueda). Dos partidos que encajan igual: AMBIGUO.
- Son datos no oficiales: si una casa cambia su web, esa casa cae al respaldo
  hasta adaptar su lector. Las de EE. UU. deben leerse desde un servidor en EE. UU.

Medido con VPN de EE. UU. (30/09/2026): FanDuel ✅, DraftKings ✅ (con los
encabezados de su web), Kalshi ✅ (331 partidos), Caesars ❌ (verificación
antibots que exige un navegador real: respaldo), Polymarket ✅ (64; se
descartan los partidos pasados que siguen abiertos), BetMGM ✅ solo con la
huella de Chrome (`FUENTES_IMITAR_CHROME`; riesgo: la casa no lo permite y puede
bloquear la IP, en cuyo caso cae al respaldo). Claves públicas de FanDuel y
BetMGM: `python scripts/sacar_claves.py` (las saca de tus HAR).
Fanatics no tiene web pública de apuestas (solo app): respaldo.
Betano: medido el 30/09/2026, TODAS sus webs bloquean conexiones de EE. UU.; desde
Colombia responde betano.co con la huella de Chrome (61 partidos de tenis en
vivo). En producción: `FUENTES_PROXY=betano=...` con un proxy residencial en
Colombia (probarlo antes con `probar_betano.py --proxy ... --solo-co`).
Kambi y Wplay responden desde EE. UU. Kalshi está hecho sobre su documentación oficial:
confirmarlo con datos reales (`capturar_fuente.py kalshi`). Codere no pone el partido en la dirección: solo respaldo.

## Betano por Tailscale (salida por Colombia, 0 $)

Betano bloquea todas las conexiones de EE. UU. El servicio (en EE. UU.) lleva
Tailscale dentro (`arrancar.sh`, `nixpacks.toml`) en modo userspace: no toca la
red del contenedor y ofrece un proxy SOCKS5 en `localhost:1055` que sale a
internet por un aparato de Colombia (el "exit node"). Solo Betano lo usa.

1. En el aparato de Colombia: Tailscale → Exit nodes → **Run exit node**. En
   login.tailscale.com → Machines: ⋯ → Edit route settings → **Use as exit node**,
   y ⋯ → **Disable key expiry**. Que no se suspenda.
2. login.tailscale.com → Settings → Keys → **Generate auth key**: Reusable ✅,
   Ephemeral ✅ (cada despliegue entra como aparato temporal y se borra solo).
3. Variables del servicio en Railway:
   - `TS_AUTHKEY` = la clave (secreto)
   - `TS_EXIT_NODE` = nombre del aparato en Tailscale (p. ej. `danivalero`)
   - `FUENTES_PROXY` = `betano=socks5h://localhost:1055`
4. Tras desplegar: el log muestra `[tailscale] conectado`, en Machines aparece
   `bot-buscador`, y `/salud` → `fuentes.betano` con partidos > 0 y `proxy: true`.

Si el aparato se apaga o Tailscale falla, el BOT sigue funcionando y Betano cae
al respaldo. Para cambiar a un proxy de pago basta con cambiar `FUENTES_PROXY`.

## Enlaces: OddsPapi (desactivado, se conserva el código)

BetPlay, Rushbet, DraftKings, FanDuel, BetMGM, Kalshi y Polymarket obtienen el
enlace del partido de OddsPapi (`providers/oddspapi.py`). **Solo el enlace**
(`fixturePath` de cada casa): cuotas, mercados y `betslip` se descartan.

- La lista de partidos de OddsPapi se baja cada `ODDSPAPI_SYNC_MINUTOS`
  (1 petición). Fuera partidos simulados (SRL), dobles y cancelados.
- Un partido de FullTenis se empareja con uno de OddsPapi por los **dos
  jugadores, cada uno en su lado**, y el mismo día (±1).
- Los enlaces de un partido se piden **una vez** (1 petición, solo las casas del
  catálogo) la primera vez que alguien lo abre, y se guardan. Un candado por
  partido evita peticiones repetidas aunque el navegador pida varias casas a la
  vez. Guardados antes de empezar, siguen sirviendo con el partido en juego
  (el plan gratuito no da partidos en vivo).
- **Barrido por torneos** (`ODDSPAPI_BARRIDO_HORAS`), la vía principal: el flujo
  real empieza con un MTO, así que el partido siempre está en juego cuando se
  busca. `/odds-by-tournaments` trae ~50 partidos con enlace por petición (1
  casa, máximo 5 torneos). Un barrido completo cuesta ~casas × torneos/5 (unas 63
  peticiones con 7 casas y 42 torneos) y cubre también los días siguientes.
- **Precarga** (`ODDSPAPI_PRECARGA_MIN`): con el plan gratuito OddsPapi no da
  enlaces de partidos en juego. La precarga pide los enlaces antes de que empiece
  cada partido de FullTenis (ITF sin hora: los de hoy), para que ya estén
  guardados cuando alguien lo abra en vivo. Cuesta 1 petición por partido; si
  OddsPapi responde 429, corta el ciclo y sigue en el siguiente.
- BetMGM: el estado del dominio se cambia a `ODDSPAPI_ESTADO_US`.
- La clave va en la URL de OddsPapi; los logs de `httpx` están silenciados
  para que nunca aparezca.

Casas que siguen pendientes y por qué: ver la nota de cada una en
`buscador/catalogo.py` (resumen: Wplay, YaJuego, Luckia, Rivalo, Sportium,
Zamba, Bingo Casino y Mr. Yoker no están en OddsPapi; Betano, Bwin, Betsson,
Codere y Stake solo traen su web internacional o un enlace roto).

## Trabajo de investigación

```bash
python scripts/explorar.py --desde-fullteni --max 20 --salida informes/   # OddsPapi
# probar el CSV a mano con perfiles limpios y rellenar las columnas
python scripts/importar_pruebas.py informes/enlaces_para_probar.csv
python scripts/medir_feed.py --volcado respuesta_opticodds.json   # durante el trial
```

`datos/matriz_colombia.csv`: CASA | TENIS | DEEP LINK | ABRE SIN LOGIN |
EVENTO CORRECTO | COBERTURA por categoría, para rellenar desde Colombia.

## Pruebas

```bash
pip install -r requirements.txt
python tests/test_buscador.py
```

Antes de subir (navegador real, pestaña real, OddsPapi simulado; no gasta
peticiones ni toca Railway):

```bash
pip install playwright && python -m playwright install chromium
python scripts/verificar_todo.py --rankingftr RUTA_A_RANKINGFTR
```

En local con OddsPapi real: `scripts/probar_local.py` (enlaces en pantalla) y
`scripts/simular_fulltenis.py` (FullTenis simulado con la pestaña real).

## Distribución de ventanas (pestaña: «Cómo abrir»)

Motor: `scripts/simulador/ventanas.js` (cuadrícula adaptable sin huecos y
reparto por pantallas; pruebas: `node tests/test_ventanas.js`). Diagnóstico
para Windows y Mac: `python scripts/diagnostico_ventanas.py`.
Reglas del navegador (medidas en Chromium real): una ventana solo se puede
colocar mientras está vacía, antes de cargar la casa; varios monitores solo en
Chrome/Edge con el permiso "gestión de ventanas". Solo actúa sobre las ventanas
que abre el propio buscador. El usuario elige en la pestaña: 📑 todas a la vez
(por defecto: una pestaña por casa, sin colocar), 🪟 cuadrícula (colocadas
según los enlaces encontrados) o 👆 una a una (un botón «Abrir» por casa). Se
guarda en ese ordenador.

