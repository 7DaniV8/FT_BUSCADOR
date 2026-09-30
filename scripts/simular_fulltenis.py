#!/usr/bin/env python3
"""
scripts/simular_fulltenis.py — FullTenis simulado + BOT_BUSCADOR, en local.

Levanta DOS servidores, como en producción:
  FullTenis (simulado)  http://127.0.0.1:8000   la pestaña 🔎 BOT BUSCADOR REAL
                                                (buscador.html y buscador.js de
                                                RankingFTR, sin cambios) y
                                                /api/buscador/token
  BOT_BUSCADOR (real)   http://127.0.0.1:8765   el servicio, con CORS solo para
                                                el origen de FullTenis

Los "partidos de FullTenis" se simulan con los partidos de OddsPapi de las
próximas horas (nombres en formato "Nombre Apellido"). Todo lo demás es el
código real: búsqueda, Mis casas, resolver, enlaces, dominios, ventanas.

Uso (desde la raíz de BOT_BUSCADOR):
    python scripts/simular_fulltenis.py TU_CLAVE_ODDSPAPI
    python scripts/simular_fulltenis.py TU_CLAVE --horas 48
Parar: Ctrl+C.

Gasto en OddsPapi: 1 petición al arrancar + 1 por cada partido que abras
(los enlaces quedan guardados en simulador.db).
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
DIR_SIM = Path(__file__).resolve().parent / "simulador"

def _clave_local(archivo: str) -> str:
    f = Path(__file__).resolve().parent.parent / archivo
    return f.read_text(encoding="utf-8").strip() if f.exists() else ""


def _ak_local() -> str:
    return _clave_local("fanduel_ak.txt")


# Claves públicas guardadas por scripts/sacar_claves.py (si no vienen por variable)
if not os.getenv("BETMGM_ACCESSID") and _clave_local("betmgm_accessid.txt"):
    os.environ["BETMGM_ACCESSID"] = _clave_local("betmgm_accessid.txt")


ap = argparse.ArgumentParser()
ap.add_argument("clave", nargs="?", default="",
                help="(opcional) clave de OddsPapi. Sin ella se usan SOLO las fuentes gratuitas")
ap.add_argument("--fanduel-ak", default=os.getenv("FANDUEL_AK", "") or _ak_local(),
                help="parámetro _ak de la web de FanDuel (sin él, FanDuel queda pendiente)")
ap.add_argument("--horas", type=int, default=30, help="partidos de las próximas N horas")
ap.add_argument("--horas-atras", type=int, default=12,
                help="partidos que empezaron hace hasta N horas (en juego o recién acabados)")
ap.add_argument("--puerto-ft", type=int, default=8000)
ap.add_argument("--puerto-bot", type=int, default=8765)
ap.add_argument("--db", default=str(RAIZ / "simulador.db"))
ap.add_argument("--precarga", type=int, default=0, metavar="MIN",
                help="pide los enlaces de los partidos que empiezan en los próximos MIN minutos "
                     "(1 petición por partido: gasta cupo de OddsPapi)")
ap.add_argument("--barrido", action="store_true",
                help="al arrancar, BARRIDO POR TORNEOS: enlaces de todos los partidos de las "
                     "próximas 30 h (1 petición por casa y lote de 5 torneos)")
ap.add_argument("--barrido-max", type=int, default=70,
                help="máximo de peticiones del barrido (protege el cupo)")
ap.add_argument("--precarga-max", type=int, default=10,
                help="máximo de partidos por ciclo de precarga (cada 10 min)")
A = ap.parse_args()

ORIGEN_FT = f"http://127.0.0.1:{A.puerto_ft}"
URL_BOT = f"http://127.0.0.1:{A.puerto_bot}"
SECRETO = "solo-para-el-simulador-local"
if (A.barrido or A.precarga) and not A.clave:
    sys.exit("--barrido y --precarga son de OddsPapi: necesitan su clave.")
os.environ.update({
    "ODDSPAPI_API_KEY": A.clave or "",
    "FANDUEL_AK": A.fanduel_ak or "",
    "BUSCADOR_DB_PATH": A.db,
    "BUSCADOR_TOKEN_SECRET": SECRETO,
    "ALLOWED_ORIGINS": ORIGEN_FT,
    "SYNC_ACTIVO": "0",                 # no hay FullTenis real al que llamar
    "FTR_SERVICE_URL": "http://127.0.0.1:1",
    "FTR_LECTURA_SECRET": "no-se-usa",
})

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse, Response  # noqa: E402

from buscador import app as bot, catalogo, db, sync  # noqa: E402
from buscador.claves import normalizar  # noqa: E402
from buscador.providers import ODDSPAPI  # noqa: E402
from buscador.providers.oddspapi import CASAS, SinAccesoEnVivo, emparejar  # noqa: E402
from buscador.resolver import ENCONTRADO, Partido  # noqa: E402
from buscador.token import emitir  # noqa: E402

# ── Colombia EN PRUEBA (solo simulador) ──────────────────────────────────
# OddsPapi trae estas casas con su web de OTRO país. Si la casa usa el mismo
# número de partido en todos sus países, basta con cambiar el dominio. Cada
# formato es una hipótesis hasta que se marque como que funciona.
EXPERIMENTALES = [
    # id, nombre visible, casa en OddsPapi, cómo sacar el número, enlace colombiano
    ("betano_co_cuotas", "Betano · cuotas-de-partido", "betano", r"/(\d{6,})/?(?:[?#].*)?$",
     "https://www.betano.co/cuotas-de-partido/e-e/{id}/"),
    ("betano_co_live", "Betano · live", "betano", r"/(\d{6,})/?(?:[?#].*)?$",
     "https://www.betano.co/live/e-e/{id}/"),
    ("bwin_co_es", "Bwin · es/eventos", "bwin", r"/events/(\d+)",
     "https://sports.bwin.co/es/sports/eventos/{id}"),
    ("bwin_co_en", "Bwin · en/events", "bwin", r"/events/(\d+)",
     "https://sports.bwin.co/en/sports/events/{id}"),
    ("stake_co_es", "Stake · es/deportes", "stake", r"/sports/(.+)$",
     "https://stake.com.co/es/deportes/{id}"),
    ("stake_co_sports", "Stake · sports", "stake", r"/sports/(.+)$",
     "https://stake.com.co/sports/{id}"),
    ("codere_co_a", "Codere · apuestas-deportivas", "codere.es", r"eventId=(\d+)",
     "https://www.codere.com.co/apuestas-deportivas?eventId={id}"),
    ("codere_co_b", "Codere · es_CO/e", "codere.es", r"eventId=(\d+)",
     "https://apuestas.codere.com.co/es_CO/e/{id}"),
    ("betsson_co", "Betsson · apuestas-deportivas", "betsson", r"eventId=([^&#]+)",
     "https://www.betsson.co/apuestas-deportivas?eventId={id}"),
]
if not A.clave:
    EXPERIMENTALES = []                     # los formatos 🧪 salen de OddsPapi
# Se piden en la MISMA petición que BetPlay y compañía: no gastan de más.
for _slug in {e[2] for e in EXPERIMENTALES}:
    CASAS[f"_exp_{_slug}"] = _slug
RESULTADOS_CSV = RAIZ / "plataformas_resultados.csv"

# ── Respaldo: si no llega enlace directo, la pestaña va a la sección de tenis
# de la casa (y el apellido queda copiado para pegarlo en su buscador).
# POR VERIFICAR: se marcan en la tabla igual que los formatos 🧪.
RESPALDO = {
    "betplay": "https://tienda.betplay.com.co/apuestas#filter/tennis",
    "rushbet": "https://www.rushbet.co/?page=sportsbook#filter/tennis",
    "betano": "https://www.betano.co/live/",
    "bwin": "https://sports.bwin.co/es/sports/tenis-5",
    "stake": "https://stake.com.co/es/deportes/tennis",
    "codere": "https://m.codere.com.co/deportesCol/",
    "betsson": "https://www.betsson.co/apuestas-deportivas/tenis",
    "draftkings": "https://sportsbook.draftkings.com/sports/tennis",
    "fanduel": "https://sportsbook.fanduel.com/tennis",
    "betmgm": "https://www.nc.betmgm.com/en/sports/tennis-5",
    "caesars": "https://sportsbook.caesars.com/tennis",
    "wplay": "https://apuestas.wplay.co/es",
    "kalshi": "https://kalshi.com/sports/tennis",
    "polymarket": "https://polymarket.com/sports/tennis",
}


def _nombre(n: str) -> str:
    if "," in n:
        ap_, nom = [x.strip() for x in n.split(",", 1)]
        return f"{nom} {ap_}".strip()
    return n


EMPEZADOS: list[str] = []


def preparar_desde_fuentes(conn) -> int:
    """Sin OddsPapi: los partidos 'de FullTenis' salen de las fuentes gratuitas."""
    from buscador.providers.fuentes import FUENTES, TIEMPO_MAX_FUENTE_S, refrescar_todas

    print(f"Leyendo las fuentes gratuitas a la vez (máx. {TIEMPO_MAX_FUENTE_S} s)...")
    for m, r in asyncio.run(refrescar_todas()).items():
        if r == "sin configurar" and m == "fanduel":
            r += " (pon la clave real con --fanduel-ak)"
        print(f"   {m:<11} {r}")
    print("   (las de EE. UU. solo responden desde EE. UU.: sin VPN es normal que fallen)")
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(hours=A.horas_atras)).isoformat()[:19]
    hasta = (ahora + timedelta(hours=A.horas)).isoformat()[:19]
    vistos, n = set(), 0
    for m, f in FUENTES.items():
        for ev in f._eventos:
            ini = str(ev.get("inicio") or "")[:19]
            if not ev.get("en_juego") and not (desde <= ini <= hasta):
                continue
            clave = tuple(sorted([" ".join(sorted(normalizar(ev["j1"]).split())),
                                  " ".join(sorted(normalizar(ev["j2"]).split()))]))
            if clave in vistos:
                continue
            vistos.add(clave)
            if ev.get("en_juego"):
                EMPEZADOS.append(f"{ev['j1']} vs {ev['j2']} — {ev.get('torneo') or m} (en juego)")
            sync.guardar_fixture(conn, {"fixture_id": f"sim-{m}-{ev['id']}",
                                        "fecha": ev.get("inicio") or ahora.isoformat(),
                                        "jugador1": ev["j1"], "jugador2": ev["j2"],
                                        "torneo": ev.get("torneo") or "", "genero": "M"}, "fixtures")
            n += 1
    conn.commit()
    return n


def preparar_datos() -> int:
    """Partidos que hacen de 'FullTenis': de las fuentes gratuitas o, con clave,
    de la lista de OddsPapi."""
    conn = db.conectar()
    db.inicializar(conn)
    catalogo.sembrar(conn)
    if not A.clave:
        conn.execute("DELETE FROM fixtures_cache")
        conn.execute("DELETE FROM provider_event_map")
        n = preparar_desde_fuentes(conn)
        conn.close()
        return n
    print("Bajando la lista de partidos de OddsPapi (1 petición)...")
    asyncio.run(ODDSPAPI.sincronizar_fixtures(conn))
    ahora = datetime.now(timezone.utc)
    desde = (ahora - timedelta(hours=A.horas_atras)).isoformat()[:19]
    hasta = (ahora + timedelta(hours=A.horas)).isoformat()[:19]
    filas = conn.execute(
        "SELECT * FROM oddspapi_fixtures WHERE substr(inicio,1,19) BETWEEN ? AND ? "
        "ORDER BY (fixture_id LIKE 'id%') DESC, inicio", (desde, hasta)).fetchall()
    conn.execute("DELETE FROM fixtures_cache")
    conn.execute("DELETE FROM provider_event_map")   # respuestas de versiones anteriores
    # Consultas de sesiones anteriores pudieron hacerse sin las casas 🧪: se
    # vuelven a pedir (los enlaces ya guardados se conservan).
    conn.execute("DELETE FROM oddspapi_consultas")
    vistos, n = set(), 0
    for f in filas:
        j1, j2 = _nombre(f["jugador1"]), _nombre(f["jugador2"])
        clave = (tuple(sorted([normalizar(j1), normalizar(j2)])), f["dia"])
        if clave in vistos:                       # mismo partido con otro id
            continue
        vistos.add(clave)
        cat = f["categoria"] or ""
        genero = "F" if ("women" in cat or cat.startswith("wta") or "-w" in cat) else "M"
        torneo = f["torneo"] or cat
        if cat.startswith("itf") and not re.match(r"^[MW]\d", torneo):
            torneo = ("W" if genero == "F" else "M") + "15 " + torneo   # para deducir ITF
        if f["inicio"][:19] <= ahora.isoformat()[:19]:
            EMPEZADOS.append(f"{j1} vs {j2} — {f['torneo']} (inicio {f['inicio'][11:16]} UTC)")
        sync.guardar_fixture(conn, {"fixture_id": f"sim-{f['fixture_id']}", "fecha": f["inicio"],
                                    "jugador1": j1, "jugador2": j2, "torneo": torneo,
                                    "genero": genero}, "fixtures")
        n += 1
    conn.commit()
    conn.close()
    return n


PAGINA = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>FullTenis (simulado) — BOT BUSCADOR</title>
<style>
  body{margin:0;font-family:system-ui,sans-serif;background:#12161c;color:#e6e6e6}
  header{padding:12px 18px;background:#0b0e12;border-bottom:1px solid #2a2f37;
         display:flex;align-items:center;gap:14px}
  header b{font-size:18px} header span{font-size:12px;opacity:.6}
  nav{display:flex;gap:4px;padding:8px 12px;border-bottom:1px solid #2a2f37}
  .tab-btn{background:transparent;color:inherit;border:1px solid #2a2f37;border-radius:8px;
           padding:8px 12px;cursor:pointer}
  .tab-btn.activa{background:#1f6feb;border-color:#1f6feb}
  .panel{display:none;padding:10px} .panel.activo{display:block}
  .sim{max-width:900px;margin:10px auto;padding:10px 14px;border-radius:8px;font-size:13px;
       background:rgba(31,111,235,.12);border:1px solid rgba(31,111,235,.5)}
</style></head>
<body>
<header><b>🎾 FullTenis</b><span>SIMULADOR LOCAL — la pestaña es la real de RankingFTR</span>
  <a href="/links" style="color:#8ab4ff;font-size:13px">← obtener links (lista)</a></header>
<nav>
  <button class="tab-btn" data-tab="live" onclick="selTab(this)">📡 LIVE</button>
  <button class="tab-btn" data-tab="pre" onclick="selTab(this)">📋 PRE</button>
  <button class="tab-btn" data-tab="buscador" onclick="selTab(this)">🔎 BOT BUSCADOR</button>
</nav>
<div class="panel" id="panel-live"><p style="padding:20px;opacity:.6">(LIVE no se simula)</p></div>
<div class="panel" id="panel-pre"><p style="padding:20px;opacity:.6">(PRE no se simula)</p></div>
<div class="sim">Partidos simulados: __N__ (últimas __HA__ h y próximas __H__ h). Busca un apellido,
  por ejemplo <b>__EJ__</b>. La primera vez: marca tus casas → <i>Guardar mis casas</i>, y
  permite las ventanas emergentes de 127.0.0.1:__PFT__.</div>
__PANEL__
<script>
function selTab(b){
  document.querySelectorAll('.tab-btn').forEach(function(x){x.classList.remove('activa')});
  document.querySelectorAll('.panel').forEach(function(x){x.classList.remove('activo')});
  b.classList.add('activa');
  var p=document.getElementById('panel-'+b.dataset.tab); if(p) p.classList.add('activo');
}
</script>
<script src="/research/static/js/tabs/buscador_ventanas.js" defer></script>
<script src="/research/static/js/tabs/buscador.js" defer></script>
</body></html>"""


PAGINA_LINKS = """<!doctype html>
<html lang="es"><head><meta charset="utf-8">
<title>FullTenis (simulado) — Abrir partido en las casas</title>
<style>
  body{margin:0;font-family:system-ui,sans-serif;background:#12161c;color:#e6e6e6}
  header{padding:12px 18px;background:#0b0e12;border-bottom:1px solid #2a2f37;
         display:flex;align-items:center;gap:14px}
  header b{font-size:18px} header a{color:#8ab4ff;font-size:13px}
  main{max-width:1000px;margin:20px auto;padding:0 14px}
  input[type=search]{width:100%;box-sizing:border-box;padding:11px 12px;font-size:16px;
        border-radius:8px;border:1px solid #555;background:transparent;color:inherit}
  .casas input{margin:0 5px 0 0;vertical-align:middle}
  .p{padding:9px 12px;border-radius:8px;cursor:pointer;border:1px solid transparent;margin:4px 0}
  .p:hover{background:rgba(31,111,235,.15);border-color:#1f6feb}
  .p.activo{background:rgba(31,111,235,.25);border-color:#1f6feb}
  .sub{opacity:.65;font-size:13px}
  table{width:100%;border-collapse:collapse;margin-top:6px}
  td,th{padding:8px 10px;border-bottom:1px solid #2a2f37;text-align:left;font-size:14px;
        vertical-align:top}
  td a{color:#8ab4ff;word-break:break-all} .ok{color:#3fb950} .no{opacity:.6} .err{color:#f85149}
  .aviso{padding:10px 14px;border-radius:8px;background:rgba(255,193,7,.12);
         border:1px solid rgba(255,193,7,.5);display:none;margin:12px 0}
  h2{font-size:15px;margin:22px 0 8px;color:#8ab4ff}
  .grupo{margin:8px 0 12px} .grupo b{display:block;font-size:13px;opacity:.8;margin-bottom:4px}
  .casas{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:14px}
  .casas label{cursor:pointer} .casas .off{opacity:.4;cursor:default}
  .cuenta{font-size:13px;opacity:.8}
  .mk{padding:3px 8px;margin:4px 4px 0 0;font-size:12px;border-radius:6px;cursor:pointer;
      border:1px solid #555;background:#1b2129;color:#e6e6e6}
  .mk:hover{border-color:#1f6feb} .fb{color:#e3b341}
  .cp{padding:8px 14px;font-size:14px;border-radius:8px;cursor:pointer;border:0;background:#238636;color:#fff}
</style></head>
<body>
<header><b>🎾 FullTenis</b><span class="sub">SIMULADOR LOCAL — clic en un partido = una pestaña por casa</span>
  <a href="/#buscador">pestaña real de RankingFTR →</a></header>
<main>
  <h2>1. Elige tus casas de apuestas</h2>
  <div id="casas"><span class="sub">Cargando casas…</span></div>
  <div class="cuenta" id="cuenta"></div>
  <h2>2. Busca el partido y haz clic en él</h2>
  <div class="sub" style="margin-bottom:8px">__N__ partidos (últimas __HA__ h y próximas __H__ h).
    Por ejemplo <b>__EJ__</b>. Se abre una pestaña por cada casa elegida que tenga el partido.</div>
  <input type="search" id="q" placeholder="Escribe un jugador..." autocomplete="off">
  <div id="res" style="margin:8px 0"></div>
  <div class="aviso" id="aviso"></div>
  <div class="aviso" id="vivo">⏱️ <b>Este partido ya estaba en juego y nadie lo había abierto
    antes.</b> Con el plan gratuito, OddsPapi no da enlaces de partidos en juego, así que se
    abrió la sección de tenis de cada casa. La solución es la <b>precarga</b>: el BOT guarda los
    enlaces antes de que empiece cada partido (en el simulador: <code>--precarga 60</code>).</div>
  <div id="titulo" style="font-weight:600;margin-top:10px"></div>
  <div style="margin:6px 0"><button id="copiar" class="cp" style="display:none">📋 Copiar enlaces para enviar</button>
    <span id="copiado" class="sub"></span></div>
  <table id="tabla" style="display:none">
    <thead><tr><th>Casa</th><th>Región</th><th>Estado</th><th>Link</th></tr></thead>
    <tbody id="filas"></tbody>
  </table>
  <div id="resumen"></div>
</main>
<script>
(function(){
  var tk=null, url=null, casas=[], espera=null;
  function $(i){return document.getElementById(i)}
  function esc(s){return String(s==null?'':s).replace(/[&<>"']/g,function(c){
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
  function aviso(t){$('aviso').style.display=t?'block':'none';$('aviso').innerHTML=t||''}
  function token(){
    if(tk) return Promise.resolve(tk);
    return fetch('/api/buscador/token').then(function(r){return r.json()})
      .then(function(j){tk=j.token;url=j.url;return tk});
  }
  function api(ruta){
    return token().then(function(t){
      return fetch(url+ruta,{headers:{'Authorization':'Bearer '+t}});
    }).then(function(r){if(!r.ok) throw new Error(r.status); return r.json()});
  }
  // Las casas se cargan ANTES del clic: al hacer clic hay que abrir las
  // pestañas en ese mismo instante (el navegador no deja hacerlo después).
  var REGION={CO:'Colombia','US-NC':'EE. UU. (Carolina del Norte)',GLOBAL:'Mercados de predicción'};
  var ESTADO={PROVIDER_PENDING:'pendiente',COMING_SOON:'próximamente',
              NOT_AVAILABLE_REGION:'no disponible en la región',MAINTENANCE:'en mantenimiento',
              DISABLED:'desactivada'};
  var EXP=__EXP__, FB=__FB__;
  function base(id){return String(id).split('_')[0]}
  function botones(f, formato, u, partido){
    f.children[2].insertAdjacentHTML('beforeend','<br>'+
      ['ok|✅ sirve','portada|🏠 portada','no|❌ no sirve'].map(function(b){
        var q=b.split('|'); return '<button class="mk" data-r="'+q[0]+'">'+q[1]+'</button>'}).join(' '));
    f.querySelectorAll('.mk').forEach(function(b){
      b.addEventListener('click',function(){
        fetch('/sim/marcar',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({id:formato,resultado:b.dataset.r,partido:partido,url:u})})
        .then(function(){
          f.querySelectorAll('.mk').forEach(function(x){x.remove()});
          f.children[2].insertAdjacentHTML('beforeend','<div class="sub">anotado: '+esc(b.textContent)+'</div>');
          verResumen();
        });
      });
    });
  }
  // Sin enlace directo: la pestaña va a la sección de tenis de la casa.
  var avisadoVivo=false;
  // Kalshi: sin su número, al menos la lista de partidos de esa categoría.
  var KALSHI_SERIE={ATP:'kxatpmatch',WTA:'kxwtamatch',CHALLENGER:'kxatpchallengermatch',
                    WTA125:'kxwtachallengermatch',ITF_M:'kxitfmatch',ITF_W:'kxitfwmatch'};
  var categoriaActual='';
  function respaldo(f, w, idCasa, motivo, apellido, partido){
    if(!avisadoVivo && motivo.indexOf('en juego')>=0){
      avisadoVivo=true;
      $('vivo').style.display='block';
    }
    var u=FB[base(idCasa)];
    if(base(idCasa)==='kalshi' && KALSHI_SERIE[categoriaActual])
      u='https://kalshi.com/markets/'+KALSHI_SERIE[categoriaActual];
    if(!u){ if(w&&!w.closed) try{w.close()}catch(x){}
      f.children[2].className='no'; f.children[2].textContent=motivo; return; }
    if(w&&!w.closed) w.location.href=u;
    f.children[2].className='fb';
    f.children[2].innerHTML='🔍 '+esc(motivo)+' → abierta la sección de tenis. '+
      'Busca <b>'+esc(apellido)+'</b> (copiado)';
    f.children[3].innerHTML='<a href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">'+
      esc(u)+'</a><div class="sub">página de respaldo, por verificar</div>';
    botones(f,'respaldo:'+base(idCasa),u,partido);
  }
  function elegidas(){
    var m={}; document.querySelectorAll('#casas input:checked:not(.exp)').forEach(function(i){m[i.value]=1});
    return casas.filter(function(c){return m[c.id]});
  }
  function elegidasExp(){
    var m={}; document.querySelectorAll('#casas input.exp:checked').forEach(function(i){m[i.value]=1});
    return EXP.filter(function(e){return m[e.id]});
  }
  function verResumen(){
    fetch('/sim/resumen').then(function(r){return r.json()}).then(function(j){
      var f=j.formatos||[];
      $('resumen').innerHTML=f.length?'<h2>Resultados de las pruebas 🧪</h2><table>'+
        '<tr><th>Formato</th><th>✅ sirve</th><th>🏠 portada</th><th>❌ no sirve</th></tr>'+
        f.map(function(x){return '<tr><td>'+esc(x.nombre)+'</td><td>'+(x.ok||0)+'</td><td>'+
          (x.portada||0)+'</td><td>'+(x.no||0)+'</td></tr>'}).join('')+
        '</table><div class="sub">Guardado en plataformas_resultados.csv</div>':'';
    }).catch(function(){});
  }
  function contar(){
    var n=elegidas().length+elegidasExp().length;
    $('cuenta').textContent=n?n+' casa(s) elegida(s) · se guarda sola':'Ninguna casa elegida todavía';
  }
  var guardando=null;
  function guardar(){                     // se recuerda para la próxima vez
    contar(); clearTimeout(guardando);
    guardando=setTimeout(function(){
      token().then(function(t){
        return fetch(url+'/api/mis-casas',{method:'PUT',headers:{'Authorization':'Bearer '+t,
          'Content-Type':'application/json'},body:JSON.stringify({providers:
          elegidas().map(function(c){return c.id})})});
      }).catch(function(){aviso('No se pudo guardar tu selección')});
    },400);
  }
  Promise.all([api('/api/catalogo'),api('/api/mis-casas')]).then(function(r){
    var todas=r[0].providers||[], mias={};
    (r[1].providers||[]).forEach(function(p){mias[p.id]=1});
    casas=todas.filter(function(p){return p.seleccionable});
    var html='';
    ['CO','US-NC','GLOBAL'].forEach(function(reg){
      var g=todas.filter(function(p){return p.region===reg});
      if(!g.length) return;
      g.sort(function(a,b){return (b.seleccionable?1:0)-(a.seleccionable?1:0)||
                                  a.nombre.localeCompare(b.nombre)});
      html+='<div class="grupo"><b>'+esc(REGION[reg]||reg)+'</b><div class="casas">'+
        g.map(function(p){
          return p.seleccionable
            ?'<label><input type="checkbox" value="'+esc(p.id)+'"'+(mias[p.id]?' checked':'')+
              '> '+esc(p.nombre)+'</label>'
            :'<label class="off" title="'+esc(p.nota||'')+'"><input type="checkbox" disabled> '+
              esc(p.nombre)+' <span class="sub">('+esc(ESTADO[p.estado]||p.estado)+')</span></label>';
        }).join('')+'</div></div>';
    });
    var guardadas={};
    try{JSON.parse(localStorage.getItem('sim_exp')||'[]').forEach(function(i){guardadas[i]=1})}catch(x){}
    html+='<div class="grupo"><b>🧪 Colombia — en prueba (formato por confirmar)</b>'+
      '<div class="casas">'+EXP.map(function(e){
        return '<label><input type="checkbox" class="exp" value="'+esc(e.id)+'"'+
          (guardadas[e.id]?' checked':'')+'> '+esc(e.nombre)+'</label>'}).join('')+'</div></div>';
    $('casas').innerHTML=html; contar(); verResumen();
  }).catch(function(){aviso('BOT_BUSCADOR no responde')});
  $('casas').addEventListener('change',function(ev){
    if(ev.target.classList.contains('exp')){
      try{localStorage.setItem('sim_exp',JSON.stringify(elegidasExp().map(function(e){return e.id})))}catch(x){}
      contar();
    } else guardar();
  });

  $('q').addEventListener('input',function(){
    clearTimeout(espera); var q=this.value.trim();
    if(q.length<2){$('res').innerHTML='';return}
    espera=setTimeout(function(){
      api('/api/partidos?q='+encodeURIComponent(q)).then(function(j){
        var l=j.partidos||[];
        $('res').innerHTML=l.length?l.map(function(p){
          return '<div class="p" data-cat="'+esc(p.categoria||'')+'" data-a="'+esc(String(p.jugador1||'').trim().split(/\\s+/).pop())+
            '" data-clave="'+esc(p.clave)+'" data-n="'+
            esc(p.jugador1+' vs '+p.jugador2)+'"><b>'+esc(p.jugador1)+' vs '+esc(p.jugador2)+
            '</b><div class="sub">'+esc(p.torneo)+' · '+esc(p.categoria)+' · '+
            esc((p.fecha||'').slice(0,16).replace('T',' '))+' UTC</div></div>'}).join('')
          :'<div class="sub">Sin partidos con ese nombre</div>';
      }).catch(function(){aviso('BOT_BUSCADOR no responde')});
    },300);
  });

  var TXT={ENCONTRADO:'✅ abierto',NO_ENCONTRADO:'❌ no está en esta casa',AMBIGUO:'🟠 ambiguo',
           ERROR:'⛔ error',PROVIDER_PENDING:'⚪ pendiente'};

  // Copiar los enlaces directos (p. ej. desde Colombia, para enviarlos a EE. UU.)
  $('copiar').addEventListener('click',function(){
    var filas=Array.prototype.filter.call(document.querySelectorAll('#filas tr'),
      function(tr){return tr.dataset.url});
    var txt='🎾 '+$('titulo').textContent+'\\n'+filas.map(function(tr){
      return tr.children[0].textContent.replace('🧪 ','')+': '+tr.dataset.url}).join('\\n');
    var ok=function(){$('copiado').textContent='copiado: '+filas.length+' enlace(s)'};
    try{navigator.clipboard.writeText(txt).then(ok,function(){window.prompt('Copia:',txt)})}
    catch(x){window.prompt('Copia:',txt)}
  });

  $('res').addEventListener('click',function(e){
    var el=e.target.closest('.p'); if(!el) return;
    document.querySelectorAll('.p').forEach(function(x){x.classList.remove('activo')});
    el.classList.add('activo');
    var clave=el.dataset.clave, sel=elegidas(), selExp=elegidasExp(), partidoN=el.dataset.n,
        apellido=el.dataset.a||'';
    categoriaActual=el.dataset.cat||'';
    try{navigator.clipboard.writeText(apellido).catch(function(){})}catch(x){}
    if(!sel.length&&!selExp.length){
      aviso('Primero elige al menos una casa de apuestas en el paso 1.');
      $('casas').scrollIntoView({behavior:'smooth'}); return;
    }
    // 1) En el mismo clic: una pestaña nueva por casa.
    var pest={}, bloqueadas=0;
    sel.forEach(function(c){
      var w=null;
      try{w=window.open('about:blank','_blank')}catch(x){w=null}
      if(w){
        try{w.document.title=c.nombre;
            w.document.body.innerHTML='<p style="font-family:sans-serif">Buscando el partido en '+
              esc(c.nombre)+'…</p>'}catch(x){}
        try{w.opener=null}catch(x){}
      } else bloqueadas++;
      pest[c.id]=w;
    });
    var pestExp={};
    selExp.forEach(function(e){
      var w=null;
      try{w=window.open('about:blank','_blank')}catch(x){w=null}
      if(w){try{w.document.title=e.nombre;w.document.body.innerHTML=
        '<p style="font-family:sans-serif">Probando '+esc(e.nombre)+'…</p>'}catch(x){}
        try{w.opener=null}catch(x){}} else bloqueadas++;
      pestExp[e.id]=w;
    });
    avisadoVivo=false; $('vivo').style.display='none';
    aviso(bloqueadas?'⚠️ El navegador bloqueó <b>'+bloqueadas+'</b> pestaña(s). Haz clic en el '+
      'icono de ventanas bloqueadas de la barra de direcciones → <b>Permitir siempre ventanas '+
      'emergentes de '+esc(location.host)+'</b>, y vuelve a hacer clic en el partido. Mientras, '+
      'tienes los enlaces en la tabla.':'');
    $('titulo').textContent=el.dataset.n; $('tabla').style.display='table';
    $('copiar').style.display='none'; $('copiado').textContent='';
    $('filas').innerHTML=sel.map(function(p){
      return '<tr id="f-'+esc(p.id)+'"><td>'+esc(p.nombre)+'</td><td>'+esc(p.region)+
        '</td><td class="sub">buscando…</td><td></td></tr>'}).join('')+
      selExp.map(function(e){
      return '<tr id="f-'+esc(e.id)+'"><td>🧪 '+esc(e.nombre)+'</td><td>CO</td>'+
        '<td class="sub">buscando…</td><td></td></tr>'}).join('');
    // Colombia en prueba: una llamada para todos los formatos
    if(selExp.length){
      fetch('/sim/experimentales?clave='+encodeURIComponent(clave)).then(function(r){return r.json()})
      .catch(function(){return {estado:'ERROR',detalle:'sin respuesta',filas:[]}})
      .then(function(j){
        var por={}; (j.filas||[]).forEach(function(x){por[x.id]=x});
        selExp.forEach(function(e){
          var x=por[e.id]||{}, w=pestExp[e.id], f=$('f-'+e.id);
          if(!f) return;
          if(!x.url){
            respaldo(f,w,e.id,j.estado==='ERROR'?'sin enlace ('+(j.detalle||'error')+')':
                     (j.detalle||'la fuente no dio enlace directo'),apellido,partidoN);
            return;
          }
          if(w&&!w.closed) w.location.href=x.url;
          f.dataset.url=x.url; $('copiar').style.display='inline-block';
          f.children[2].className='';
          f.children[2].innerHTML='🧪 ¿abrió el partido?';
          f.children[3].innerHTML='<a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">'+
            esc(x.url)+'</a><div class="sub">OddsPapi: '+esc(x.origen||'')+'</div>';
          botones(f,e.id,x.url,partidoN);
        });
      });
    }
    // 2) Cada casa por su lado: la pestaña va al partido o, si no hay
    //    enlace directo, a la sección de tenis de la casa.
    sel.forEach(function(p){
      api('/api/resolver?clave='+encodeURIComponent(clave)+'&provider='+encodeURIComponent(p.id))
        .catch(function(){return {estado:'ERROR',detalle:'sin respuesta'}})
        .then(function(r){
          var w=pest[p.id], ok=r.estado==='ENCONTRADO'&&/^https:\\/\\//.test(r.url||'');
          var f=$('f-'+p.id); if(!f) return;
          if(!ok){
            respaldo(f,w,p.id,r.estado==='ERROR'?'sin enlace ('+(r.detalle||'error')+')':
                     'la fuente no dio enlace directo',apellido,partidoN);
            return;
          }
          if(w&&!w.closed) w.location.href=r.url;
          f.dataset.url=r.url; $('copiar').style.display='inline-block';
          f.children[2].className=ok?'ok':(r.estado==='ERROR'?'err':'no');
          f.children[2].textContent=(ok&&!w?'🔗 pestaña bloqueada, usa el enlace':
            (TXT[r.estado]||r.estado))+(r.detalle?' ('+r.detalle+')':'');
          f.children[3].innerHTML=r.url?'<a href="'+esc(r.url)+'" target="_blank" '+
            'rel="noopener noreferrer">'+esc(r.url)+'</a>':'';
        });
    });
  });
})();
</script>
</body></html>"""


def app_fulltenis(n: int, ejemplo: str) -> FastAPI:
    ft = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    panel = (DIR_SIM / "buscador.html").read_text(encoding="utf-8")
    js = (DIR_SIM / "buscador.js").read_text(encoding="utf-8")
    html = (PAGINA.replace("__PANEL__", panel).replace("__N__", str(n))
            .replace("__HA__", str(A.horas_atras)).replace("__H__", str(A.horas)).replace("__EJ__", ejemplo)
            .replace("__PFT__", str(A.puerto_ft)))

    import json as _json
    exp_js = _json.dumps([{"id": e[0], "nombre": e[1]} for e in EXPERIMENTALES], ensure_ascii=False)
    links = (PAGINA_LINKS.replace("__FB__", _json.dumps(RESPALDO)).replace("__EXP__", exp_js).replace("__N__", str(n)).replace("__HA__", str(A.horas_atras))
             .replace("__H__", str(A.horas)).replace("__EJ__", ejemplo))

    @ft.get("/", response_class=HTMLResponse)
    def inicio():
        return html

    @ft.get("/links", response_class=HTMLResponse)
    def pagina_links():
        return links

    @ft.get("/research/static/js/tabs/buscador.js")
    def script():
        return Response(js, media_type="application/javascript")

    @ft.get("/research/static/js/tabs/buscador_ventanas.js")
    def script_ventanas():
        return Response((DIR_SIM / "ventanas.js").read_text(encoding="utf-8"),
                        media_type="application/javascript")

    @ft.get("/sim/experimentales")
    async def experimentales(clave: str):
        if not EXPERIMENTALES:
            return {"estado": "NO_ENCONTRADO", "filas": []}
        conn = db.conectar()
        try:
            f = conn.execute("SELECT * FROM fixtures_cache WHERE clave = ?", (clave,)).fetchone()
            if not f:
                return {"estado": "NO_ENCONTRADO", "filas": []}
            p = Partido(f["clave"], f["jugador1"], f["jugador2"], f["fecha"],
                        bool(f["hora_conocida"]), f["torneo"] or "", f["categoria"] or "")
            estado, ids, _ = emparejar(conn, p)
            if estado != ENCONTRADO:
                return {"estado": estado, "filas": []}
            try:
                enl = await ODDSPAPI.enlaces(conn, ids[0], "betano")
            except SinAccesoEnVivo:
                return {"estado": "ERROR", "detalle": "partido en juego sin enlace guardado",
                        "filas": []}
            except Exception as e:
                return {"estado": "ERROR", "detalle": type(e).__name__, "filas": []}
            filas = []
            for eid, nombre, slug, patron, plantilla in EXPERIMENTALES:
                orig = enl.get(slug)
                m = re.search(patron, orig or "")
                filas.append({"id": eid, "nombre": nombre, "origen": orig,
                              "url": plantilla.format(id=m.group(1)) if m else None})
            c = conn.execute("SELECT resultado FROM oddspapi_consultas WHERE fixture_id = ?",
                             (ids[0],)).fetchone()
            vivo = bool(c and c["resultado"] == "en_vivo_sin_acceso")
            return {"estado": ENCONTRADO, "filas": filas,
                    "detalle": "partido en juego: la fuente ya no da enlaces nuevos" if vivo else ""}
        finally:
            conn.close()

    @ft.post("/sim/marcar")
    def marcar(d: dict):
        import csv
        nuevo = not RESULTADOS_CSV.exists()
        with open(RESULTADOS_CSV, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if nuevo:
                w.writerow(["cuando", "formato", "resultado", "partido", "url"])
            w.writerow([datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        str(d.get("id", ""))[:40], str(d.get("resultado", ""))[:20],
                        str(d.get("partido", ""))[:120], str(d.get("url", ""))[:400]])
        return resumen()

    @ft.get("/sim/resumen")
    def resumen():
        import csv
        cuenta: dict = {}
        if RESULTADOS_CSV.exists():
            with open(RESULTADOS_CSV, encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    c = cuenta.setdefault(r["formato"], {})
                    c[r["resultado"]] = c.get(r["resultado"], 0) + 1
        nombres = {e[0]: e[1] for e in EXPERIMENTALES}
        nombres.update({f"respaldo:{k}": f"Respaldo {k} (sección de tenis)" for k in RESPALDO})
        return {"formatos": [{"id": k, "nombre": nombres.get(k, k), **v}
                             for k, v in cuenta.items()]}

    @ft.get("/api/buscador/token")
    def token():
        # En RankingFTR: solo usuarios con permiso; aquí, el admin local.
        return {"token": emitir(SECRETO, "local", "ruben", "admin"), "url": URL_BOT,
                "expira_en": 600}

    return ft


async def servir(n: int, ejemplo: str):
    s_ft = uvicorn.Server(uvicorn.Config(app_fulltenis(n, ejemplo), host="127.0.0.1",
                                         port=A.puerto_ft, log_level="warning"))
    s_bot = uvicorn.Server(uvicorn.Config(bot.app, host="127.0.0.1", port=A.puerto_bot,
                                          log_level="warning"))

    async def abrir_navegador():
        await asyncio.sleep(1.5)            # que los dos servidores estén arriba
        webbrowser.open(f"{ORIGEN_FT}/#buscador")

    async def barrido():
        if not A.barrido:
            return
        await asyncio.sleep(2)
        c = db.conectar()
        try:
            casas = sorted({v for k, v in CASAS.items() if not k.startswith("_exp_")})
            r = await ODDSPAPI.barrer(c, 30, A.barrido_max, casas=casas)
            print(f"[barrido] {r['torneos']} torneos en {r['lotes']} lotes × {r['casas']} casas: "
                  f"{r['peticiones']} peticiones, {r['enlaces']} enlaces guardados"
                  f"{' (cortado: ' + r['cortado'] + ')' if r['cortado'] else ''}")
            print("[barrido] listo: ya puedes abrir partidos EN JUEGO.")
        except Exception as e:
            print(f"[barrido] {type(e).__name__}: {e}")
        finally:
            c.close()

    async def precarga():
        if not A.precarga:
            return
        await asyncio.sleep(3)
        while True:
            c = db.conectar()
            try:
                r = await ODDSPAPI.precargar(c, A.precarga, A.precarga_max)
                print(f"[precarga] {datetime.now().strftime('%H:%M')} próximos {A.precarga} min: "
                      f"{r['pendientes']} sin enlaces, {r['pedidos']} pedidos"
                      f"{', límite de OddsPapi (429)' if r['cortado'] else ''}")
            except Exception as e:
                print(f"[precarga] {type(e).__name__}: {e}")
            finally:
                c.close()
            await asyncio.sleep(600)

    await asyncio.gather(s_ft.serve(), s_bot.serve(), abrir_navegador(), precarga(), barrido())


def main():
    n = preparar_datos()
    if not n:
        sys.exit("Ninguna fuente devolvió partidos. Si ahora no hay tenis en juego, prueba más "
                 "tarde; las casas de EE. UU. necesitan VPN de EE. UU. desde Colombia.")
    conn = db.conectar()
    f = conn.execute("SELECT jugador1 FROM fixtures_cache WHERE categoria IN ('ATP','WTA') "
                     "LIMIT 1").fetchone() or conn.execute(
                         "SELECT jugador1 FROM fixtures_cache LIMIT 1").fetchone()
    conn.close()
    ejemplo = f["jugador1"].split()[-1] if f else "Damm"
    print(f"{n} partidos cargados como si vinieran de FullTenis.")
    print(f"{len(EMPEZADOS)} ya empezaron (en juego o recién acabados). Algunos para probar:")
    for e in EMPEZADOS[-12:]:
        print(f"   · {e}")
    print()
    print(f"  Pestaña real (la de producción): {ORIGEN_FT}/#buscador")
    print(f"  Pantalla de pruebas antigua:     {ORIGEN_FT}/links")
    print(f"  BOT_BUSCADOR:        {URL_BOT}/salud")
    if A.barrido:
        print(f"\n  BARRIDO POR TORNEOS al arrancar (máx. {A.barrido_max} peticiones). Espera el "
              f"mensaje '[barrido] listo' antes de abrir partidos en juego.")
    if A.precarga:
        print(f"\n  PRECARGA ACTIVA: cada 10 min, enlaces de los partidos que empiezan en los "
              f"próximos {A.precarga} min (máx. {A.precarga_max} por ciclo). Gasta cupo de OddsPapi.")
    else:
        if not A.barrido:
            print("\n  Sin barrido ni precarga: un partido ya empezado que nadie abrió antes no")
            print("  tendrá enlaces (plan gratuito). Para verlo: --barrido")
    print("\nCtrl+C para parar.\n")
    try:
        asyncio.run(servir(n, ejemplo))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
