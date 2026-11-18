# Qué lleva cada sección de la landing

`wireframe.yaml` dice el orden, el tipo, el largo (palabras de la referencia) y si la sección lleva botón. Aquí está qué va dentro de cada tipo. Todo con tus palabras, en el idioma del país, con el ángulo y la promesa de `OFERTA.md` y el tono de `BRANDBOOK.md`. Nunca copies frases, diseño ni imágenes de la referencia.

Cada sección del esqueleto es `<section data-tf-seccion="N" data-tf-tipo="<tipo>">` con **un solo** titular `data-tf-hito` (`h1` en la primera, `h2` en las demás). Cambia los `<!-- texto propio -->` por tu texto; no quites ni dupliques los atributos `data-tf-*`. Donde el wireframe dice `cta: true`, el botón es `<a data-tf-checkout href="…">` con el `href` que ya trae (no lo cambies).

## Los tipos

- **`hero`** — La promesa del `h1` (la de `OFERTA.md`, `promesa_h1`) en una línea clara, una frase que diga para quién es y qué consigue, y el botón si lo marca el wireframe. Es lo primero que se ve en móvil: corto, sin párrafos largos. La imagen grande, si la hay, es una propia de `assets/`.
- **`problema`** — La situación que vive el comprador, contada como él la reconocería: lo que le pasa, lo que ya probó y por qué no le funcionó. Sin exagerar ni asustar.
- **`villano`** — La causa del problema que no es culpa del comprador (un método equivocado, una costumbre, un consejo que circula). Se nombra con respeto: nunca una persona, una marca ni un profesional concreto.
- **`mecanismo`** — Por qué este producto funciona donde lo otro falló: la idea central del método, con el nombre del mecanismo de `OFERTA.md`. Explicado en pasos simples, sin promesas de resultado garantizado.
- **`que_incluye`** — Lo que recibe al comprar: el producto principal y sus partes (capítulos, fichas, ejercicios), en una lista que se lee de un vistazo. Solo lo que existe de verdad en el PDF.
- **`formato`** — Cómo es lo que compra: un PDF, cuántas páginas tiene y cómo lo recibe. El párrafo `data-tf-formato` tiene que decir «PDF» y el número **real** de páginas del PDF vigente (el que dice `trovefy landing estado`), no uno redondeado.
- **`vista_previa`** — Páginas reales del PDF para que vea lo que compra: las `img[data-tf-vista]` que deja `trovefy landing medios` (al menos 2), cada una con un `alt` que diga qué página es y una línea de contexto. Sin retocar las imágenes ni inventar páginas.
- **`prueba_social`** — Con las reseñas registradas con `trovefy landing resena` (cada una `<blockquote data-tf-resena="<id>">` con su texto exacto). Si no hay ninguna, el wireframe ya cambia esta sección por una `vista_previa` (`sustituye: prueba_social`): escríbela como vista previa. Si el usuario registra una reseña después de `preparar`, vuelve a lanzar `preparar` y cambia esa sección en el borrador.
- **`bonos`** — Los bonos de la oferta, cada uno con su título en el idioma del país y qué aporta en una o dos frases. Solo los que existen y se entregan.
- **`para_quien`** — Las personas a las que les sirve, descritas por su situación («si te pasa…»), no por edad, cuerpo ni datos sensibles.
- **`no_es_para`** — A quién no le conviene, con honestidad: quien busca otra cosa, quien necesita a un profesional. Da confianza y evita compras que acaban en devolución. Con productos de salud, incluye a quien necesita atención médica.
- **`autor`** — Quién hay detrás de la marca local de `BRANDBOOK.md` y por qué hizo el producto. Nada de títulos, credenciales, apariciones en medios ni historias que no sean ciertas; si no hay datos reales, habla de la marca y de su forma de trabajar.
- **`comparativa`** — Este producto frente a las alternativas que el comprador ya conoce (un curso caro, buscar gratis, no hacer nada), por sus características. Sin nombrar competidores y sin cifras inventadas.
- **`garantia`** — La garantía, explícita: cuántos días (los de `OFERTA.md`), qué cubre y cómo se pide (`garantia.como`; un `mailto:` vale para el soporte). El párrafo `data-tf-garantia` tiene que decir ese número de días.
- **`precio`** — El precio en la moneda del país, tal como lo deja el esqueleto en `data-tf-precio` (no lo reescribas ni lo conviertas), lo que incluye y el botón. Sin precio tachado ni «antes costaba».
- **`faq`** — Las dudas que frenan la compra, con respuesta corta: cómo lo recibo, en qué formato, cuánto dura la garantía, qué pasa si no me sirve, cómo pago. Las respuestas repiten los datos reales (páginas, días, precio), nunca otros.
- **`cta_final`** — Un cierre corto que recuerde la promesa y la garantía, y el botón.

## Reglas que valen para todas

- **Formato y páginas reales.** El formato (PDF) y el número de páginas son los del PDF vigente; si `trovefy landing estado` dice otro número, manda ese. Nunca «más de 100 páginas» ni cifras redondeadas.
- **Garantía explícita.** Los días y cómo se pide, dichos claro en la sección `garantia` y repetidos en la `faq` si hay una.
- **Precio y moneda.** Siempre los de `ESCALERA.md` para ese país, en su moneda y como se escriben allí. El checkout cobrará exactamente eso.
- **Idioma.** Todo el texto en el idioma del país, con sus diacríticos o su alfabeto, incluidos `<title>`, `description`, los `alt` y los textos de los botones. Nada de restos en español.
- **Largo.** Cerca de las palabras del wireframe; si una sección se aleja mucho, `validar` avisa. Mejor claro y corto que relleno.
- **Sin nada de fuera.** Ni fuentes, ni imágenes, ni scripts, ni iframes de otros sitios: solo lo de `assets/`. El único script es el del esqueleto.
