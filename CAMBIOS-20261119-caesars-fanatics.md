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
