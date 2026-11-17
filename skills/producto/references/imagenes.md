# Imágenes del entregable: `entregable/imagenes.yaml`

Solo imágenes propias, hechas con APIMart dentro del tope de US$ 2 por producto (o que dé el usuario). Nunca imágenes de la referencia ni de internet. Cada imagen generada queda en `<pieza>/medios/` con su `sha256`, su `task_id` y su coste en `medios/medios.json`.

## Formato

Una lista; cada imagen con estos campos y ninguno más:

```yaml
- id: portada            # portada, mockup, il-01 … il-10 (minúsculas, números y guiones)
  pieza: principal       # principal, bono-N, bump, u1, u2, u3 o downsell
  prompt: >-
    Portada de un cuaderno de respiración para dormir mejor, ilustración plana en azul y arena,
    con espacio arriba para el título. Sin texto, sin letras, sin logotipos.
  proporcion: "2:3"      # 1:1 3:2 2:3 4:3 3:4 5:4 4:5 16:9 9:16 2:1 1:2 3:1 1:3 21:9 9:21
  resolucion: 1k         # la de config/producto.yaml (apimart.resolucion); todas iguales en un lote
  referencias: []        # opcional: ids de imágenes ya generadas de la misma pieza (mismo estilo)
```

## Qué pedir

- **portada** (`2:3`): la imagen de la portada del PDF. La maqueta la usa sola si existe `medios/portada.png`. Sin texto: el título lo pone la maqueta.
- **mockup** (`3:2` o `4:3`): el producto como objeto (cuaderno, tableta) para la landing. Sin texto.
- **il-01 … il-10** (6 a 10): una por sección que lo necesite. Sencillas, del mismo estilo; usa `referencias: [portada]` para que no cambie el estilo.
- Escribe el prompt en español o en inglés, nunca con la marca ni con el nombre del anunciante original. Pide siempre «sin texto».
- Personas: adultos genéricos, nunca famosos ni personas reales. Nada que parezca un antes y después ni un resultado médico.

## Coste y orden

1. `trovefy producto imagenes <p-id> --simular`: mide el precio de cada modelo de `config/producto.yaml`, elige el más barato (P-11) y anota lo que costaría sin enviar nada. Con unos US$ 0,0085 por imagen en 1k, 12 imágenes son unos US$ 0,10.
2. `trovefy producto imagenes <p-id>`: genera. Una imagen ya hecha con el mismo prompt, proporción y resolución no se paga dos veces. Si cambias el prompt de una imagen, se vuelve a generar y vuelve a costar.
3. Si el tope para el lote, el usuario decide: o sube el tope con sus palabras, o se sigue con menos imágenes.
