"""Test Events por el MCP de Meta, solo lectura (plan 19, Tarea 8; §4.9; D-17).

**Qué hacen los vídeos:** Claude comprueba «píxel correcto en landing y checkout» (V1 1:14:15) y no se lanza sin
píxel y checkout verificados (V2 0:19:45). Contar los cuatro eventos y exigir Purchase exactamente una vez por
pedido es más que los vídeos (desvío aprobado: solo lectura, coste cero, no cambia lo que ve el comprador).

Claude llama ``ads_get_dataset_stats`` (``aggregation: event``) antes y después de la demo y la compra de prueba, y
``ads_get_dataset_details`` o ``ads_get_dataset_quality`` después; guarda las respuestas crudas fuera del vault y
esta parte solo cuenta. Nunca se escribe en Meta (``ads_pixel_event_read`` está clasificada como escritura y no se
usa). Respaldo: una captura de «Probar eventos» que pega el usuario (clave ``test-events``).
"""
from __future__ import annotations

from typing import Literal

from trovefy.tracking.dataset import desenvolver
from trovefy.tracking.modelo import EVENTOS

Veredicto = Literal["verificado", "no_verificado", "no_medido"]
_NOMBRE = ("value", "event", "event_name", "name")


def _conteo(valor: object) -> int | None:
    if isinstance(valor, bool):
        return None
    if isinstance(valor, int):
        return valor if valor >= 0 else None
    if isinstance(valor, str) and valor.strip().isdigit():
        return int(valor.strip())
    return None


def _entrada(d: dict) -> tuple[str, int] | None | bool:
    """``(evento, n)`` si `d` es una fila de conteo; ``None`` si no lo es; ``False`` si lo parece pero está rota."""
    nombre = next((d[k] for k in _NOMBRE if isinstance(d.get(k), str)), None)
    if nombre is None or "count" not in d:
        return None
    n = _conteo(d["count"])
    return False if n is None else (nombre, n)


def contar_eventos(instantanea: object) -> dict[str, int] | None:
    """Suma por evento (solo los cuatro de §4.9) de una respuesta de ``ads_get_dataset_stats``; ``None`` si la
    forma no es la esperada o algún conteo no es un entero ≥ 0."""
    datos = desenvolver(instantanea)
    if isinstance(datos, dict):
        datos = datos.get("data")
    if not isinstance(datos, list):
        return None
    total = dict.fromkeys(EVENTOS, 0)
    for cubo in datos:
        if not isinstance(cubo, dict):
            return None
        filas = cubo.get("data") if isinstance(cubo.get("data"), list) else [cubo]
        for fila in filas:
            e = _entrada(fila) if isinstance(fila, dict) else False
            if not e:
                return None
            if e[0] in total:
                total[e[0]] += e[1]
    return total


def diferencia(antes: dict[str, int] | None, despues: dict[str, int] | None) -> dict[str, int] | None:
    """Lo que llegó entre dos instantáneas; ``None`` si falta una o algún conteo baja (ventanas distintas)."""
    if antes is None or despues is None:
        return None
    resta = {e: despues.get(e, 0) - antes.get(e, 0) for e in EVENTOS}
    return None if any(n < 0 for n in resta.values()) else resta


def evaluar_eventos(conteo: dict[str, int] | None, pedidos_de_prueba: int = 1) -> tuple[Veredicto, list[str]]:
    """``verificado`` si llegaron los cuatro y Purchase == pedidos; Purchase de más o de menos (sin ser 0) es
    ``no_verificado``; un evento que no llegó es ``no_medido``."""
    if isinstance(pedidos_de_prueba, bool) or not isinstance(pedidos_de_prueba, int) or pedidos_de_prueba < 1:
        raise ValueError("pedidos de prueba: un entero de 1 o más")
    if conteo is None:
        return "no_medido", ["no medido: la respuesta de Meta no tiene la forma esperada (o las ventanas no casan)"]
    faltan = [e for e in EVENTOS if not conteo.get(e)]
    purchase = conteo.get("Purchase") or 0
    if purchase > pedidos_de_prueba:
        return "no_verificado", [(f"no verificado: Purchase duplicado ({purchase} para {pedidos_de_prueba} "
                                  f"pedido{'s' if pedidos_de_prueba > 1 else ''})")]
    if faltan:
        return "no_medido", [f"no medido: {e} no llegó" for e in faltan]
    if purchase < pedidos_de_prueba:
        return "no_verificado", [f"no verificado: faltan Purchase ({purchase} para {pedidos_de_prueba} pedidos)"]
    return "verificado", []


def _servidor(nodo: object, vistos: list[bool]) -> None:
    if isinstance(nodo, dict):
        for k, v in nodo.items():
            if "server" in str(k).lower() and not isinstance(v, (dict, list)):
                if isinstance(v, bool):
                    vistos.append(v)
                elif isinstance(v, (int, float)):
                    vistos.append(v > 0)
                elif v is None or isinstance(v, str):
                    vistos.append(bool(v and v.strip()))
            else:
                _servidor(v, vistos)
    elif isinstance(nodo, list):
        for x in nodo:
            _servidor(x, vistos)


def capi_en_meta(instantanea: object) -> bool | None:
    """``True`` si la respuesta de ``ads_get_dataset_details``/``ads_get_dataset_quality`` muestra eventos del
    servidor (API de conversiones: ``server_last_fired_time``, conteos ``server_*``); ``False`` si los campos están
    y van vacíos; ``None`` si no los trae."""
    vistos: list[bool] = []
    _servidor(desenvolver(instantanea), vistos)
    if not vistos:
        return None
    return any(vistos)
