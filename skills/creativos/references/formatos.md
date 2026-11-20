# Guiones y escenas

## `escenas.yaml`

Las imágenes nuevas que necesita la tanda (APIMart): la persona del UGC, escenas de uso, fondos.

```yaml
- id: e01
  prompt: "mujer de 40 años en su sala, luz cálida, mira a cámara; estilo foto de móvil"
  proporcion: "9:16"          # 9:16 para vídeo, 4:5 para estáticos
  referencias: [mockup]       # solo medios propios del entregable
```

## Guion de un estático (`guiones/ADnn.yaml`)

```yaml
formato: mockup
fondo: {tipo: mockup, ref: mockup}        # color | escena | ficha | mockup | portada
bloques:
  - {texto: "Три стъпки за спокоен сън", rol: gancho, posicion: arriba}
  - {texto: "само 13,90 €", rol: precio, posicion: abajo}
```

## Guion de un vídeo (`guiones/ADnn.yaml`)

Todos los vídeos llevan voz, música, subtítulos karaoke y un clip corto de gancho. Duran de 20 a 30 s (gancho + segmentos + cierre). Cada parte tiene su trozo de voz, que no puede durar más que su tramo.

```yaml
plantilla: broll_voz
gancho: "Не можеш да заспиш вечер?"      # texto grande los 3 primeros segundos
clip_gancho: {prompt: "reloj a las 3 de la mañana, primer plano", segundos: 3}
segmentos:
  - texto_voz: "Мислите не спират…"
    texto_pantalla: "Мислите не спират"
    clip: {prompt: "ventana de noche, ciudad en calma", tipo: texto}
    segundos: 5
cierre: {texto: "Ruta Calma 3R · 13,90 €", cta: "Натисни бутона отдолу", segundos: 3,
         texto_voz: "Само тринадесет евро и деветдесет цента. Натисни бутона отдолу."}
voz: true
```

| Plantilla | Qué lleva cada segmento | De dónde sale |
|---|---|---|
| `broll_voz` | `clip` (los clips se cortan cada 1,5 s) | L2 16:01 |
| `ugc` | `clip` con `tipo: imagen, ref: <persona de escenas.yaml>`: habla con su trozo de voz | L2 16:01 |
| `claymation` | `clip` de plastilina en stop-motion; personifica al villano | L2 16:01 |
| `3d` | 4 segmentos (capítulos), cada uno con su `clip` 3D tipo Pixar | L2 16:01 |
| `scroll_pdf` | `paginas: [n, …]` del PDF vigente | L2 16:10 |
| `zoom_lento` | `imagen: <id propio>` con zoom lento, tras el clip de gancho | L1 56:40 |
| `objeto_que_habla`, `cara_en_circulo`, `pantalla_dividida`, `antes_despues` | `clip` o `imagen` | L2 16:10 |

El precio, en la voz, va en palabras; en pantalla, con cifras y el formato del país.
