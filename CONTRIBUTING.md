# Cómo contribuir

## Entorno

```bash
uv sync                              # Python 3.12 y dependencias de desarrollo
uv run playwright install chromium   # solo para las pruebas de integración
```

## Forma de trabajo

- **TDD**: primero la prueba que falla, luego el código mínimo que la pasa, luego la limpieza.
- Las pruebas por defecto no usan red ni navegador:

  ```bash
  uv run pytest -q                  # excluye integracion y vivo
  uv run pytest -q -m integracion   # Chromium de Playwright
  uv run pytest -q -m vivo          # servicios reales; úsalo con cuidado
  ```

- Lint antes de cada commit: `uv run ruff check .`
- La CI ejecuta `uv sync --locked`, `ruff` y `pytest` en cada push y pull request a `main`.

## Reglas del proyecto

- **Todo el texto que ve el usuario va en español**: mensajes de la CLI, ayudas, skills y plantillas.
- Lo que no se midió se escribe «no medido: <motivo>», nunca 0 ni una estimación.
- Ningún dato del negocio ni ningún secreto en el repositorio: los datos viven en el vault y los secretos en `~/.config/trovify/*.env`.
- Nada de escrituras en Meta desde el código ni desde las skills.
- Si una idea viene de otro proyecto, se reescribe sin copiar código; el mantenedor registra la fuente de forma privada.

## Commits

Mensajes en español con prefijos convencionales y el área entre paréntesis:

```text
feat(caza): mide el hueco por país con frases locales
fix(auditar): ranking con notas parciales
docs: README y guía de contribución
test(hooks): meta_guard deniega escrituras por WebFetch
```

Áreas habituales: `caza`, `auditar`, `arranque`, `cerebro`, `hooks`, `cli`, `ci`.
