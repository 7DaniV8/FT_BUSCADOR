/* ventanas.js — Distribución automática de las ventanas que abre BOT BUSCADOR.
 *
 * SOLO calcula posiciones y coloca ventanas que el propio buscador abrió
 * (vacías, antes de cargar la casa). No toca páginas de las casas: el
 * navegador tampoco lo permite (otro origen).
 *
 * Cuadrícula adaptable (sin huecos): columnas = ceil(raíz(n)) (2 si n = 2);
 * la última fila se estira a todo el ancho.
 *   1 → completa · 2 → mitades · 3 → 2 + 1 ancha · 4 → 2×2 · 5 → 3 + 2 · 6 → 3×2 …
 *
 * Varias pantallas (Chrome/Edge con permiso "gestión de ventanas"): se numeran
 * de izquierda a derecha. Cada casa puede tener pantalla fija; las demás
 * llenan las pantallas por orden hasta `maxPorPantalla`.
 */
(function (raiz) {
  'use strict';

  // Número de ventanas por fila para n ventanas.
  function filas(n) {
    if (n <= 0) return [];
    var cols = n <= 2 ? n : Math.ceil(Math.sqrt(n));
    var salida = [];
    for (var resto = n; resto > 0; resto -= cols) salida.push(Math.min(cols, resto));
    return salida;
  }

  // Rectángulos (x, y, w, h) de n ventanas dentro de una pantalla.
  function rejilla(n, p) {
    var f = filas(n), rects = [];
    var alto = Math.floor(p.h / Math.max(f.length, 1));
    f.forEach(function (k, r) {
      var ancho = Math.floor(p.w / k);
      var y = p.y + r * alto, h = (r === f.length - 1) ? p.y + p.h - y : alto;
      for (var i = 0; i < k; i++) {
        var x = p.x + i * ancho, w = (i === k - 1) ? p.x + p.w - x : ancho;
        rects.push({ x: x, y: y, w: w, h: h });
      }
    });
    return rects;
  }

  // Pantallas ordenadas de izquierda a derecha (y de arriba abajo).
  function ordenarPantallas(lista) {
    return lista.slice().sort(function (a, b) { return (a.x - b.x) || (a.y - b.y); });
  }

  /* casas: [{id, pantalla?}] en el orden deseado (pantalla 1-based, opcional).
   * pantallas: [{x, y, w, h}] ya ordenadas.
   * Devuelve {id: {x, y, w, h, pantalla}}. */
  function distribuir(casas, pantallas, maxPorPantalla) {
    var n = pantallas.length, max = maxPorPantalla || 4, grupos = [];
    if (!n || !casas.length) return {};
    for (var i = 0; i < n; i++) grupos.push([]);
    var auto = [];
    casas.forEach(function (c) {
      var p = parseInt(c.pantalla, 10);
      if (p >= 1) grupos[Math.min(p, n) - 1].push(c.id);   // si faltan pantallas, a la última
      else auto.push(c.id);
    });
    var k = 0;
    auto.forEach(function (id) {
      while (k < n - 1 && grupos[k].length >= max) k++;
      grupos[k].push(id);
    });
    var salida = {};
    grupos.forEach(function (ids, i) {
      rejilla(ids.length, pantallas[i]).forEach(function (r, j) {
        r.pantalla = i + 1;
        salida[ids[j]] = r;
      });
    });
    return salida;
  }

  // Coloca una ventana abierta por el buscador (vacía, mismo origen).
  function colocar(w, r) {
    try { w.moveTo(r.x, r.y); w.resizeTo(r.w, r.h); return true; } catch (e) { return false; }
  }

  // Pantallas disponibles: todas (Chrome/Edge con permiso) o la actual.
  function pantallaActual() {
    var s = window.screen;
    return [{ x: s.availLeft || 0, y: s.availTop || 0, w: s.availWidth, h: s.availHeight,
              nombre: 'Esta pantalla' }];
  }
  function detectarPantallas(pedirPermiso) {
    if (!('getScreenDetails' in window)) return Promise.resolve({ lista: pantallaActual(), multi: false });
    var intento = function () {
      return window.getScreenDetails().then(function (d) {
        var l = ordenarPantallas(d.screens.map(function (s) {
          return { x: s.availLeft, y: s.availTop, w: s.availWidth, h: s.availHeight,
                   nombre: s.label || '' };
        }));
        return { lista: l, multi: true };
      });
    };
    var permiso = (navigator.permissions && navigator.permissions.query)
      ? navigator.permissions.query({ name: 'window-management' }).then(function (r) { return r.state; },
                                                                         function () { return 'prompt'; })
      : Promise.resolve('prompt');
    return permiso.then(function (estado) {
      if (estado === 'granted' || pedirPermiso) return intento();
      return { lista: pantallaActual(), multi: false, pendiente: estado !== 'denied' };
    }).catch(function () { return { lista: pantallaActual(), multi: false }; });
  }

  var api = { filas: filas, rejilla: rejilla, ordenarPantallas: ordenarPantallas,
              distribuir: distribuir, colocar: colocar, detectarPantallas: detectarPantallas };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else raiz.FTVentanas = api;
})(typeof window !== 'undefined' ? window : this);
