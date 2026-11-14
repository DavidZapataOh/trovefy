---
tipo: escalera
producto: p-0042-kit-demo
fecha: '2026-11-13'
fuente: productos/p-0042-kit-demo/modelar.yaml, config/economia.yaml, config/mercados.yaml
paises:
  XE:
    moneda: EUR
    fuente_precio: banda del país
    front_eur: '13.90'
    pasos:
      front:
        precio: '13.90'
        activo: true
        motivo_inactivo: null
        titulo: Подреден дом за 14 дни
        entregable: El plan de 14 días con su lista de control
      bump:
        precio: '4.90'
        activo: false
        motivo_inactivo: 'apagado en el test 1: se enciende con ≥ 10 ventas, §4.1'
        titulo: Седмичен план
        entregable: Plan de mantenimiento para después de los 14 días
      u1:
        precio: '19.90'
        activo: true
        motivo_inactivo: null
        titulo: Кухня без хаос
        entregable: Plan de 7 días solo para la cocina
      u2:
        precio: '30.90'
        activo: false
        motivo_inactivo: el plan de la tienda admite 1 upsell
        titulo: Гардероб за един уикенд
        entregable: Método para vaciar y ordenar el armario
      u3:
        precio: '12.90'
        activo: false
        motivo_inactivo: el plan de la tienda admite 1 upsell
        titulo: Мини план
        entregable: Versión corta del plan para pisos pequeños
      downsell:
        precio: '7.90'
        activo: false
        motivo_inactivo: 'no medido: P-05'
        titulo: Кухня лайт
        entregable: La guía de cocina sin las listas imprimibles
    aov_usd: '17.16'
    be_usd: '14.58'
    cpa_be_usd: '14.58'
    cpa_test_usd: '7.29'
    cpa_escala_usd: '9.48'
    roas_be: '1.18'
    avisos:
    - 'comparación con el original: no medido (moneda del original no medida)'
    - 'AOV estimado 17,16 USD: lejos del objetivo de 30 USD (aspiracional)'
  XR:
    moneda: RON
    fuente_precio: banda del país
    front_eur: '13.86'
    pasos:
      front:
        precio: '69'
        activo: true
        motivo_inactivo: null
        titulo: Подреден дом за 14 дни
        entregable: El plan de 14 días con su lista de control
      bump:
        precio: '29'
        activo: false
        motivo_inactivo: 'apagado en el test 1: se enciende con ≥ 10 ventas, §4.1'
        titulo: Седмичен план
        entregable: Plan de mantenimiento para después de los 14 días
      u1:
        precio: '99'
        activo: true
        motivo_inactivo: null
        titulo: Кухня без хаос
        entregable: Plan de 7 días solo para la cocina
      u2:
        precio: '149'
        activo: false
        motivo_inactivo: el plan de la tienda admite 1 upsell
        titulo: Гардероб за един уикенд
        entregable: Método para vaciar y ordenar el armario
      u3:
        precio: '59'
        activo: false
        motivo_inactivo: el plan de la tienda admite 1 upsell
        titulo: Мини план
        entregable: Versión corta del plan para pisos pequeños
      downsell:
        precio: '39'
        activo: false
        motivo_inactivo: 'no medido: P-05'
        titulo: Кухня лайт
        entregable: La guía de cocina sin las listas imprimibles
    aov_usd: '17.12'
    be_usd: '14.55'
    cpa_be_usd: '14.55'
    cpa_test_usd: '7.27'
    cpa_escala_usd: '9.45'
    roas_be: '1.18'
    avisos:
    - 'comparación con el original: no medido (moneda del original no medida)'
    - 'AOV estimado 17,12 USD: lejos del objetivo de 30 USD (aspiracional)'
cambio:
  fuente: BCE
  fecha: '2026-11-12'
  url: https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml
---
# Escalera de precios · p-0042-kit-demo

Cambio: BCE del 2026-11-12 (https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml).

## XE (EUR)

Precio del front: banda del país.

| Paso | Pieza | Precio | Activo | Motivo |
|---|---|---|---|---|
| Front | Подреден дом за 14 дни | 13,90 EUR | sí | — |
| Bump | Седмичен план | 4,90 EUR | no | apagado en el test 1: se enciende con ≥ 10 ventas, §4.1 |
| U1 | Кухня без хаос | 19,90 EUR | sí | — |
| U2 | Гардероб за един уикенд | 30,90 EUR | no | el plan de la tienda admite 1 upsell |
| U3 | Мини план | 12,90 EUR | no | el plan de la tienda admite 1 upsell |
| Downsell | Кухня лайт | 7,90 EUR | no | no medido: P-05 |

### Economía (USD)

- AOV: 17,16 USD
- BE (CPA de equilibrio): 14,58 USD
- CPA de test: 7,29 USD
- CPA de escala: 9,48 USD
- ROAS de equilibrio: 1,18

BE = AOV 17,16 × (1 − 0,1 − 0 − 0,05) − 0 × cobros 1,1 → 14,58 USD (a la baja al céntimo)

### Avisos

- comparación con el original: no medido (moneda del original no medida)
- AOV estimado 17,16 USD: lejos del objetivo de 30 USD (aspiracional)

## XR (RON)

Precio del front: banda del país.

| Paso | Pieza | Precio | Activo | Motivo |
|---|---|---|---|---|
| Front | Подреден дом за 14 дни | 69 RON | sí | — |
| Bump | Седмичен план | 29 RON | no | apagado en el test 1: se enciende con ≥ 10 ventas, §4.1 |
| U1 | Кухня без хаос | 99 RON | sí | — |
| U2 | Гардероб за един уикенд | 149 RON | no | el plan de la tienda admite 1 upsell |
| U3 | Мини план | 59 RON | no | el plan de la tienda admite 1 upsell |
| Downsell | Кухня лайт | 39 RON | no | no medido: P-05 |

### Economía (USD)

- AOV: 17,12 USD
- BE (CPA de equilibrio): 14,55 USD
- CPA de test: 7,27 USD
- CPA de escala: 9,45 USD
- ROAS de equilibrio: 1,18

BE = AOV 17,12 × (1 − 0,1 − 0 − 0,05) − 0 × cobros 1,1 → 14,55 USD (a la baja al céntimo)

### Avisos

- comparación con el original: no medido (moneda del original no medida)
- AOV estimado 17,12 USD: lejos del objetivo de 30 USD (aspiracional)
