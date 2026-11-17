---
tipo: escalera
producto: p-0042-respira
fecha: '2026-11-13'
fuente: productos/p-0042-respira/modelar.yaml, config/economia.yaml, config/mercados.yaml
paises:
  ZZ:
    moneda: EUR
    fuente_precio: banda del país
    front_eur: '13.90'
    pasos:
      front:
        precio: '13.90'
        activo: true
        motivo_inactivo: null
        titulo: Respira y duerme
        entregable: El plan de 21 días con su diario de sueño
      bump:
        precio: '4.90'
        activo: false
        motivo_inactivo: 'apagado en el test 1: se enciende con ≥ 10 ventas, §4.1'
        titulo: Respira en la oficina
        entregable: Rutinas cortas para el día de trabajo
      u1:
        precio: '19.90'
        activo: true
        motivo_inactivo: null
        titulo: Calma para la ansiedad de la mañana
        entregable: Plan de 7 días para empezar el día sin prisa, la próxima dolencia
      u2:
        precio: '29.90'
        activo: false
        motivo_inactivo: el plan de la tienda admite 1 upsell
        titulo: Respira en pareja
        entregable: Prácticas para hacer en pareja antes de dormir
      u3:
        precio: '12.90'
        activo: false
        motivo_inactivo: el plan de la tienda admite 1 upsell
        titulo: Mini plan
        entregable: Versión corta del plan
      downsell:
        precio: '7.90'
        activo: false
        motivo_inactivo: 'no medido: P-05'
        titulo: Respira lite
        entregable: El plan sin el diario imprimible
    aov_usd: '17.16'
    avisos: []
---
# Escalera · p-0042-respira

Ficticia.
