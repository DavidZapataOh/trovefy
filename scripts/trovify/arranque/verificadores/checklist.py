"""Pasos que se verifican con una lista de comprobaciones respondida por el usuario (paso 03).

Meta no deja leer desde fuera si un perfil es real ni si tiene 2FA, así que la evidencia es la
respuesta del usuario con su fecha. Un solo «no» o una respuesta que falte dejan el paso sin verificar.
"""

from datetime import datetime
from pathlib import Path

from trovify.arranque.estado import ResultadoVerificacion
from trovify.arranque.verificadores import verificador
from trovify.arranque.verificadores.base import guardar_evidencia
from trovify.vault.escritura import ZONA_NEGOCIO

CHECKLISTS: dict[str, dict[str, str]] = {
    "03": {
        "perfil_propio": "Es tu perfil real y propio",
        "dos_fa": "Tiene 2FA activo",
        "sin_vpn": "No vas a usar VPN el día de crear el Business",
    },
}


def verificar_checklist(vault: Path, id: str, respuestas: dict[str, bool]) -> ResultadoVerificacion:
    items = CHECKLISTS.get(id)
    if items is None:
        raise ValueError(f"el paso {id} no tiene lista de comprobaciones")
    faltan = [k for k in items if k not in respuestas]
    desconocidas = [k for k in respuestas if k not in items]
    if desconocidas:
        raise ValueError(f"respuesta desconocida: {', '.join(desconocidas)} (válidas: {', '.join(items)})")
    if faltan:
        motivo = "incompleto, faltan respuestas: " + "; ".join(f"{items[k]} ({k})" for k in faltan)
        return ResultadoVerificacion(False, [], motivo, [f"responde todas con `--respuesta {k}=si` o `=no`" for k in faltan],
                                     {}, [f"✗ {motivo}"])
    nos = [k for k in items if respuestas[k] is not True]
    lineas = [f"{'✓' if respuestas[k] else '✗'} {items[k]}" for k in items]
    if nos:
        motivo = "no se cumple: " + "; ".join(items[k] for k in nos)
        return ResultadoVerificacion(False, [], motivo, [f"arregla «{items[k]}» y vuelve a responder" for k in nos], {}, lineas)
    ahora = datetime.now(ZONA_NEGOCIO)
    rel = guardar_evidencia(vault, id, "checklist", {
        "paso": id, "fecha": ahora.strftime("%Y-%m-%d"), "respuestas": {k: respuestas[k] for k in items},
    })
    return ResultadoVerificacion(True, [rel], "las tres comprobaciones están en «sí» (palabra del usuario, fechada)", [], {}, lineas)


@verificador("03")
def verificar_03(vault: Path | None = None) -> ResultadoVerificacion:
    motivo = "no medido: responde la lista con `trovify arranque checklist 03 --respuesta perfil_propio=si --respuesta dos_fa=si --respuesta sin_vpn=si`"
    return ResultadoVerificacion(None, [], motivo, [], {}, [f"? {motivo}"])
