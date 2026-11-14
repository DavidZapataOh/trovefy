# claude-video (vendorizado tal cual)

- Repo: `bradautomates/claude-video` (https://github.com/bradautomates/claude-video)
- Commit: `03ceb42f7fa2c4439aca01752118044baabffb8f` (2026-09-25)
- Licencia: MIT (ver `LICENSE`)
- Fecha de copia: 2026-11-13
- Copia sin modificar: los archivos se copiaron con `cp` y `MANIFEST.sha256` (`sha256sum`, rutas relativas a esta carpeta) vigila su integridad mediante `tests/unit/referencia/test_vendor.py`.

## Archivos incluidos

- `LICENSE`
- `skills/watch/scripts/watch.py`
- `skills/watch/scripts/config.py`
- `skills/watch/scripts/download.py`
- `skills/watch/scripts/frames.py`
- `skills/watch/scripts/gemini.py`
- `skills/watch/scripts/local_whisperx.py`
- `skills/watch/scripts/runtime.py`
- `skills/watch/scripts/setup.py`
- `skills/watch/scripts/transcribe.py`
- `skills/watch/scripts/whisper.py`

## Excluido y por qué

- `hooks/hooks.json` (y `hooks/scripts/check-setup.sh`): el hook `SessionStart` ejecutaría `setup.py --check` en cada sesión.
- `skills/watch/SKILL.md`: no se expone `/watch` suelto, porque por defecto usa Gemini si hay clave. Se usa solo a través de `trovefy.referencia.watch`.
- `build-skill.sh`, los tests, los manifiestos de Codex y de marketplace, el CI y el README: no hacen falta para ejecutar los scripts.

## Notas de seguridad (auditoría)

- `gemini.py` sube el vídeo a Google. Aquí nunca se invoca.
- `setup.py` descarga el instalador de uv solo si falta uv.
