---
tipo: regla
id: R-006
titulo: Corte de oferta sin ventas
fecha: 2026-11-19
fuente: "C1 1:24:15 («un promedio de US$ 25»); C1 1:38:00; C1 34:25; T3 11:22; corrección del 2026-11-19 («los vídeos son la ley»)"
umbrales: [corte.oferta.sin_ventas_usd]
estado: vigente
---

# R-006 · Corte de oferta sin ventas

## Regla

Una oferta con 0 ventas se propone pausar al llegar a `corte.oferta.sin_ventas_usd` (25) US$ gastados en total desde la activación, **sin esperar ningún plazo** y a cualquier hora, también en la ronda intradía. Manda la tienda: una sola venta real la salva aunque el píxel diga 0. Con ventas, pasadas las 72 h (R-011), un ROAS neto acumulado inferior a `roas.apagar` (1,4) también corta, solo con el día cerrado.

## Por qué

Es lo que hacen los vídeos: «son $25 por producto… un promedio» (C1 1:24:15; «puede ser menos», C1 1:38:00). La regla anterior (PU-01) cortaba a min(US$ 25, 2 × CPA_BE); el factor no está en los vídeos y se quitó el 2026-11-19. Si quieres recuperarlo, dilo con `/recordar` y se repone como umbral con tus palabras.

## Cómo se aplica

`/leer` compara el gasto acumulado de la campaña (en USD, con la TRM del día del gasto) con el corte y, si la tienda no tiene ventas, deposita la propuesta de pausar la campaña con prioridad alta; la ejecuta el ejecutor tras tu Aceptar. Sin TRM el gasto es «no medido» y no se propone nada por importe. Las 72 h (R-011) solo protegen a ofertas con ventas.

## Fuente

C1 1:24:15 y C1 1:38:00; C1 34:25 y T3 11:22 para la rama con ventas.
