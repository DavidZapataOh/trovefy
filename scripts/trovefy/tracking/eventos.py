"""Test Events por el MCP de Meta, solo lectura (plan 19, Tarea 8; §4.9; D-17).

**Qué hacen los vídeos:** Claude comprueba «píxel correcto en landing y checkout» (V1 1:14:15) y no se lanza sin
píxel y checkout verificados (V2 0:19:45). Contar los cuatro eventos y exigir Purchase exactamente una vez por
pedido es más que los vídeos (desvío aprobado: solo lectura, coste cero, no cambia lo que ve el comprador).

Claude llama ``ads_get_dataset_stats`` (``aggregation: event``) antes y después de la demo y la compra de prueba, y
``ads_get_dataset_details`` después; guarda las respuestas crudas fuera del vault y esta parte solo cuenta. Nunca se
escribe en Meta (``ads_pixel_event_read`` está clasificada como escritura y no se usa). Respaldo: una captura de
«Probar eventos» que pega el usuario (clave ``test-events``), registrada después de la lectura «antes».

Revisión T6–10: la diferencia se hace por cubo (``start_time``), porque la ventana de las estadísticas se desliza
(M1); una respuesta con más páginas (``paging.next``) es «no medido»; la CAPI se da por vista solo con
``server_last_fired_time`` del mismo dataset y posterior a la lectura «antes» (M2), y sin ella no hay
``verificado`` (H1, ruling: la CAPI es obligatoria).
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from trovefy.tracking.dataset import desenvolver
from trovefy.tracking.modelo import EVENTOS, eventos_exigidos

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


def hora(valor: object) -> datetime | None:
    """Una hora ISO 8601 con zona (``2026-11-17T10:00:00+0000`` o ``…+00:00``); ``None`` si no lo es."""
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    for formato in (None, "%Y-%m-%dT%H:%M:%S%z"):
        try:
            h = datetime.fromisoformat(texto) if formato is None else datetime.strptime(texto, formato)
        except ValueError:
            continue
        return h if h.utcoffset() is not None else None
    return None


def _datos(instantanea: object) -> list | None:
    """La lista ``data`` de la respuesta; ``None`` si la forma no es la esperada o hay más páginas (``paging.next``):
    una respuesta a medias contaría de menos."""
    datos = desenvolver(instantanea)
    if isinstance(datos, dict):
        paging = datos.get("paging")
        if isinstance(paging, dict) and paging.get("next"):
            return None
        # Forma de la API de Graph (``data``) o la del MCP oficial de Meta (``stats``, 2026-11-18).
        datos = datos.get("data") if "data" in datos else datos.get("stats")
    return datos if isinstance(datos, list) else None


def _sumar(filas: object, total: dict[str, int]) -> bool:
    if not isinstance(filas, list):
        return False
    for fila in filas:
        e = _entrada(fila) if isinstance(fila, dict) else False
        if not e:
            return False
        if e[0] in total:
            total[e[0]] += e[1]
    return True


def cubos_de_eventos(instantanea: object) -> dict[datetime, dict[str, int]] | None:
    """Conteo por cubo (``start_time``) y evento (solo los cuatro de §4.9) de ``ads_get_dataset_stats``;
    ``None`` si la forma no es la esperada, hay más páginas, un cubo no trae su hora o un conteo no es un entero
    ≥ 0."""
    datos = _datos(instantanea)
    if datos is None:
        return None
    cubos: dict[datetime, dict[str, int]] = {}
    for cubo in datos:
        if not isinstance(cubo, dict):
            return None
        inicio = hora(cubo.get("start_time", cubo.get("timestamp")))
        if inicio is None or inicio in cubos:
            return None
        cubos[inicio] = dict.fromkeys(EVENTOS, 0)
        if not _sumar(cubo.get("data"), cubos[inicio]):
            return None
    return cubos


def contar_eventos(instantanea: object) -> dict[str, int] | None:
    """Suma por evento (solo los cuatro de §4.9) de una respuesta de ``ads_get_dataset_stats``; ``None`` si la
    forma no es la esperada, hay más páginas o algún conteo no es un entero ≥ 0."""
    datos = _datos(instantanea)
    if datos is None:
        return None
    total = dict.fromkeys(EVENTOS, 0)
    for cubo in datos:
        if not isinstance(cubo, dict):
            return None
        if not _sumar(cubo.get("data") if isinstance(cubo.get("data"), list) else [cubo], total):
            return None
    return total


def diferencia(antes: dict[datetime, dict[str, int]] | None,
               despues: dict[datetime, dict[str, int]] | None) -> dict[str, int] | None:
    """Lo que llegó entre dos lecturas por cubo (`cubos_de_eventos`).

    La ventana de ``ads_get_dataset_stats`` se desliza: los cubos viejos salen y entran otros nuevos. Solo cuentan
    los cubos de «después» desde el más nuevo de «antes» (ese, restando lo que ya tenía); los anteriores son de
    antes de la prueba. ``None`` si falta una lectura, si «después» perdió el cubo más nuevo de «antes» o si algún
    conteo baja."""
    if antes is None or despues is None:
        return None
    resta = dict.fromkeys(EVENTOS, 0)
    if antes:
        ultimo = max(antes)
        if ultimo not in despues:
            return None
        cubos = [c for c in despues if c >= ultimo]
    else:
        cubos = list(despues)
    for c in cubos:
        for e in EVENTOS:
            n = despues[c].get(e, 0) - antes.get(c, {}).get(e, 0)
            if n < 0:
                return None
            resta[e] += n
    return resta


def evaluar_eventos(conteo: dict[str, int] | None, pedidos_de_prueba: int = 1,
                    emisores: dict | None = None) -> tuple[Veredicto, list[str]]:
    """``verificado`` si llegaron los eventos exigidos y Purchase == pedidos; Purchase de más o de menos (sin ser 0)
    es ``no_verificado``; un evento exigido que no llegó es ``no_medido``.

    Con `emisores` (la tabla evento → emisor de ``TRACKING.md``) no se exige lo que su emisor no envía nunca
    (`trovefy.tracking.modelo.eventos_exigidos`: ViewContent con la tienda de Impultienda)."""
    if isinstance(pedidos_de_prueba, bool) or not isinstance(pedidos_de_prueba, int) or pedidos_de_prueba < 1:
        raise ValueError("pedidos de prueba: un entero de 1 o más")
    if conteo is None:
        return "no_medido", ["no medido: la respuesta de Meta no tiene la forma esperada (o las ventanas no casan)"]
    faltan = [e for e in eventos_exigidos(emisores) if not conteo.get(e)]
    purchase = conteo.get("Purchase") or 0
    if purchase > pedidos_de_prueba:
        return "no_verificado", [(f"no verificado: Purchase duplicado ({purchase} para {pedidos_de_prueba} "
                                  f"pedido{'s' if pedidos_de_prueba > 1 else ''})")]
    if faltan:
        return "no_medido", [f"no medido: {e} no llegó" for e in faltan]
    if purchase < pedidos_de_prueba:
        return "no_verificado", [f"no verificado: faltan Purchase ({purchase} para {pedidos_de_prueba} pedidos)"]
    return "verificado", []


def capi_en_meta(instantanea: object, dataset_id: str, desde: datetime) -> bool | None:
    """¿Llegan eventos del servidor (API de conversiones) a ese dataset después de `desde` (la lectura «antes»)?

    Solo se miran dos claves de la respuesta de ``ads_get_dataset_details``: ``id`` (tiene que ser `dataset_id`) y
    ``server_last_fired_time``. ``True`` si esa hora es posterior a `desde`; ``False`` si está vacía o es anterior;
    ``None`` («no medido») si la respuesta es de otro dataset, no trae esas claves o la hora no se entiende."""
    datos = desenvolver(instantanea)
    if isinstance(datos, dict) and isinstance(datos.get("metadata"), dict):
        datos = datos["metadata"]  # forma del MCP oficial de Meta (2026-11-18)
    if not isinstance(datos, dict) or str(datos.get("id", datos.get("dataset_id"))) != dataset_id or "server_last_fired_time" not in datos:
        return None
    valor = datos["server_last_fired_time"]
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return False
    h = hora(valor)
    if h is None:
        return None
    return h > desde
