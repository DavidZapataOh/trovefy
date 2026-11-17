---
tipo: qa_landing
pais: ZZ
version: a1b2c3d4e5f6
ok: true
fecha: '2026-11-17T10:30:00-05:00'
url: null
movil_390:
  http: 200
  captura: landing/ZZ/qa/movil-a1b2c3d4e5f6.png
utm_checkout:
  ok: true
  destino: http://127.0.0.1:8000/checkout?utm_source=fb&utm_medium=paid&utm_campaign=QA%7C0&utm_term=QA%7C0&utm_content=QA%7C0&fbclid=QA
  captura: null
  interceptado: true
  fuente: landing/ZZ/QA.md
---
# QA de la landing · p-0099-demo · ZZ

Versión `a1b2c3d4e5f6` · local (127.0.0.1) · apta.

4G simulado: 562,5 ms, 1,47 Mbit/s bajada, 0,68 Mbit/s subida, CPU ×4.

| Comprobación | Estado | Detalle |
|---|---|---|
| Validación estática | OK | sin fallos |
| Versión servida (movil) | OK | a1b2c3d4e5f6 |
| LCP (movil, 4G simulado) | OK | mediana 1.250 ms (rondas 1.200 / 1.300 / 1.250); máximo 2.500 ms |
| Peso (movil) | OK | 180 KB |
| Desborde (movil) | OK | scrollWidth 390 px |
| Peticiones externas (movil) | OK | ninguna |
| Hitos (movil) | OK | 15 hitos en orden |
| Versión servida (escritorio) | OK | a1b2c3d4e5f6 |
| Peso (escritorio) | OK | 186 KB |
| Desborde (escritorio) | OK | scrollWidth 1280 px |
| Peticiones externas (escritorio) | OK | ninguna |
| Hitos (escritorio) | OK | 15 hitos en orden |
| Clic al checkout con UTM | OK | http://127.0.0.1:8000/checkout?utm_source=fb&utm_medium=paid&utm_campaign=QA%7C0&utm_term=QA%7C0&utm_content=QA%7C0&fbclid=QA |
| Idioma (nativo) | OK | ok (versión a1b2c3d4e5f6) |

## Medidas

### movil (390×844)

- Captura: landing/ZZ/qa/movil-a1b2c3d4e5f6.png
- Peso: 180 KB
- LCP: mediana 1.250 ms (rondas 1.200 / 1.300 / 1.250 ms)

### escritorio (1280×800)

- Captura: landing/ZZ/qa/escritorio-a1b2c3d4e5f6.png
- Peso: 186 KB
- LCP: mediana 820 ms (rondas 800 / 850 / 820 ms)
