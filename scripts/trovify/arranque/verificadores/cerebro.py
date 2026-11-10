"""Paso 01: el cerebro está construido, es coherente y pasa sus canarios."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores import base, verificador
from trovify.cerebro import canarios, destilado
from trovify.vault.escritura import ZONA_NEGOCIO
from trovify.vault.lint import lint
from trovify.vault.rutas import vault_root

MAX_DIAS = 30
_CANARIOS = "corre `trovify cerebro canarios` dentro del vault"


def _falla(motivo: str, arreglo: str, evidencia: list[str] | None = None) -> ResultadoVerificacion:
    return ResultadoVerificacion(False, evidencia or [], motivo, [arreglo], {}, [f"✗ {motivo}"])


@verificador("01")
def verificar_cerebro(vault: Path | None = None) -> ResultadoVerificacion:
    vault = vault_root() if vault is None else Path(vault)
    if not vault.is_dir():
        return _falla(f"no existe el vault en {vault}", "crea el vault con `trovify vault init` y vuelve a verificar")
    problemas = lint(vault)
    if problemas:
        return _falla(
            f"el vault tiene {len(problemas)} problemas de lint (p. ej. {problemas[0].ruta}: {problemas[0].detalle})",
            "corre `trovify vault lint` y corrige lo que señala",
        )
    ultimo = vault / "data" / "canarios" / "ultimo.json"
    if not ultimo.is_file():
        return _falla("no hay resultado de canarios (data/canarios/ultimo.json)", _CANARIOS)
    paginas = destilado._paginas_metodo(vault)
    if not paginas:
        return _falla("no hay páginas del método en wiki/metodo/", "destila el método con `trovify cerebro destilar` (/trovify:destilar)")
    invalidas = destilado.validar_todo(vault)
    if invalidas:
        return _falla(
            f"{len(invalidas)} problemas en wiki/metodo/ (p. ej. {invalidas[0]})",
            "corrige las citas y fuentes de esas páginas y vuelve a verificar",
        )
    try:
        datos = json.loads(ultimo.read_text(encoding="utf-8"))
        fecha = datetime.strptime(str(datos["fecha"]), "%Y-%m-%d").date()
    except (OSError, ValueError, KeyError, TypeError):
        return _falla("data/canarios/ultimo.json está ilegible o incompleto", _CANARIOS)
    if not isinstance(datos, dict) or datos.get("todos_ok") is not True:
        return _falla("los canarios no pasaron todos", _CANARIOS + " y corrige las respuestas que fallan")
    if fecha < datetime.now(ZONA_NEGOCIO).date() - timedelta(days=MAX_DIAS):
        return _falla(f"los canarios son de hace más de {MAX_DIAS} días ({fecha})", _CANARIOS)
    try:
        esperados = [c.id for c in canarios.cargar()]
        sha = canarios.sha256_de()
    except (OSError, ValueError, TypeError) as exc:
        return _falla(f"no se pudo leer el canarios.yaml canónico: {exc}", "revisa tests/canarios.yaml del repo")
    if datos.get("ids") != esperados:
        return _falla("los ids de los canarios del resultado no son los del canarios.yaml actual", _CANARIOS)
    if datos.get("canarios_sha256") != sha:
        return _falla("el sha del canarios.yaml cambió desde la última corrida", _CANARIOS)
    rel_ultimo = ultimo.relative_to(vault).as_posix()
    ruta = base.guardar_evidencia(vault, "01", "cerebro", {"ultimo": rel_ultimo, "paginas_metodo": len(paginas)})
    return ResultadoVerificacion(
        True, [rel_ultimo, ruta], "cerebro coherente y canarios al día", [], {},
        [f"✓ {len(paginas)} páginas del método válidas", f"✓ canarios ok ({fecha})"],
    )
