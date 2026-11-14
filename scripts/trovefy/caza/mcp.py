"""Lote y lector de las respuestas del MCP oficial ``ads_library_search`` (forma confirmada el 2026-11-14, P-01).

Claude llama a la herramienta del MCP y guarda lo que devolvió, sin tocar, en un *lote*; este módulo
lo lee. Regla: si la respuesta no tiene la forma esperada es «no medido», nunca un número inventado ni
un cambio silencioso de fuente. Nada del texto de los anuncios se interpreta como orden.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from trovefy.caza.biblioteca import url_biblioteca
from trovefy.caza.modelo import AnuncioBiblioteca, Parseo, ResultadoBusqueda
from trovefy.caza.parser import FormatoDesconocido
from trovefy.secretos import buscar_secreto

FORMA = "forma confirmada el 2026-11-14 (P-01); si no coincide, vuelve a «no medido»"
MOTIVO_FORMA = "no medido: la respuesta del MCP no tiene la forma esperada (P-01)"
MOTIVO_FUERA = "no medido: búsqueda fuera del lote del MCP"
_MAX_BYTES = 20 * 1024 * 1024


class LoteInvalido(ValueError):
    """El lote del MCP no se puede aceptar."""


# Códigos de Graph que son límite o bloqueo de Meta (como en la vía pública) y estados HTTP de límite.
_CODIGOS_LIMITE = frozenset({4, 17, 32, 613})
_HTTP_LIMITE = frozenset({403, 429})


class ErrorMcp(Exception):
    """La respuesta guardada en el lote es un error de Meta o del MCP, no un listado.

    ``bloqueado`` es True con un límite de Meta (códigos 4, 17, 32, 613 o HTTP 403/429): es una parada.
    El motivo nunca copia el mensaje de Meta."""

    def __init__(self, bloqueado: bool, motivo: str):
        super().__init__(motivo)
        self.bloqueado = bloqueado
        self.motivo = motivo


def _entero(v: Any) -> int | None:
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def _comprobar_error(obj: dict) -> None:
    err = obj.get("error")
    if not err:
        return
    datos = err if isinstance(err, dict) else {}
    codigo = _entero(datos.get("code"))
    http = next(
        (h for h in (_entero(d.get(k)) for d in (datos, obj) for k in ("http_status", "status_code", "status"))
         if h is not None),
        None,
    )
    if codigo in _CODIGOS_LIMITE or http in _HTTP_LIMITE:
        detalle = f"código {codigo}" if codigo in _CODIGOS_LIMITE else f"HTTP {http}"
        raise ErrorMcp(True, f"Meta limitó las consultas del MCP ({detalle})")
    detalle = f" (código {codigo})" if codigo is not None else ""
    raise ErrorMcp(False, f"no medido: el MCP devolvió un error de Meta{detalle}")


@dataclass(frozen=True)
class BusquedaMcp:
    pais: str
    q: str | None
    page_id: str | None
    estado: Literal["active", "all"]
    capturado_en: datetime
    respuesta: object


def _norm(q: str | None) -> str | None:
    q = q.strip().casefold() if isinstance(q, str) else None
    return q or None


def cargar_lote(ruta: Path) -> list[BusquedaMcp]:
    ruta = Path(ruta)
    try:
        if ruta.stat().st_size > _MAX_BYTES:
            raise LoteInvalido("el lote pesa más de 20 MB")
        texto = ruta.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoteInvalido(f"no se puede leer el lote: {exc.strerror}") from exc
    if buscar_secreto(texto):
        raise LoteInvalido("el lote contiene un secreto; no se acepta")
    try:
        datos = json.loads(texto)
    except ValueError as exc:
        raise LoteInvalido("el lote no es JSON") from exc
    if not isinstance(datos, dict) or not str(datos.get("herramienta", "")).endswith("__ads_library_search"):
        raise LoteInvalido("el lote no es de la herramienta ads_library_search")
    busquedas = datos.get("busquedas")
    if not isinstance(busquedas, list):
        raise LoteInvalido("el lote no trae «busquedas»")
    salida: list[BusquedaMcp] = []
    for b in busquedas:
        if not isinstance(b, dict):
            raise LoteInvalido("búsqueda que no es un objeto")
        pais, q, pid = b.get("pais"), b.get("q"), b.get("page_id")
        if not isinstance(pais, str) or not re.fullmatch(r"[A-Z]{2}|ALL", pais):
            raise LoteInvalido("búsqueda sin país válido")
        q = q if isinstance(q, str) and q.strip() else None
        pid = pid if isinstance(pid, str) and pid else None
        if q is None and pid is None:
            raise LoteInvalido("búsqueda sin q ni page_id")
        estado = b.get("estado", "active")
        if estado not in ("active", "all"):
            raise LoteInvalido("estado inválido")
        try:
            cap = datetime.fromisoformat(str(b.get("capturado_en")))
        except ValueError as exc:
            raise LoteInvalido("capturado_en no es una fecha ISO") from exc
        if cap.tzinfo is None:
            cap = cap.replace(tzinfo=UTC)
        salida.append(BusquedaMcp(pais, q, pid, estado, cap, b.get("respuesta")))
    return salida


def consultas_del_lote(lote: list[BusquedaMcp]) -> list[tuple[str, str]]:
    return [(b.pais, b.q) for b in lote if b.page_id is None and b.q]


def _desenvolver(respuesta: object) -> dict:
    obj = respuesta
    if isinstance(obj, dict) and obj.get("isError") is True:
        raise ErrorMcp(False, "no medido: el MCP devolvió un error")
    if isinstance(obj, dict) and isinstance(obj.get("content"), list):
        textos = [c.get("text") for c in obj["content"] if isinstance(c, dict) and c.get("type") == "text"]
        if len(textos) != 1 or not isinstance(textos[0], str):
            raise FormatoDesconocido("content sin un único texto")
        try:
            obj = json.loads(textos[0])
        except ValueError as exc:
            raise FormatoDesconocido("el texto no es JSON") from exc
    elif isinstance(obj, dict) and isinstance(obj.get("structuredContent"), dict):
        obj = obj["structuredContent"]
    if not isinstance(obj, dict):
        raise FormatoDesconocido("la respuesta no es un objeto")
    # Forma real (2026-11-14): {"results": "<JSON en texto>", "client_conversation_id": ...}
    if isinstance(obj.get("results"), str) and "data" not in obj and "ads" not in obj:
        try:
            obj = json.loads(obj["results"])
        except ValueError as exc:
            raise FormatoDesconocido("results no es JSON") from exc
        if not isinstance(obj, dict):
            raise FormatoDesconocido("results no es un objeto")
    _comprobar_error(obj)
    return obj


def _fecha(valor: Any, campo: str) -> date:
    if isinstance(valor, str) and re.fullmatch(r"\d{9,}(\.\d+)?", valor.strip()):
        valor = float(valor.strip())
    if isinstance(valor, (int, float)) and not isinstance(valor, bool) and valor > 0:
        try:
            return datetime.fromtimestamp(valor, UTC).date()
        except (OverflowError, OSError, ValueError) as exc:
            raise FormatoDesconocido(f"{campo} no es una fecha") from exc
    if not isinstance(valor, str) or not valor:
        raise FormatoDesconocido(f"falta {campo}")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", valor):
        return date.fromisoformat(valor)
    try:
        dt = datetime.fromisoformat(valor)
    except ValueError as exc:
        raise FormatoDesconocido(f"{campo} no es una fecha") from exc
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC)
    return dt.date()


def _id(valor: Any, campo: str) -> str:
    if isinstance(valor, int) and not isinstance(valor, bool):
        valor = str(valor)
    if not isinstance(valor, str) or not valor:
        raise FormatoDesconocido(f"falta {campo}")
    return valor


def _primero(valor: Any) -> str | None:
    if valor is None:
        return None
    if not isinstance(valor, list):
        raise FormatoDesconocido("se esperaba una lista")
    return next((v for v in valor if isinstance(v, str) and v), None)


def _anuncio(a: Any, pais: str, estado_busqueda: str = "active") -> AnuncioBiblioteca:
    if not isinstance(a, dict):
        raise FormatoDesconocido("anuncio que no es un objeto")
    plataformas = a.get("publisher_platforms", [])
    if plataformas is None:
        plataformas = []
    if not isinstance(plataformas, list):
        raise FormatoDesconocido("publisher_platforms no es una lista")
    cuerpos = a.get("ad_creative_bodies")
    texto = _primero(cuerpos) or ""
    if "ad_creative_link_titles" in a:
        titulo = _primero(a["ad_creative_link_titles"])
    else:
        t = a.get("ad_creative_link_title")
        if t is not None and not isinstance(t, str):
            raise FormatoDesconocido("ad_creative_link_title no es texto")
        titulo = t or None
    inicio = _fecha(a.get("ad_delivery_start_time"), "ad_delivery_start_time")
    stop = a.get("ad_delivery_stop_time")
    fin = _fecha(stop, "ad_delivery_stop_time") if stop else None
    estado = a.get("ad_active_status")
    if isinstance(estado, str):
        activo = estado == "ACTIVE"
    elif "ad_delivery_stop_time" in a:
        activo = stop in (None, "")
    else:  # forma real: sin estado ni fin; la búsqueda ACTIVE solo devuelve activos
        activo = estado_busqueda == "active"
    cuenta = a.get("collation_count")
    if cuenta is not None and (isinstance(cuenta, bool) or not isinstance(cuenta, int)):
        raise FormatoDesconocido("collation_count no es entero")
    col = a.get("collation_id")
    return AnuncioBiblioteca(
        library_id=_id(a.get("id"), "id"),
        page_id=_id(a.get("page_id"), "page_id"),
        page_name=_id(a.get("page_name"), "page_name"),
        inicio=inicio,
        fin=fin,
        activo=activo,
        plataformas=tuple(str(p) for p in plataformas),
        texto=texto,
        titulo=titulo,
        enlace_destino=_primero(a.get("ad_creative_link_urls")),
        collation_id=_id(col, "collation_id") if col not in (None, "") else None,
        collation_count=cuenta,
        pais=pais,
    )


def parsear_mcp(respuesta: object, pais: str, estado: str = "active") -> Parseo:
    cuerpo = _desenvolver(respuesta)
    data = cuerpo.get("data") if "data" in cuerpo else cuerpo.get("ads")
    if not isinstance(data, list):
        raise FormatoDesconocido("data no es una lista")
    anuncios: list[AnuncioBiblioteca] = []
    descartados = 0
    for a in data:
        try:
            anuncios.append(_anuncio(a, pais, estado))
        except FormatoDesconocido:
            descartados += 1
    if data and not anuncios:
        raise FormatoDesconocido("ninguna entrada válida")
    paging = cuerpo.get("paging")
    hay_mas = bool(isinstance(paging, dict) and paging.get("next")) if paging is not None else None
    total = cuerpo.get("total_count")
    total = total if isinstance(total, int) and not isinstance(total, bool) else None
    return Parseo(anuncios, descartados, total, hay_mas)


class ClienteMcp:
    """Sirve las búsquedas del lote con la misma interfaz que el cliente público."""

    def __init__(self, lote: list[BusquedaMcp], respaldo=None):
        self._lote = {(b.pais, _norm(b.q), b.page_id, b.estado): b for b in lote}
        self.respaldo = respaldo
        self.presupuesto = getattr(respaldo, "presupuesto", None)
        self.faltan: list[dict] = []

    def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60, completa=False) -> ResultadoBusqueda:
        b = self._lote.get((pais, _norm(q), page_id, estado))
        if b is None:
            if self.respaldo is not None:
                return self.respaldo.buscar(
                    pais, q=q, page_id=page_id, estado=estado, max_anuncios=max_anuncios, completa=completa
                )
            self.faltan.append({"pais": pais, "q": q, "page_id": page_id, "estado": estado})
            return ResultadoBusqueda(
                "error", url_biblioteca(pais, q, page_id, estado), None, [], MOTIVO_FUERA,
                datetime.now(UTC), via="mcp",
            )
        url = url_biblioteca(pais, b.q, b.page_id, estado)
        try:
            p = parsear_mcp(b.respuesta, pais, b.estado)
        except ErrorMcp as exc:
            estado = "bloqueado" if exc.bloqueado else "error"
            return ResultadoBusqueda(estado, url, None, [], exc.motivo, b.capturado_en, via="mcp")
        except FormatoDesconocido:
            return ResultadoBusqueda("error", url, None, [], MOTIVO_FORMA, b.capturado_en, via="mcp")
        completo = p.hay_mas is False and p.descartados == 0
        anuncios = p.anuncios[:max_anuncios]
        completo = completo and len(anuncios) == len(p.anuncios)
        total = p.total_json if p.total_json is not None else (len(anuncios) if completo else None)
        return ResultadoBusqueda(
            "ok" if anuncios else "vacio", url, total, anuncios, None, b.capturado_en,
            completo=completo, via="mcp", total_exacto=p.total_json is not None or completo,
        )
