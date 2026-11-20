---
name: ayuda
description: Lista los comandos de Trovefy disponibles y para qué sirve cada uno. Úsala cuando el usuario pregunte qué puede hacer Trovefy o cómo empezar.
allowed-tools: Bash(trovefy version)
---

# Ayuda de Trovefy

Responde siempre en español. Muestra al usuario esta lista de lo disponible hoy:

- `trovefy version`: muestra la versión instalada del comando (ejecútalo para confirmar que está en el PATH).
- `/trovefy:ayuda`: esta ayuda; resume los comandos y skills de Trovefy.
- `/trovefy:cazar`: caza ofertas que ya venden en la Biblioteca de anuncios de Meta y escribe el informe y las fichas en el cerebro (`trovefy caza ejecutar`, `trovefy caza hueco`).
- `/trovefy:auditar`: audita una oferta cazada país por país (hueco, precio y nota), escribe `productos/<p-id>/AUDITORIA.md` y registra el país que eliges con tus palabras (`trovefy auditar ejecutar`, `trovefy auditar elegir`).
- `/trovefy:modelar`: modela la oferta del país elegido (autopsia, core offer, escalera de precios y brandbook) y escribe `OFERTA.md`, `ESCALERA.md`, `BRANDBOOK.md` y `comparativa.md`; queda aprobada si no la rechazas en la sesión (`trovefy modelar …`, `trovefy economia …`).
- `/trovefy:producto`: hace el entregable del producto modelado (ficha, plan, texto, imágenes con APIMart dentro del tope de US$ 2, PDF, gates y revisión de los agentes `revisor` y `nativo`, con sus bonos y upsells); al cerrar, el país pasa a `producido` (`trovefy producto …`).
- `/trovefy:landing`: hace la landing propia del país producido (sonda de Impultienda, borrador en su idioma, validación, agente `nativo`, QA en móvil y escritorio) y la publica en Impultienda o en Cloudflare Pages; al publicar, el país pasa a `con_landing` (`trovefy landing …`).
- `/trovefy:tracking`: deja medido el país con landing: el dataset (píxel) con su nombre exacto, el píxel y la CAPI que pegas tú en tu panel, los eventos comprobados por el MCP de Meta en solo lectura y el dataset en los límites del ejecutor; es el paso 11 de `/trovefy:arranque` (`trovefy tracking …`).
- `/trovefy:checkout`: arma el checkout por el conector de Impultienda tras tu aprobación del resumen en seco, lo comprueba desde fuera, guía la compra y el reembolso de prueba (los haces tú) y cierra el país en `con_checkout`; un requisito sin verde solo se salta con tu excepción, con tus palabras (`trovefy checkout …`).
- `/trovefy:creativos`: hace la tanda de anuncios del país listo como en los vídeos (10 piezas: imágenes y vídeos con las cuatro plantillas, voz, música y clip de gancho), te enseña el coste antes de gastar, la revisa (QA, Whisper, `revisor` y `nativo`), deja `manifest.csv` para `/montar` y te avisa por Telegram; también renueva cada 48 h y rehace tras un veto (`trovefy creativos …`).
- `/trovefy:montar`: monta el test del país como en los vídeos (ABO 5 × US$ 5, techo US$ 100, plazo 1 semana, salida a las 00:00) por el ejecutor, todo en PAUSED y validado antes; tú lo activas con un toque en Telegram («Activar campaña», con miniaturas); registra la activación, el veto y las renovaciones cada 48 h en la misma ABO (`trovefy montar …`).

Si el usuario pide algo que no aparece aquí, dile que todavía no está disponible en esta versión. No inventes comandos.
