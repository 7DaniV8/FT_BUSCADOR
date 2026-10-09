# CAMBIOS — 08/10/2026 — Emparejamiento v2 (FT_BUSCADOR)

Pedido de Rubén: "que siempre encuentre los partidos y donde no encuentre el
partido no abra esa pestaña".

## Por qué no encontraba

1. `claves.apellidos("Carlos Alcaraz Garfia")` devolvía solo `{'garfia'}` (la
   última palabra) y las casas muestran "C. Alcaraz": no casaba. Ahora, con
   nombre + dos apellidos, cuentan los dos; las partículas (de, del, van, jr…)
   no cuentan.
2. Grafías distintas entre FullTenis y la casa (Schwartzman/Schwarzman,
   Kecmanovic/Kecmanovich, Mpetshi/Mpetschi): exigía igualdad exacta. Ahora
   `claves.parecidos()` acepta parecido ≥ 0,85 en palabras de 5+ letras con la
   misma inicial; las cortas siguen exactas (Lee ≠ Lei).
3. Seis fuentes (Kambi=BetPlay/Rushbet, DraftKings, BetMGM/Bwin, Betano, Wplay,
   Hard Rock) solo publican tenis EN VIVO: un partido que no empezó nunca iba
   a estar. Antes salía NO_ENCONTRADO + respaldo (y la pestaña se abría en la
   sección de tenis). Ahora `SOLO_EN_VIVO=True` en esas fuentes y, si el
   partido no empezó (hora conocida, margen 5 min), `/api/resolver` responde
   `NO_ENCONTRADO` con `detalle` claro y `solo_en_vivo: true`, SIN respaldo:
   FullTenis no abre nada y ofrece Reintentar al empezar.

## Archivos

- `buscador/claves.py` (`apellidos`, `parecidos`, `apellido_en`),
  `buscador/providers/fuentes.py` (`emparejar`, `SoloEnVivo`, `_ya_empezo`,
  `SOLO_EN_VIVO`), `buscador/app.py` (`/api/resolver`), `tests/test_buscador.py` (§20).

`python tests/test_buscador.py` → TODO BIEN.
