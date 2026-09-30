# BOT BUSCADOR — Paso a paso para dejarlo funcionando

Orden acordado: **staging primero, producción después**. Dos servicios en
Railway: **RankingFTR** (ya existe) y **BOT_BUSCADOR** (nuevo, región EE. UU.).

---

## 0. Tener a mano (una vez)

1. **Dos secretos nuevos** (en tu ordenador):
   ```
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
   Ejecútalo dos veces y apunta:
   - **A** → `FTR_LECTURA_SECRET` (debe ser distinto de `FTR_INTERNAL_SECRET`)
   - **B** → `BUSCADOR_TOKEN_SECRET`
2. **Claves públicas de FanDuel y BetMGM** (de tus HAR), en la carpeta del BOT:
   ```
   python scripts/sacar_claves.py
   ```
   Quedan en `fanduel_ak.txt` y `betmgm_accessid.txt` (no se suben a GitHub).
3. **Clave de Tailscale**: login.tailscale.com → Settings → Keys →
   Generate auth key → **Reusable** ✅ y **Ephemeral** ✅.
4. **Tu ordenador `danivalero`** encendido, con Tailscale conectado como exit
   node, **sin suspensión y sin la VPN comercial**.

⚠️ Todo lo anterior son secretos: solo en las variables de Railway, nunca en el
chat ni en GitHub.

---

## 1. RankingFTR (staging)

1. Copia los archivos de `RankingFTR_cambios.zip` sobre tu repositorio (mismas
   rutas; son 11 archivos, ver `CAMBIOS-20260928-bot-buscador.md`).
2. Pruebas en tu ordenador:
   ```
   bash tests/correr_todo.sh
   ```
   Todo como antes y `test_buscador_aislado.py` OK. (`test_export_sugerencias.js`
   ya fallaba antes de estos cambios.)
3. Súbelo a una rama (p. ej. `bot-buscador`) que despliegue en tu entorno
   **staging** de Railway.
4. Variables del servicio RankingFTR en **staging**:
   | Variable | Valor |
   | --- | --- |
   | `FTR_LECTURA_SECRET` | A |
   | `BUSCADOR_TOKEN_SECRET` | B |

   Todavía **sin** `BUSCADOR_PUBLIC_URL`: la pestaña dirá "no está disponible
   todavía" y el resto de FullTenis sigue igual.

---

## 2. BOT_BUSCADOR (staging)

1. Crea un repositorio **privado** en GitHub (`BOT_BUSCADOR`) con el contenido
   del ZIP. El `.gitignore` ya excluye bases de datos y claves locales.
2. Railway → tu proyecto → entorno **staging** → **New → GitHub Repo →
   BOT_BUSCADOR**.
3. **Settings → Region: US East** (Virginia). Las casas de EE. UU. solo
   responden desde allí.
4. **Volume**: añade un volumen montado en **`/data`** (ahí vive su base).
5. **Variables**:
   | Variable | Valor |
   | --- | --- |
   | `FTR_SERVICE_URL` | URL pública de RankingFTR staging (`https://…`) |
   | `FTR_LECTURA_SECRET` | A |
   | `BUSCADOR_TOKEN_SECRET` | B |
   | `ALLOWED_ORIGINS` | dominio de RankingFTR staging, exacto, sin `/` final |
   | `BUSCADOR_DB_PATH` | `/data/bot_buscador.db` |
   | `FANDUEL_AK` | contenido de `fanduel_ak.txt` |
   | `BETMGM_ACCESSID` | contenido de `betmgm_accessid.txt` |
   | `TS_AUTHKEY` | clave de Tailscale |
   | `TS_EXIT_NODE` | `danivalero` |
   | `FUENTES_PROXY` | `betano=socks5h://localhost:1055` |
6. **Settings → Networking → Generate Domain** (p. ej.
   `https://bot-buscador-staging.up.railway.app`).
7. Comprueba:
   - Log del despliegue: `[tailscale] conectado; salida por 'danivalero'`.
   - Tailscale → Machines: aparece `bot-buscador`.
   - `https://TU-BOT/salud`: `ok: true`; en unos minutos `fixtures_en_cache` > 0;
     en `fuentes`, cada una con `partidos` y sin `error` (salvo `caesars`);
     `betano` con `"proxy": true`.

---

## 3. Conectar los dos

1. RankingFTR staging → variable **`BUSCADOR_PUBLIC_URL`** = dominio del BOT
   (`https://bot-buscador-staging.up.railway.app`).
2. Entra en RankingFTR staging como **admin** → pestaña **🔎 BOT BUSCADOR**:
   debe cargar sin aviso y mostrar las casas agrupadas por región.

---

## 4. Probar en staging (`STAGING.md`)

- Los **8 escenarios** (funcionando, apagado, lento, timeout, error 500, CORS,
  fuente caída, una casa fallando) con `MODO_PRUEBA`, y dejarlo **vacío** al terminar.
- **T1–T5** de Betano por Tailscale (incluido apagar `danivalero`: Betano va al
  respaldo y el resto sigue).
- Un **usuario en Colombia** y otro **en EE. UU.**: elegir casas → partido en
  juego → ABRIR → cada pestaña abre el partido; «📋 Copiar enlaces» funciona.

---

## 5. Producción

1. Cuando staging esté bien: fusiona la rama en `main` (RankingFTR).
2. Crea el servicio BOT_BUSCADOR en el entorno **production** igual que en el
   paso 2 (región US East, volumen `/data`), con **secretos nuevos** A y B
   propios de producción y `ALLOWED_ORIGINS` = dominio de producción.
3. RankingFTR producción: `FTR_LECTURA_SECRET`, `BUSCADOR_TOKEN_SECRET` y
   `BUSCADOR_PUBLIC_URL` (dominio del BOT de producción).
4. **Cómo abrir** (lo elige cada usuario en la pestaña, se guarda en su
   ordenador): 📑 todas a la vez (por defecto), 🪟 cuadrícula o 👆 una a una. Para varios monitores: Chrome o
   Edge y pulsar «Detectar pantallas» → **Permitir**. Probar antes en cada equipo
   con `python scripts/diagnostico_ventanas.py` (Windows y Mac).
5. La pestaña es **solo para admin** de fábrica. Para otros roles: panel de
   administración → permisos → `ver_tab_buscador`.

---

## 6. Mantenimiento

| Situación | Qué pasa | Qué hacer |
| --- | --- | --- |
| `danivalero` apagado o con VPN comercial | Betano va al respaldo; el resto igual | Encenderlo / apagar la VPN |
| Clave de Tailscale caducada | Solo afecta a despliegues nuevos | Generar otra y cambiar `TS_AUTHKEY` |
| Una casa da error en `/salud` | Esa casa va al respaldo | DraftKings: subir `DK_CLIENT_VERSION`. FanDuel/BetMGM: nueva captura HAR + `sacar_claves.py` y actualizar la variable |
| Quieres Betano sin depender del ordenador | — | Proxy residencial de pago: solo cambia `FUENTES_PROXY` |
| Probar cambios en local | — | `python scripts/verificar_todo.py --rankingftr RUTA` y el simulador |

Resultado esperado: **10 casas con enlace directo** (BetPlay, Rushbet, Wplay,
Bwin, Betano, DraftKings, FanDuel, BetMGM, Kalshi, Polymarket), el resto con
respaldo (sección de tenis + apellido copiado). Coste en fuentes: **0 $**.
