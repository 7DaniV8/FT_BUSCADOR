// tests/test_ventanas.js — motor de distribución de ventanas (sin navegador).
const V = require('../scripts/simulador/ventanas.js');
let fallos = 0;
const ok = (c, t) => { console.log((c ? '  OK    ' : '  FALLO ') + t); if (!c) fallos++; };
const P = { x: 0, y: 0, w: 1920, h: 1080 };

const esperado = { 1: [1], 2: [2], 3: [2, 1], 4: [2, 2], 5: [3, 2], 6: [3, 3], 7: [3, 3, 1], 9: [3, 3, 3], 10: [4, 4, 2] };
for (const n in esperado) ok(JSON.stringify(V.filas(+n)) === JSON.stringify(esperado[n]), `${n} casas → filas ${JSON.stringify(esperado[n])}`);

const r4 = V.rejilla(4, P);
ok(JSON.stringify(r4) === JSON.stringify([{x:0,y:0,w:960,h:540},{x:960,y:0,w:960,h:540},{x:0,y:540,w:960,h:540},{x:960,y:540,w:960,h:540}]), '4 casas = 2×2 exacto (como en la prueba real)');
const r3 = V.rejilla(3, P);
ok(r3[2].w === 1920 && r3[2].y === 540, '3 casas: la tercera ocupa todo el ancho abajo (sin hueco)');

// Sin huecos ni solapes para 1..12 y pantallas "raras" (Mac con menú/Dock, 1366×728, coordenadas negativas)
const pantallas = [P, { x: 0, y: 25, w: 1440, h: 790 }, { x: 0, y: 0, w: 1366, h: 728 }, { x: -1920, y: 0, w: 1920, h: 1040 }];
let todoBien = true;
for (const p of pantallas) for (let n = 1; n <= 12; n++) {
  const rs = V.rejilla(n, p);
  const area = rs.reduce((a, r) => a + r.w * r.h, 0);
  const dentro = rs.every(r => r.x >= p.x && r.y >= p.y && r.x + r.w <= p.x + p.w && r.y + r.h <= p.y + p.h);
  let solape = false;
  for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) {
    const a = rs[i], b = rs[j];
    if (a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h) solape = true;
  }
  if (rs.length !== n || area !== p.w * p.h || !dentro || solape) { todoBien = false; console.log('   ✗', JSON.stringify(p), n); }
}
ok(todoBien, '1 a 12 casas en 4 tipos de pantalla: cubren toda la pantalla, sin huecos ni solapes');

// Varias pantallas
const dos = V.ordenarPantallas([{ x: 1920, y: 0, w: 1920, h: 1080 }, { x: -1440, y: 0, w: 1440, h: 900 }, P]);
ok(dos[0].x === -1440 && dos[2].x === 1920, 'pantallas ordenadas de izquierda a derecha (incluida la de coordenadas negativas)');
const casas = ['a','b','c','d','e','f','g','h','i','j','k'].map(id => ({ id }));
const d = V.distribuir(casas, [P, { x: 1920, y: 0, w: 1920, h: 1080 }, { x: 3840, y: 0, w: 1920, h: 1080 }], 4);
ok(['a','b','c','d'].every(id => d[id].pantalla === 1) && ['e','f','g','h'].every(id => d[id].pantalla === 2)
   && ['i','j','k'].every(id => d[id].pantalla === 3), '11 casas en 3 pantallas: 4 + 4 + 3 (tu ejemplo)');
ok(d.a.x === 0 && d.e.x === 1920 && d.i.x === 3840, 'cada casa cae dentro de su pantalla');
const f = V.distribuir([{ id: 'x', pantalla: 2 }, { id: 'y' }, { id: 'z', pantalla: 5 }], [P, { x: 1920, y: 0, w: 1920, h: 1080 }], 4);
ok(f.x.pantalla === 2 && f.y.pantalla === 1 && f.z.pantalla === 2, 'pantalla fija respetada; si esa pantalla no existe en este ordenador, va a la última');
ok(f.x.w === 960 && f.z.w === 960, 'la pantalla 2 reparte entre sus 2 casas (mitades)');
const una = V.distribuir(casas.slice(0, 6), [P], 4);
ok(Object.values(una).every(r => r.pantalla === 1), 'con una sola pantalla, todas en ella (aunque pasen del máximo)');

console.log(fallos ? `\n${fallos} FALLO(S)` : '\nTODO BIEN');
process.exit(fallos ? 1 : 0);
