/* tabs/buscador.js — Pestaña 🔎 BOT BUSCADOR (28/09/2026).
 *
 * Todo el tráfico va del NAVEGADOR al servicio BOT_BUSCADOR. El servidor de
 * FullTenis solo entrega un token corto (/api/buscador/token); nunca llama al
 * buscador ni espera a ninguna casa.
 *
 * Aislamiento:
 *   - todo va dentro de esta función; no deja variables globales.
 *   - cada llamada lleva tiempo máximo (AbortController).
 *   - cada casa se resuelve por separado (Promise.allSettled): una lenta o
 *     caída no frena a las demás.
 *   - cualquier fallo del servicio muestra el aviso SOLO en esta pestaña.
 *
 * Ventanas: el navegador solo deja abrir ventanas en el mismo instante del
 * clic. Por eso, al pulsar ABRIR, se abre al momento una ventana con nombre
 * por casa ("ft_<casa>", reutilizable para el siguiente partido) y después se
 * navega cuando llega su URL. Si una casa no tiene enlace directo, su ventana
 * va a la sección de tenis de esa casa (`respaldo`, que decide el buscador) y
 * el apellido queda copiado para pegarlo en su buscador; si no hay respaldo,
 * la ventana se cierra.
 * Antes de navegar se corta window.opener: la página de la casa no puede
 * tocar la pestaña de FullTenis.
 *
 * Cómo abrir (30/09/2026), a elección del usuario y guardado EN ESTE ORDENADOR:
 *   - todas a la vez (por defecto): una pestaña/ventana por casa, sin colocar;
 *     cada una carga su casa en cuanto llega su enlace.
 *   - cuadrícula: al pulsar ABRIR se abre una ventana vacía por casa; cuando
 *     llegan las respuestas se recolocan SOLO las que tienen destino (enlace o
 *     sección de tenis) con buscador_ventanas.js, se cierran las demás y cada
 *     una carga su casa ya en su sitio. Las ventanas solo se pueden colocar
 *     mientras están vacías (el navegador no deja mover una página de otro
 *     origen); por eso, en cada ABRIR se cierran las del buscador y se abren de
 *     nuevo. Varias pantallas: Chrome/Edge con el permiso de gestión de ventanas.
 *   - una a una: no abre nada solo; muestra un botón «Abrir» por casa.
 */
(function () {
  'use strict';
  var T_TOKEN = 5000, T_API = 4000, T_CASA = 8000;
  var estado = { token: null, url: null, vence: 0, iniciado: false, partido: null,
                 nombrePartido: '', apellido: '', enlaces: [], catalogo: [], mias: [],
                 sub: 'anon', pantallas: [], multi: false,
                 pref: { modo: 'todas', max: 4, pantalla: {} } };
  var MOVIL = !!(window.matchMedia && window.matchMedia('(pointer: coarse)').matches);
  var ESTADOS = { PROVIDER_PENDING: 'pendiente', COMING_SOON: 'próximamente',
                  NOT_AVAILABLE_REGION: 'no disponible en la región', MAINTENANCE: 'en mantenimiento',
                  DISABLED: 'desactivada', TESTING: 'en prueba', ACTIVE: 'activa' };
  var REGIONES = [['CO', 'Colombia'], ['US-NC', 'EE. UU. (Carolina del Norte)'],
                  ['GLOBAL', 'Mercados de predicción']];
  var ICONO = {
    ENCONTRADO: '✅ ENCONTRADO', NO_ENCONTRADO: '❌ NO ENCONTRADO', AMBIGUO: '🟠 AMBIGUO',
    LOGIN_REQUERIDO: '🟡 LOGIN REQUERIDO', UBICACION_REQUERIDA: '🟡 UBICACIÓN REQUERIDA',
    PROVIDER_PENDING: '⚪ PENDIENTE', NO_DISPONIBLE: '⚪ NO DISPONIBLE EN TU REGIÓN',
    ERROR: '⛔ ERROR'
  };

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function aviso(mostrar, texto) {
    var a = $('bb-aviso');
    if (!a) return;
    a.textContent = texto || '🔎 BOT BUSCADOR temporalmente no disponible';
    a.style.display = mostrar ? 'block' : 'none';
  }
  function conTiempo(url, opciones, ms) {
    var ctl = new AbortController();
    var t = setTimeout(function () { ctl.abort(); }, ms);
    opciones = opciones || {};
    opciones.signal = ctl.signal;
    return fetch(url, opciones).finally(function () { clearTimeout(t); });
  }

  function token() {
    if (estado.token && Date.now() < estado.vence) return Promise.resolve(estado.token);
    return conTiempo('/api/buscador/token', { credentials: 'same-origin' }, T_TOKEN)
      .then(function (r) {
        if (r.status === 503) throw new Error('no_configurado');
        if (!r.ok) throw new Error('token ' + r.status);
        return r.json();
      })
      .then(function (j) {
        estado.token = j.token;
        estado.url = j.url;
        try {
          var carga = JSON.parse(atob(j.token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
          if (carga && carga.sub && estado.sub !== String(carga.sub)) {
            estado.sub = String(carga.sub); cargarPref();
          }
        } catch (e) { /* nada */ }
        estado.vence = Date.now() + (j.expira_en - 60) * 1000;
        return j.token;
      });
  }

  function api(ruta, opciones, ms) {
    return token().then(function (tk) {
      opciones = opciones || {};
      opciones.headers = Object.assign({ 'Authorization': 'Bearer ' + tk },
                                       opciones.headers || {});
      opciones.credentials = 'omit';
      return conTiempo(estado.url + ruta, opciones, ms || T_API);
    }).then(function (r) {
      if (!r.ok) throw new Error('api ' + r.status);
      return r.json();
    });
  }

  function fallo(e) {
    if (e && e.message === 'no_configurado') {
      aviso(true, '🔎 BOT BUSCADOR no está disponible todavía');
    } else {
      aviso(true);
    }
  }

  // ── Preferencia "cómo abrir" (en este ordenador, por usuario) ──────
  function clavePref() { return 'bb_pref_' + estado.sub; }
  function cargarPref() {
    try {
      var g = JSON.parse(localStorage.getItem(clavePref()) || 'null');
      if (g && (g.modo === 'todas' || g.modo === 'cuadricula' || g.modo === 'una')) estado.pref.modo = g.modo;
      if (g && g.max >= 1 && g.max <= 9) estado.pref.max = g.max;
      if (g && g.pantalla && typeof g.pantalla === 'object') estado.pref.pantalla = g.pantalla;
    } catch (e) { /* nada */ }
    if (MOVIL && estado.pref.modo === 'cuadricula') estado.pref.modo = 'todas';
    pintarDistribucion();
  }
  function guardarPref() {
    try { localStorage.setItem(clavePref(), JSON.stringify(estado.pref)); } catch (e) { /* nada */ }
  }
  function detectar(pedir) {
    if (!window.FTVentanas) return;
    window.FTVentanas.detectarPantallas(pedir).then(function (d) {
      estado.pantallas = d.lista; estado.multi = d.multi; pintarDistribucion();
    });
  }
  function pintarDistribucion() {
    var cont = $('bb-dist');
    if (!cont) return;
    var modo = estado.pref.modo, cuad = modo === 'cuadricula', n = estado.pantallas.length || 1;
    var op = function (v, texto, titulo, off) {
      return '<label class="ctrl-btn' + (modo === v ? ' active' : '') + '" title="' + esc(titulo) + '">' +
             '<input type="radio" name="bb-modo" value="' + v + '"' + (modo === v ? ' checked' : '') +
             (off ? ' disabled' : '') + '>' + texto + '</label>';
    };
    var h = '<div class="ctrl-options">' +
            op('todas', '📑 Todas a la vez', 'Cada casa en su pestaña, sin colocar') +
            op('cuadricula', '🪟 Cuadrícula', 'Todas a la vez, ordenadas en tus pantallas', MOVIL) +
            op('una', '👆 Una a una', 'Un botón «Abrir» por casa; tú eliges') + '</div>';
    h += '<div class="muted" style="margin-top:4px">' + ({
      todas: 'Cada casa se abre en su pestaña en cuanto llega su enlace.',
      cuadricula: 'Se abren todas a la vez, colocadas en tus pantallas según los enlaces encontrados.',
      una: 'No se abre nada solo: un botón «Abrir» por casa.' })[modo] + '</div>';
    if (MOVIL) h += '<div class="muted">En el móvil no hay cuadrícula.</div>';
    if (cuad && !MOVIL) {
      h += '<div class="bb-opciones"><label>Máximo por pantalla <input type="number" id="bb-max" min="1" max="9" value="' +
        estado.pref.max + '" style="width:52px"></label>' +
        '<span class="muted">' + n + ' pantalla(s)' + (estado.multi ? '' : ' (esta)') + '</span>' +
        ('getScreenDetails' in window && !estado.multi ?
          '<button class="go" id="bb-detectar" type="button">Detectar pantallas</button>' : '') +
        '</div>';
      if (n > 1 && estado.mias.length) {
        h += '<div class="bb-asig">' + estado.mias.map(function (c) {
          var v = estado.pref.pantalla[c.id] || '';
          var ops = '<option value="">Auto</option>';
          for (var i = 1; i <= n; i++) ops += '<option value="' + i + '"' + (String(v) === String(i) ? ' selected' : '') + '>Pantalla ' + i + '</option>';
          return '<label>' + esc(c.nombre) + ' <select data-casa="' + esc(c.id) + '">' + ops + '</select></label>';
        }).join('') + '</div>';
      }
    }
    cont.innerHTML = h;
  }

  // ABRIR se activa con partido elegido Y casas guardadas, en cualquier orden.
  function actualizarAbrir() {
    var b = $('bb-abrir');
    if (!b) return;
    b.disabled = !(estado.partido && estado.mias.length);
    if (estado.partido && !estado.mias.length) {
      $('bb-estado').innerHTML =
        '<div class="muted">Marca tus casas y pulsa «Guardar mis casas».</div>';
    }
  }

  // ── Mis casas ──────────────────────────────────────────────────────
  function pintarCasas() {
    var cont = $('bb-casas');
    var mias = {};
    estado.mias.forEach(function (p) { mias[p.id] = true; });
    // Solo las casas disponibles (activas o en prueba), en píldoras por región.
    var disp = estado.catalogo.filter(function (p) { return p.seleccionable; });
    if (!disp.length) { cont.innerHTML = '<span class="muted">Sin casas disponibles</span>'; return; }
    function casa(p) {
      return '<label class="ctrl-btn bb-casa' + (mias[p.id] ? ' active' : '') + '">' +
        '<input type="checkbox" value="' + esc(p.id) + '"' + (mias[p.id] ? ' checked' : '') + '>' +
        esc(p.nombre) + '</label>';
    }
    var vistas = {};
    var html = REGIONES.map(function (r) {
      var g = disp.filter(function (p) { return p.region === r[0]; });
      g.forEach(function (p) { vistas[p.id] = true; });
      if (!g.length) return '';
      return '<div class="bb-grupo"><div class="bb-region">' + esc(r[1]) + '</div>' +
             '<div class="ctrl-options">' + g.map(casa).join('') + '</div></div>';
    }).join('');
    var resto = disp.filter(function (p) { return !vistas[p.id]; });
    if (resto.length) html += '<div class="bb-grupo"><div class="ctrl-options">' + resto.map(casa).join('') + '</div></div>';
    cont.innerHTML = html;
  }

  function cargarCasas() {
    return Promise.all([api('/api/catalogo'), api('/api/mis-casas')]).then(function (r) {
      estado.catalogo = r[0].providers || [];
      estado.mias = r[1].providers || [];
      aviso(false);
      pintarCasas();
      pintarDistribucion();
      actualizarAbrir();
    }).catch(function (e) {
      $('bb-casas').innerHTML = '<span class="muted">No disponible</span>';
      fallo(e);
    });
  }

  function guardarCasas() {
    var ids = Array.prototype.map.call(
      document.querySelectorAll('#bb-casas input:checked'), function (i) { return i.value; });
    api('/api/mis-casas', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ providers: ids }) })
      .then(function () { return cargarCasas(); })
      .catch(fallo);
  }

  // ── Búsqueda ───────────────────────────────────────────────────────
  var espera = null;
  function buscar() {
    var q = $('bb-q').value.trim();
    clearTimeout(espera);
    if (q.length < 2) { $('bb-resultados').innerHTML = ''; return; }
    espera = setTimeout(function () {
      api('/api/partidos?q=' + encodeURIComponent(q)).then(function (j) {
        aviso(false);
        var lista = j.partidos || [];
        estado.partido = null;
        $('bb-abrir').disabled = true;
        $('bb-resultados').innerHTML = lista.length ? lista.map(function (p) {
          var cuando = p.hora_conocida ? p.fecha.slice(0, 16).replace('T', ' ') :
                                         p.fecha.slice(0, 10) + ' (hora sin confirmar)';
          var ape = String(p.jugador1 || '').trim().split(/\s+/).pop();
          return '<label class="bb-partido"><input type="radio" name="bb-p" value="' +
            esc(p.clave) + '" data-n="' + esc(p.jugador1 + ' vs ' + p.jugador2) +
            '" data-a="' + esc(ape) + '"><b>' + esc(p.jugador1) + ' vs ' + esc(p.jugador2) + '</b>' +
            '<span class="muted">' + esc(p.torneo) + ' · ' + esc(p.categoria) + ' · ' +
            esc(cuando) + '</span></label>';
        }).join('') : '<div class="muted">Sin partidos con ese nombre</div>';
      }).catch(fallo);
    }, 300);
  }

  // ── Abrir en mis casas ─────────────────────────────────────────────
  function abrir() {
    if (!estado.partido || !estado.mias.length) return;
    if (estado.pref.modo === 'una') return abrirUnaAUna();
    if (estado.pref.modo === 'cuadricula' && !MOVIL && window.FTVentanas) return abrirCuadricula();
    return abrirTodas();
  }

  function destinoDe(r) {
    var url = r.url && /^https:\/\//.test(r.url) &&
      (r.estado === 'ENCONTRADO' || r.estado === 'LOGIN_REQUERIDO' || r.estado === 'UBICACION_REQUERIDA') ? r.url : null;
    var respaldo = !url && r.respaldo && /^https:\/\//.test(r.respaldo) ? r.respaldo : null;
    return { url: url, respaldo: respaldo };
  }
  function pintarFila(c, r, d, extra) {
    var fila = document.getElementById('bb-e-' + c.id);
    if (!fila) return;
    fila.textContent = c.nombre + ' → ' + (ICONO[r.estado] || r.estado) +
      (r.estado === 'ERROR' && r.detalle ? ' (' + r.detalle + ')' : '');
    if (d.respaldo) {
      fila.textContent += ' · 🔍 ' + (extra === 'una' ? 'su sección de tenis' : 'abierta su sección de tenis') +
                          ': busca «' + estado.apellido + '» (copiado)';
      fila.className = 'bb-respaldo';
    }
    if (extra === 'una' && (d.url || d.respaldo)) {
      var a = document.createElement('a');
      a.className = 'bb-uno'; a.target = '_blank'; a.rel = 'noopener noreferrer';
      a.href = d.url || d.respaldo; a.textContent = d.url ? 'Abrir' : 'Abrir sección de tenis';
      a.addEventListener('click', function () {
        try { navigator.clipboard.writeText(estado.apellido).catch(function () {}); } catch (e) { /* nada */ }
      });
      fila.appendChild(a);
    }
  }
  // Mandar una ventana del buscador a su destino. Red de seguridad: si 1,5 s
  // después sigue vacía (about:blank), se repite la orden. Si ya cargó la casa,
  // el navegador no deja leerla (otro origen) y eso confirma que cargó.
  function ir(w, destino) {
    try { w.location.href = destino; } catch (e) { return; }
    setTimeout(function () {
      try { if (!w.closed && w.location.href === 'about:blank') w.location.href = destino; }
      catch (e) { /* ya está en la casa */ }
    }, 1500);
  }
  function preparar(casas) {
    estado.enlaces = [];
    $('bb-copiar').style.display = 'none';
    $('bb-copiado').textContent = '';
    try { navigator.clipboard.writeText(estado.apellido).catch(function () {}); } catch (e) { /* nada */ }
    $('bb-estado').innerHTML = casas.map(function (c) {
      return '<div id="bb-e-' + esc(c.id) + '">' + esc(c.nombre) + ' → buscando…</div>';
    }).join('');
  }
  function resolverTodas(casas, alLlegar) {
    return Promise.allSettled(casas.map(function (c) {
      return api('/api/resolver?clave=' + encodeURIComponent(estado.partido) +
                 '&provider=' + encodeURIComponent(c.id), null, T_CASA)
        .then(function (r) { return r; },
              function () { return { provider: c.id, nombre: c.nombre, estado: 'ERROR' }; })
        .then(function (r) {
          var d = destinoDe(r);
          if (d.url) estado.enlaces.push({ nombre: c.nombre, url: d.url });
          alLlegar(c, r, d);
          return { c: c, d: d };
        });
    })).then(function (rs) {
      if (estado.enlaces.length) $('bb-copiar').style.display = 'inline-block';
      return rs.map(function (x) { return x.value; }).filter(Boolean);
    });
  }

  // ── Todas a la vez: una pestaña/ventana por casa, sin colocar ──────
  // Se abren en el mismo clic (con nombre por casa, reutilizables) y cada una
  // carga su casa en cuanto llega su enlace, sin esperar a las demás.
  function abrirTodas() {
    var casas = estado.mias.slice(), ventanas = {}, bloqueadas = 0;
    casas.forEach(function (c) {
      var w = null;
      try { w = window.open('about:blank', 'ftt_' + c.id); } catch (e) { w = null; }
      if (w) { try { w.opener = null; } catch (e) { /* nada */ } } else { bloqueadas++; }
      ventanas[c.id] = w;
    });
    preparar(casas);
    if (bloqueadas) $('bb-estado').innerHTML += '<div class="muted">El navegador bloqueó ' + bloqueadas +
      ' ventana(s): permite las ventanas emergentes de FullTenis y pulsa otra vez.</div>';
    resolverTodas(casas, function (c, r, d) {
      var w = ventanas[c.id];
      if (w && !w.closed) {
        if (d.url || d.respaldo) ir(w, d.url || d.respaldo);
        else { try { w.close(); } catch (e) { /* nada */ } }
      }
      pintarFila(c, r, d, 'todas');
    });
  }

  // ── Una a una: sin ventanas; un botón «Abrir» por casa ─────────────
  function abrirUnaAUna() {
    var casas = estado.mias.slice();
    preparar(casas);
    resolverTodas(casas, function (c, r, d) { pintarFila(c, r, d, 'una'); });
  }

  // ── Cuadrícula: ventanas colocadas según los enlaces encontrados ───
  function abrirCuadricula() {
    var V = window.FTVentanas, casas = estado.mias.slice();
    var pant = estado.pantallas.length ? estado.pantallas : [{ x: screen.availLeft || 0,
      y: screen.availTop || 0, w: screen.availWidth, h: screen.availHeight }];
    var orden = function (lista) { return lista.map(function (c) {
      return { id: c.id, pantalla: estado.pref.pantalla[c.id] }; }); };
    // 0) Cerrar SOLO las ventanas que abrió el buscador la vez anterior.
    var previas = [];
    try { previas = JSON.parse(localStorage.getItem('bb_abiertas') || '[]'); } catch (e) { /* nada */ }
    previas.forEach(function (id) {
      var w = (estado.ventanas && estado.ventanas[id]) || null;
      if (!w) { try { w = window.open('', 'ft_' + id); } catch (e) { w = null; } }
      if (w && !w.closed) { try { w.close(); } catch (e) { /* nada */ } }
    });
    // 1) En el mismo clic: una ventana vacía por casa, ya en una cuadrícula provisional.
    var inicial = V.distribuir(orden(casas), pant, estado.pref.max);
    var ventanas = {}, bloqueadas = 0;
    casas.forEach(function (c) {
      var r = inicial[c.id], w = null;
      try {
        w = window.open('about:blank', 'ft_' + c.id,
                        'popup,left=' + r.x + ',top=' + r.y + ',width=' + r.w + ',height=' + r.h);
      } catch (e) { w = null; }
      if (w) {
        V.colocar(w, r);
        try { w.document.title = c.nombre;
              w.document.body.textContent = 'Buscando el partido en ' + c.nombre + '…'; } catch (e) { /* nada */ }
        try { w.opener = null; } catch (e) { /* nada */ }
      } else { bloqueadas++; }
      ventanas[c.id] = w;
    });
    estado.ventanas = ventanas;
    try { localStorage.setItem('bb_abiertas', JSON.stringify(casas.map(function (c) { return c.id; }))); } catch (e) { /* nada */ }
    preparar(casas);
    if (bloqueadas) $('bb-estado').innerHTML += '<div class="muted">El navegador bloqueó ' + bloqueadas +
      ' ventana(s): permite las ventanas emergentes de FullTenis y pulsa otra vez.</div>';
    // 2) Cuando llegan TODAS las respuestas: cuadrícula final solo con las que tienen destino.
    resolverTodas(casas, function (c, r, d) { pintarFila(c, r, d, 'cuadricula'); }).then(function (rs) {
      var usar = rs.filter(function (x) { return (x.d.url || x.d.respaldo) && ventanas[x.c.id] && !ventanas[x.c.id].closed; });
      usar.sort(function (a, b) { return (a.d.url ? 0 : 1) - (b.d.url ? 0 : 1); });   // enlaces directos primero
      var fin = V.distribuir(orden(usar.map(function (x) { return x.c; })), pant, estado.pref.max);
      rs.forEach(function (x) {
        var w = ventanas[x.c.id];
        if (!w || w.closed) return;
        if (fin[x.c.id]) { V.colocar(w, fin[x.c.id]); ir(w, x.d.url || x.d.respaldo); }
        else { try { w.close(); } catch (e) { /* nada */ } }
      });
    });
  }

  // Copiar los enlaces directos (p. ej. para enviarlos a quien esté en otro país).
  function copiar() {
    var txt = '🎾 ' + estado.nombrePartido + '\n' + estado.enlaces.map(function (e) {
      return e.nombre + ': ' + e.url; }).join('\n');
    var hecho = function () { $('bb-copiado').textContent = 'copiado: ' + estado.enlaces.length + ' enlace(s)'; };
    try { navigator.clipboard.writeText(txt).then(hecho, function () { window.prompt('Copia:', txt); }); }
    catch (e) { window.prompt('Copia:', txt); }
  }

  // ── Arranque: solo cuando se abre la pestaña ───────────────────────
  function iniciar() {
    if (estado.iniciado) return;
    estado.iniciado = true;
    try {
      $('bb-q').addEventListener('input', buscar);
      $('bb-guardar').addEventListener('click', guardarCasas);
      $('bb-abrir').addEventListener('click', abrir);
      $('bb-copiar').addEventListener('click', copiar);
      $('bb-casas').addEventListener('change', function (ev) {
        var l = ev.target && ev.target.closest ? ev.target.closest('label') : null;
        if (l) l.classList.toggle('active', !!ev.target.checked);
      });
      $('bb-dist').addEventListener('change', function (ev) {
        var t = ev.target;
        if (t.name === 'bb-modo') { estado.pref.modo = t.value; guardarPref(); pintarDistribucion(); }
        else if (t.id === 'bb-max') { var m = parseInt(t.value, 10);
          if (m >= 1 && m <= 9) { estado.pref.max = m; guardarPref(); } }
        else if (t.getAttribute('data-casa')) {
          if (t.value) estado.pref.pantalla[t.getAttribute('data-casa')] = parseInt(t.value, 10);
          else delete estado.pref.pantalla[t.getAttribute('data-casa')];
          guardarPref();
        }
      });
      $('bb-dist').addEventListener('click', function (ev) {
        if (ev.target && ev.target.id === 'bb-detectar') detectar(true);
      });
      cargarPref();
      detectar(false);
      $('bb-resultados').addEventListener('change', function (ev) {
        if (ev.target && ev.target.name === 'bb-p') {
          estado.partido = ev.target.value;
          Array.prototype.forEach.call(document.querySelectorAll('#bb-resultados .bb-partido'),
            function (l) { l.classList.toggle('active', l.contains(ev.target)); });
          estado.nombrePartido = ev.target.getAttribute('data-n') || '';
          estado.apellido = ev.target.getAttribute('data-a') || '';
          $('bb-estado').innerHTML = '';
          actualizarAbrir();
        }
      });
      cargarCasas();
    } catch (e) { fallo(e); }
  }

  function enganchar() {
    var boton = document.querySelector('.tab-btn[data-tab="buscador"]');
    if (!boton || !$('panel-buscador')) return;
    boton.addEventListener('click', iniciar);
    if (location.hash === '#buscador') {   // entrada por /buscador
      try { boton.click(); } catch (e) { /* nada */ }
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enganchar);
  else enganchar();
})();
