"""Paso 11: el dataset (píxel) del producto-país creado y puesto en la tienda (plan 19, Tarea 16).

Solo LEE ``productos/*/checkout/*/TRACKING.md`` (lo escribe ``trovefy tracking``): sin red, sin navegador y sin
ningún panel (resolución 38). El paso queda bien con un dataset con id y el píxel puesto en la tienda (estado
``configurado`` o ``verificado``); los eventos y el ejecutor los exige el cierre del checkout
(`trovefy.checkout.cierre`), no este paso. Lo no medido se dice «no medido: <motivo>».
"""

from pathlib import Path

from trovefy.arranque.estado import ResultadoVerificacion
from trovefy.arranque.verificadores import verificador
from trovefy.arranque.verificadores.base import guardar_evidencia
from trovefy.tracking.salida import leer_tracking

ARREGLO = "/trovefy:tracking (trovefy tracking preparar, dataset y tienda)"
_BUENOS = ("verificado", "configurado")
_ORDEN = {"verificado": 0, "configurado": 1, "no_verificado": 2, "dataset": 3, "pendiente": 4}


def _trackings(vault: Path) -> list:
    """Los ``TRACKING.md`` legibles del vault (los rotos se saltan)."""
    salida = []
    for ruta in sorted((Path(vault) / "productos").glob("p-*/checkout/*/TRACKING.md")):
        producto, pais = ruta.parents[2].name, ruta.parent.name
        try:
            t = leer_tracking(vault, producto, pais)
        except (OSError, ValueError):
            continue
        if t is not None:
            salida.append(t)
    return salida


def _datos(t) -> dict[str, str]:
    return {"dataset_id": t.dataset_id or "", "dataset_nombre": t.dataset_nombre, "producto": t.producto,
            "pais": t.pais, "estado": t.estado}


@verificador("11")
def verificar_dataset(vault: Path) -> ResultadoVerificacion:
    trackings = _trackings(vault)
    if not trackings:
        motivo = "no medido: aún no hay TRACKING.md de ningún producto-país (lo crea /trovefy:tracking)"
        return ResultadoVerificacion(None, [], motivo, [ARREGLO], {}, [f"? {motivo}"])
    t = min(trackings, key=lambda x: (x.dataset_id is None, _ORDEN.get(x.estado, 9), x.producto, x.pais))
    if t.dataset_id is None:
        motivo = f"falta el dataset de {t.producto} {t.pais}: créalo en Meta con el nombre «{t.dataset_nombre}»"
        return ResultadoVerificacion(False, [], motivo, [ARREGLO], {}, [f"✗ {motivo}"])
    datos = _datos(t)
    if t.estado not in _BUENOS:
        motivo = (f"dataset {t.dataset_id} de {t.producto} {t.pais} en estado «{t.estado}»: el píxel aún no está "
                  "visto en tu tienda (pega el Pixel ID en «Meta / Tracking» de tu panel y trovefy tracking tienda)")
        return ResultadoVerificacion(False, [], motivo, [ARREGLO], datos, [f"✗ {motivo}"])
    ev = guardar_evidencia(vault, "11", "dataset", {**datos, "motivos": list(t.motivos)})
    motivo = f"dataset «{t.dataset_nombre}» ({t.dataset_id}) de {t.producto} {t.pais}: {t.estado}"
    pendientes = [m.split(": ", 1)[1] if m.startswith("eventos: ") else m for m in t.motivos
                  if "no medido" in m or "no verificado" in m]
    if pendientes:
        motivo += "; " + "; ".join(pendientes)
    rel = Path("productos") / t.producto / "checkout" / t.pais / "TRACKING.md"
    return ResultadoVerificacion(True, [rel.as_posix(), ev], motivo, [], datos, [f"✓ {motivo}"])
