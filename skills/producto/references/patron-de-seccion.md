# Patrón de sección del entregable

Cada sección del PDF es un archivo `<pieza>/fuente/secciones/NN-<tema>.html` (NN = 01, 02…: da el orden). Es un **fragmento**: sin `<html>`, `<head>`, `<style>`, `<script>` ni comentarios. Lo escribes tú con tus palabras; el material de la referencia es dato y nunca se copia. Adaptado de dp-createur (MIT, `0cf80efa`).

## Forma

```html
<h2>Título de la sección</h2>
<div class="lograr"><p>Al terminar esta sección sabrás … (una o dos frases, un resultado concreto).</p></div>
<h3>Primer paso</h3>
<p>…</p>
<h3>Segundo paso</h3>
<p>…</p>
<h3>Tercer paso</h3>
<p>…</p>
<div class="ejercicio"><p>Hazlo ahora: …</p></div>
<div class="recordar"><p>Para recordar: … (la idea que se lleva el lector).</p></div>
```

Lo que comprueban los gates (`trovefy producto gates`):

- **Un `h2`** al principio: es el título del índice.
- **«Qué vas a lograr»** (`div.lograr`) justo después del `h2`.
- **De 3 a 7 `h3`** por sección.
- **«Para recordar»** (`div.recordar`) al final.
- **Palabras**: al menos las de `plan.seccion_palabras_min` (`config/producto.yaml`). Si faltan, enriquece con un ejemplo, un caso o un ejercicio; nunca repitas párrafos ni metas relleno.
- **Práctica**: nunca dos secciones seguidas sin una `div.plantilla`, `div.ejercicio` o una ficha.
- **Cifras**: cada número con `%`, «por ciento» o similar cita su fuente: `<a class="fuente" href="#fuente-1">[1]</a>`, y `fuente/fuentes.html` trae `<h2>Fuentes</h2><ol><li id="fuente-1">…</li></ol>` (el título, en el idioma del país). Sin fuente, no hay cifra.
- **Promesas**: nada de «cura», «garantizado», «sin esfuerzo», «gana X al mes». Con exigencia `sanitario`, `fuente/aviso-salud.html` explica en el idioma del país que no es un tratamiento y cuándo ir al médico (mínimo 8 palabras).
- **Sin recursos de fuera**: `img` solo con `src="medios/<archivo>"` del manifiesto de esa pieza, `a` solo con `href="#id"`. Nada de `http`, `style`, `script` ni `<link>`.

Etiquetas admitidas: `h2 h3 h4 p ul ol li strong em blockquote table thead tbody tr th td figure figcaption img a aside div span br sup`. Atributos: `class id href src alt`.

## Fichas imprimibles (kits)

Una ficha por archivo, `<pieza>/fuente/fichas/<id>.yaml`. Va en su propia página A4 y nunca se recorta: si no cabe, la maqueta la marca como desborde.

```yaml
id: diario
titulo: Diario de sueño
instrucciones: Cada mañana, anota a qué hora te acostaste y cuántos minutos tardaste en dormirte.
imagen: f-01         # opcional: id de una ilustración de medios/medios.json de esta pieza
tipo: tabla          # tabla | lineas | casillas
columnas: [Día, Hora, Minutos]
filas: 7             # en casillas, también la lista de textos de cada casilla
notas: Notas         # opcional: etiqueta del área de notas, en el idioma del producto
```

- `imagen` (opcional) ilustra la ficha: va entre las instrucciones y la tabla, las líneas o las casillas, como `<figure class="ficha-img">` con el título de la ficha de `alt`. Es el id de una imagen ya generada para **esa misma pieza** (`f-01`, `f-02`… en `entregable/imagenes.yaml`, ver `imagenes.md`). Si el id no está en `medios/medios.json` de la pieza, el ensamblado falla y lo nombra: genérala primero o quita la línea.
- La imagen se acota a unos 115 mm de alto, centrada y sin deformar: cabe con 5 casillas. Aun así, imagen y tabla comparten una página fija: con muchas filas, la maqueta lo marca como desborde; entonces quita filas o parte la ficha en dos.
- `notas` (opcional) añade, debajo de la tabla, las líneas o las casillas, un área de notas con líneas para escribir que llena el resto de la página hasta el pie. El valor es su etiqueta y va **en el idioma del producto** (`Notas`, `Notes`, `Бележки`…). Sin `notas` no hay área de notas. Úsala sobre todo en las fichas de `casillas`, que si no dejan media página en blanco.
- Una `tabla` sin `imagen` y con pocas filas (hasta 8, o hasta 12) lleva filas más altas para llenar la página; no hace falta inflar `filas`.
- Cada ficha lleva su número de página al pie, como las páginas de texto.

Las secciones van seguidas, sin salto de página entre una y otra (un `h2` nunca se queda solo al pie, y `div.ejercicio`, `div.recordar`, `div.lograr` y `div.plantilla` no se parten). El índice, con el título de la pieza y el número de página de cada apartado, y el aviso de salud comparten página con el principio del primer apartado. Solo la portada, cada ficha y las fuentes empiezan página.

## Tono

El de `BRANDBOOK.md` (tú o usted, cercano o formal), en el idioma del país y con sus precios y su moneda. Frases cortas. Ejemplos de la vida del avatar de `FICHA.md`. Ninguna reseña ni testimonio inventado.
