---
tipo: producto
fecha: '2026-11-11'
fuente: auditar
paises:
  ZZ:
    estado: con_checkout
    landing:
      url: https://tienda-prueba.example/zz/
      hosting: impultienda
      qa:
        archivo: landing/ZZ/QA-publicada.md
        fecha: '2026-11-20'
        movil_390:
          http: 200
          captura: landing/ZZ/qa/movil-0123456789ab-publicada.png
        utm_checkout:
          ok: true
          destino: https://pago.tienda-prueba.example/c/1?utm_source=fb&utm_medium=paid&utm_campaign=c|1&utm_term=s|2&utm_content=a|3
          captura: landing/ZZ/qa/utm.png
          interceptado: false
          fuente: checkout/ZZ/embudo.md
    checkout:
      plataforma: impultienda
      url: https://pago.tienda-prueba.example/c/1
      precio:
        importe: '12.90'
        moneda: EUR
    tracking:
      dataset_id: '123456789012345'
      dataset_nombre: PRUEBA ZZ
      emisor_purchase: impultienda
      estado: verificado
    compra_prueba:
      pedido: ORD-0001
      fecha: '2026-11-21'
      importe: '12.90'
      moneda: EUR
      plataforma:
        visto: true
        fuente: mcp
        evidencia: checkout/ZZ/compra/pedido.json
      events_manager:
        purchase: 1
        dataset_id: '123456789012345'
        fuente: MCP ads_get_dataset_stats
        evidencia: checkout/ZZ/compra/events-manager.json
      entrega:
        email: true
        pdf_descargable: true
        evidencia: checkout/ZZ/compra/entrega.md
      reembolso:
        procesado: true
        fecha: '2026-11-21'
        evidencia: checkout/ZZ/compra/reembolso.json
  YZ:
    estado: aprobado
---
# Producto de prueba

Texto del cuerpo que no se toca.
