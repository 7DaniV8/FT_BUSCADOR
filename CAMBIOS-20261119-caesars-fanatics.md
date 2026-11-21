# Caesars y Fanatics en el Bot Buscador — 19/11/2026

**Caesars Sportsbook**
- Deja de estar oculta (CASAS_OCULTAS por defecto = `bet365_nc`).
- Se lee con la huella de Chrome (FUENTES_IMITAR_CHROME por defecto = `betmgm,betano,caesars`).
- Si la casa aún bloquea: su fila ofrece su sección de tenis con el apellido copiado (no abre ventana vacía).
- ⚠️ Si en Railway las variables `CASAS_OCULTAS` o `FUENTES_IMITAR_CHROME` están puestas a mano, ajustarlas:
  quitar `caesars_nc` de la primera y añadir `caesars` a la segunda.

**Fanatics Sportsbook**
- Solo existe como app (sin web de apuestas). Pasa de PROVIDER_PENDING a TESTING con método `solo_app`:
  se puede marcar en «Mis casas» y su fila dice «📱 solo en la app: ábrela y busca «apellido» (ya está copiado)».
  Nunca abre ventana. La base existente se actualiza sola (migración) si la fila seguía como se sembró.

**Archivos**: FT_BUSCADOR → buscador/config.py, catalogo.py, app.py, tests/test_buscador.py ·
RankingFTR → research/web/static/js/tabs/buscador.js, templates/research.html (versión de caché).
Pruebas: las nuevas pasan; los 2 fallos de DraftKings ya estaban en el ZIP original.

**Partidos movidos de día (Zverev vs Fils, 19/11)**
- La búsqueda tenía tres «Zverev vs Fils» (17, 18 y 19/11): FullTenis movió el partido de día y la fila vieja quedaba.
  Elegir una vieja daba NO ENCONTRADO en casi todas las casas. Ahora, tras cada sincronización, del mismo fixture
  solo queda la fecha que FullTenis mandó por última vez (`sync.quitar_fantasmas`).

**BetRivers (pedido de Rubén, 19/11 noche)**
- BetRivers corre sobre Kambi como Rushbet/BetPlay (misma empresa, RSI): mismo número de evento. Con el 2.º HAR (página de un
  partido) se lee su PROPIA lista en vivo: `eu.offering-api.kambicdn.com/offering/v2018/rsiusil/event/live/open.json?market=US-IL`
  (fuente `kambi_us`), así solo enlaza partidos que BetRivers ofrece. Variables opcionales: KAMBI_US_HOST, KAMBI_US_OPERADOR, KAMBI_US_MERCADO.
- Pasa de «no disponible» a «en prueba» (migración automática). Enlace `https://<estado>.betrivers.com/?page=sportsbook#event/<id>`,
  con el estado que el usuario elige en «Tu estado (EE. UU.)»; sin estado, Illinois.
- Opera (según su propio siteSelect.json, HAR del 19/11) en AZ, CO, IL, IN, IA, LA, MD, MI, NJ, NY, OH, PA, VA, WV. Delaware no tiene web propia: «no disponible». En otro estado (p. ej. NC) dice «no opera en NC» y no abre nada.
- Respaldo: su sección de tenis con el apellido copiado.
