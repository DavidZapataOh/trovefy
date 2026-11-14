---
tipo: brandbook
producto: p-0042-kit-demo
fecha: '2026-11-13'
fuente: productos/p-0042-kit-demo/modelar.yaml
nombre_local: Подреден дом
idioma: bg
significado: Significa «casa ordenada» en búlgaro
paleta:
  primario: '#1F4E5F'
  secundario: '#F2C14E'
  fondo: '#FAF7F2'
tipografias:
- familia: Ubuntu
  uso: titulos
  subconjuntos:
  - latin
  - cyrillic
  licencia: Ubuntu Font Licence 1.0 (fonts-ubuntu)
- familia: Noto Sans
  uso: texto
  subconjuntos:
  - latin
  - cyrillic
  licencia: OFL 1.1 (fonts-noto-core)
tono: Cercano y práctico, frases cortas, sin culpas
iconografia: Iconos de línea fina con esquinas redondeadas
mockup: Tablet sobre una mesa de cocina con el plan abierto
tokens_css:
  --color-primario: '#1F4E5F'
  --color-acento: '#F2C14E'
  --color-fondo: '#FAF7F2'
  --fuente-titulos: '''Ubuntu'', sans-serif'
  --fuente-texto: '''Noto Sans'', sans-serif'
---
# Brandbook · Подреден дом

## 1. Nombre local

**Подреден дом** (bg). Significa «casa ordenada» en búlgaro

## 2. Paleta

- primario: `#1F4E5F`
- secundario: `#F2C14E`
- fondo: `#FAF7F2`

## 3. Tipografías

- titulos: Ubuntu (latin, cyrillic; licencia Ubuntu Font Licence 1.0 (fonts-ubuntu))
- texto: Noto Sans (latin, cyrillic; licencia OFL 1.1 (fonts-noto-core))

## 4. Tono

Cercano y práctico, frases cortas, sin culpas

## 5. Iconografía

Iconos de línea fina con esquinas redondeadas

## 6. Mockup

Tablet sobre una mesa de cocina con el plan abierto

## 7. Tokens CSS

La fuente es `tokens_css` del frontmatter; este bloque es una copia para leer.

```css
:root {
  --color-primario: #1F4E5F;
  --color-acento: #F2C14E;
  --color-fondo: #FAF7F2;
  --fuente-titulos: 'Ubuntu', sans-serif;
  --fuente-texto: 'Noto Sans', sans-serif;
}
```
