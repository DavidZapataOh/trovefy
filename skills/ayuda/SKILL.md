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

Si el usuario pide algo que no aparece aquí, dile que todavía no está disponible en esta versión. No inventes comandos.
