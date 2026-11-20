# `brief.yaml`: la ficha de la tanda

Lo escribes tú en `productos/<p-id>/creativos/<PAIS>/t<N>/brief.yaml`. `trovefy creativos brief` lo valida y escribe `TANDA.md`.

```yaml
tanda: t1
grupo: G1                      # el grupo es el número de la tanda
candidatos:                    # 20 en una tanda de test; son textos, gratis
  - id: b01
    objetivo: probar el ángulo del mecanismo        # brief de 5 líneas (§4.12): objetivo,
    audiencia: mujeres de 30 a 55 que duermen mal    #   audiencia,
    linea_ancla: dormir sin pastillas                #   línea ancla,
    tono: cercano, de tú                             #   tono
    restricciones: sin promesas de salud ni cifras    #   y restricciones
    angulo: метод в три стъпки                       # en el idioma del país
    angulo_es: método de tres pasos
    respaldo: core.mecanismo_pasos[0]                # el hecho de OFERTA.md que lo sostiene (índice desde 0)
    hook: mecanismo                                  # uno de los 7 patrones
    formato: broll_voz                               # plantilla de vídeo o formato de estático
    gancho: Три стъпки за спокоен сън                # ≤ 8 palabras, en las primeras 125 letras del texto
    texto: "Три стъпки за спокоен сън. …"            # texto principal: ≤ 500, las 125 primeras se sostienen solas
    titulo: Заспи спокойно тази вечер                # ≤ 40
    descripcion: Ръководство в PDF                   # ≤ 30
    cta: LEARN_MORE                                  # opcional; por defecto el de config/creativos.yaml
    precio_dicho: само 13,90 €                       # opcional; si se dice, el del front en el formato del país
    voz: "Три стъпки за спокоен сън. …"              # obligatorio en los vídeos: todos llevan voz
    referencias: [mockup]                            # opcional: solo medios propios
elegidos:                      # 10: 5 test y 5 reserva
  - {ad: AD01, brief: b07, uso: test, orden: 1, angulo_corto: метод в три стъпки}
```

Reglas que comprueba la CLI:

- Mezcla: la del competidor si `referencia/mezcla.md` la midió (85 % imágenes → 8 imágenes y 2 vídeos, L1 46:54); si no, 7 vídeos y 3 imágenes (C2 6:50). Con 4 vídeos o más, al menos uno de cada plantilla: `broll_voz`, `ugc`, `claymation`, `3d` (L2 16:01). El resto, los formatos que usa el competidor según `/watch`; sin dato, `scroll_pdf` y `zoom_lento`.
- Las 5 de test prueban ángulos: al menos 3 distintos, ninguno más de 2 veces, y al menos un vídeo.
- `pantalla_dividida` vale para imagen y para vídeo: di `tipo: imagen` o `tipo: video`.
- Nombre del anuncio: `ADnn GN <angulo_corto>` (≤ 30 letras en el idioma del país).

## Los 7 patrones de gancho

Método «sujeto + dolor o resultado» (L2 15:25) y los ángulos que funcionaron en Trusa (L2 3:52):

| Patrón | Qué hace |
|---|---|
| `sujeto_dolor` | Nombra a quien mira y su dolor concreto |
| `sujeto_resultado` | Nombra a quien mira y lo que consigue |
| `momento_de_uso` | El momento del día en que se usa el producto |
| `objecion` | Responde a la objeción de un bono de la oferta |
| `mecanismo` | Enseña el nombre y los pasos del mecanismo |
| `villano` | Señala al culpable del problema (no a quien mira) |
| `contraste_de_uso` | Antes y después del uso, sin prometer resultados de salud |

## Formatos de estático

`tipografico` (sin foto), `ficha_del_producto`, `mockup`, `escena`, `pantalla_dividida`, `antes_despues_del_uso`, `meme`. Cada uno es una idea distinta, como las 8 imágenes de L1 56:40.
