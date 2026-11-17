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

Si el usuario pide algo que no aparece aquí, dile que todavía no está disponible en esta versión. No inventes comandos.
