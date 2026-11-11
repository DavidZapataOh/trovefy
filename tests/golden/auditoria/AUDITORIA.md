---
tipo: auditoria
fecha: '2026-11-10'
fuente: wiki/ofertas/o-ejemplo.md
oferta_id: o-ejemplo
recomendado: RO
reserva: IT
senales:
  ya_se_vende: true
  hueco_por_pais: true
  se_puede_mejorar: null
paises:
  RO:
    puesto: 1
    nota: 100.0
    hueco: true
    no_tirar: null
  IT:
    puesto: 2
    nota: 83.33
    hueco: true
    no_tirar: null
  FR:
    puesto: 3
    nota: 33.33
    hueco: false
    no_tirar: el original ya anuncia traducido
---
# Auditoría de o-ejemplo (2026-11-10)

Dónde lanzar esta oferta, país por país. Lo que no se pudo medir se dice como tal y no puntúa: la nota de cada país se calcula solo con lo medido.

## La oferta

- Ficha: [[wiki/ofertas/o-ejemplo]]
- Decisión de la caza: **B** — nota 62,4 < 70 para A (el hueco por país lo mide esta auditoría, más abajo)
- Precio del original: 13,90 EUR — landing: https://tienda.example/fichas
- Precio del original en EUR: 13,90 € (la ficha ya está en euros: sin cambio)
- Cambio de moneda: referencia del BCE del 2026-11-10 — https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml
- Cifras de la caza por país:
  - ES: C8 15 · C7 16 · total 32 anuncios activos · el más antiguo lleva 40 días — https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=ES&media_type=all&search_type=page&view_all_page_id=100000000000001

## Ranking de países

Pesos de la nota: config/umbrales.yaml (auditar.peso.*, [D-13]). Lo no medido no puntúa ni resta: la nota se calcula sobre los puntos medidos.

| # | País | Nota (0 a 100) | Hueco | No tirar |
|---|---|---|---|---|
| 1 | RO | 100 (medida sobre 45 de 100 puntos) | sí | — |
| 2 | IT | 83 (medida sobre 45 de 100 puntos) | sí | — |
| 3 | FR | 33 (medida sobre 45 de 100 puntos) | no | el original ya anuncia traducido |

### 1. RO — nota 100 (medida sobre 45 de 100 puntos)

- Hueco: **sí** — competencia local: 0 anunciantes en el idioma local · original: anuncia sin traducir (bonus)
- Precio del original en EUR: 13,90 € · precio soportable: 1 (1 = dentro de la banda de precios del país; 0 = muy lejos) · banda de RO: 11,90–15,90 € (fuente: vídeos: 11,90–15,90 €, config/mercados.yaml) · precio local en RO: ≈ 74,28 RON (al cambio del BCE de «La oferta»)
- Búsquedas en la Biblioteca que dan estas cifras:
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=RO&media_type=all&q=fise+terapie&search_type=keyword_unordered
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=RO&media_type=all&q=kit+terapie&search_type=keyword_unordered
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=RO&media_type=all&search_type=page&view_all_page_id=100000000000001

| Parte | Peso | Valor (0 a 1) |
|---|---|---|
| Hueco | 30 | 1 |
| Precio soportable | 15 | 1 |
| Demanda | 35 | no medido: requiere /ads_archive |
| CPM | 10 | no medido: sin historial en la cuenta |
| Encaje cultural | 10 | no medido: lo valora el usuario |

Cálculo: 100 × 45 ÷ 45 (solo los pesos medidos) = 100.

### 2. IT — nota 83 (medida sobre 45 de 100 puntos)

- Hueco: **sí** — competencia local: 0 anunciantes en el idioma local · original: sin anuncios activos ahora en el país
- Precio del original en EUR: 13,90 € · precio soportable: 0,5 (1 = dentro de la banda de precios del país; 0 = muy lejos) · banda de IT: 15,90–19,90 € (fuente: banda de ejemplo, config/mercados.yaml) · precio local en IT: 13,90 EUR
- Búsquedas en la Biblioteca que dan estas cifras:
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=IT&media_type=all&q=schede+terapia&search_type=keyword_unordered
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=IT&media_type=all&q=kit+terapia&search_type=keyword_unordered
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=IT&media_type=all&search_type=page&view_all_page_id=100000000000001

| Parte | Peso | Valor (0 a 1) |
|---|---|---|
| Hueco | 30 | 1 |
| Precio soportable | 15 | 0,5 |
| Demanda | 35 | no medido: requiere /ads_archive |
| CPM | 10 | no medido: sin historial en la cuenta |
| Encaje cultural | 10 | no medido: lo valora el usuario |

Cálculo: 100 × 37,5 ÷ 45 (solo los pesos medidos) = 83,33.

### 3. FR — nota 33 (medida sobre 45 de 100 puntos)

- Hueco: **no** — competencia local: 0 anunciantes en el idioma local · original: ya anuncia traducido al idioma local
- Precio del original en EUR: 13,90 € · precio soportable: 1 (1 = dentro de la banda de precios del país; 0 = muy lejos) · banda de FR: 11,90–15,90 € (fuente: vídeos: 11,90–15,90 €, config/mercados.yaml) · precio local en FR: 13,90 EUR
- No tirar: el original ya anuncia traducido
- Búsquedas en la Biblioteca que dan estas cifras:
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=FR&media_type=all&q=fiches+therapie&search_type=keyword_unordered
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=FR&media_type=all&q=kit+therapie&search_type=keyword_unordered
  - https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=FR&media_type=all&search_type=page&view_all_page_id=100000000000001

| Parte | Peso | Valor (0 a 1) |
|---|---|---|
| Hueco | 30 | 0 |
| Precio soportable | 15 | 1 |
| Demanda | 35 | no medido: requiere /ads_archive |
| CPM | 10 | no medido: sin historial en la cuenta |
| Encaje cultural | 10 | no medido: lo valora el usuario |

Cálculo: 100 × 15 ÷ 45 (solo los pesos medidos) = 33,33.

## No tirar

- FR: el original ya anuncia traducido — https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country=FR&media_type=all&search_type=page&view_all_page_id=100000000000001

## Las tres señales

- Ya se vende (la caza la dejó en A o B): **sí**
- Hay hueco en algún país: **sí**
- Se puede mejorar: **pendiente** — lo confirma la autopsia de /modelar

Si eliges con «ya se vende» o «hay hueco» en «no», la elección queda escrita como excepción en decisiones/.

## Historial del cerebro

¿Ya lanzamos algo parecido allí? No: ningún producto del cerebro murió en RO, IT ni FR.

## Qué medir

Nada: todos los países auditados tienen el hueco comprobado.

## Recomendación

Recomendado: RO (nota 100, medida sobre 45 de 100 puntos) — la nota más alta entre los países con hueco comprobado; reserva: IT (nota 83, medida sobre 45 de 100 puntos).

Primer test: 1 producto × 1 país (el capital no da para dos a la vez); la reserva es el país al que pasar si el primero no funciona.

La elección es tuya: dímela y la registro.
