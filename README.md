# Trovify

Trovify es un plugin de Claude Code y un paquete Python 3.12 para operar un negocio de productos digitales.
Guarda el conocimiento del negocio en un vault aparte (`~/trovify-cerebro`, o la ruta de `TROVIFY_VAULT`); este repo nunca contiene datos del negocio.
Todo el texto que ve el usuario está en español.
La CLI `trovify` es el punto de entrada de los subcomandos que se añaden por fases.
Licencia MIT.

## Instalación

```bash
uv tool install --python 3.12 --editable .
```

## Diseño

El diseño vive fuera de este repositorio (en el espacio de trabajo del proyecto), no se incluye aquí.
