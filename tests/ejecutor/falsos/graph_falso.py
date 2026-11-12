"""Graph falso en memoria: misma interfaz pública que ``ClienteGraph``, sin red.

NO aplica el tope de gasto (spend_cap) ni presupuestos mínimos: para probar esos rechazos de Meta,
inyecta el error con ``errores`` (que dispara también en validate_only).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from trovefy_ejecutor.graph import (
    _CAMPOS_CUENTA,
    OFFSETS_META,
    DetenidoPorStop,
    ErrorGraph,
    ErrorRed,
    InfoCuenta,
    _entero,
    _seg,
    _valor,
)

CUENTA = "act_0000000000000000"
_IMPORTES = ("daily_budget", "lifetime_budget", "bid_amount", "spend_cap", "budget_remaining")
_MAX_VIDEO = 100 * 1024 * 1024


@dataclass(frozen=True)
class Llamada:
    metodo: str
    ruta: str
    datos: dict
    validate_only: bool = False


@dataclass
class GraphFalso:
    objetos: dict[str, dict] = field(default_factory=dict)
    cuentas: dict[str, dict] = field(default_factory=dict)
    llamadas: list[Llamada] = field(default_factory=list)
    forzar_pausa: set[str] = field(default_factory=set)
    errores: dict[str, ErrorGraph] = field(default_factory=dict)
    red_tras_escribir: set[str] = field(default_factory=set)
    red_al_leer: bool = False
    token_caduca_tras: int | None = None
    redondeo: dict[str, int] = field(default_factory=dict)
    stop_tras: int | None = None
    tam_pagina: int | None = None  # filas por página al listar; con max_paginas insuficiente, listado incompleto
    errores_reales: dict[str, ErrorGraph] = field(default_factory=dict)  # solo en escrituras reales
    al_escribir: Callable[[], None] | None = None  # se llama tras aplicar una escritura real

    def __post_init__(self) -> None:
        self._reales = 0  # escrituras reales ya aplicadas
        self._siguiente_id = 9000001
        self._siguiente_video = 7000001
        # id -> (arista, padres): jerarquía para ``listar``
        self.hijos: dict[str, tuple[str, set[str]]] = {}

    # -- mandos y consultas -------------------------------------------------------------
    def escrituras(self) -> list[Llamada]:
        return [x for x in self.llamadas
                if x.metodo in ("escribir", "crear", "subir_imagen", "subir_video") and not x.validate_only]

    def cambiar(self, id: str, **campos: object) -> None:
        """Edición manual entre envío y toque: no cuenta como llamada ni como escritura."""
        self.objetos[id].update({k: self._guardar(k, v) for k, v in campos.items()})

    # -- internos -----------------------------------------------------------------------
    @staticmethod
    def _guardar(clave: str, v: object) -> object:
        if v is None:
            raise ValueError("valor None no se envía a Graph")
        if clave in _IMPORTES:
            return str(int(str(v)))
        return v

    def _entrada(self, metodo: str, ruta: str, datos: dict, validate_only: bool = False) -> None:
        self.llamadas.append(Llamada(metodo, ruta, datos, validate_only))
        if self.token_caduca_tras is not None and self._reales >= self.token_caduca_tras:
            raise ErrorGraph(190, 463, "token caducado")

    def _leyendo(self, metodo: str, ruta: str, datos: dict) -> None:
        self._entrada(metodo, ruta, datos)
        if self.red_al_leer:
            raise ErrorRed("conexión")

    def _stop(self, validate_only: bool) -> None:
        """Como ``GraphConStop``: corta antes de llegar al cliente (la llamada no queda registrada)."""
        if not validate_only and self.stop_tras is not None and self._reales >= self.stop_tras:
            raise DetenidoPorStop()

    def _antes_de_escribir(self, clave: str, validate_only: bool) -> None:
        if clave in self.errores:
            raise self.errores.pop(clave)
        if not validate_only and clave in self.errores_reales:
            raise self.errores_reales.pop(clave)

    def _existe(self, id: str) -> None:
        if id not in self.objetos and id not in self.cuentas:
            raise ErrorGraph(100, 33, "Unsupported post request. Object does not exist")

    @staticmethod
    def _sin_negativos(normal: dict) -> None:
        for k, v in normal.items():
            if k in _IMPORTES and int(v) < 0:
                raise ErrorGraph(100, None, f"Invalid parameter: {k} must not be negative")

    def _despues_de_escribir(self, clave: str, validate_only: bool) -> None:
        if validate_only:
            return
        self._reales += 1
        if self.al_escribir is not None:
            self.al_escribir()
        if clave in self.red_tras_escribir:
            raise ErrorRed("conexión")

    # -- API (misma firma que ClienteGraph) ---------------------------------------------
    def leer(self, id: str, campos: Sequence[str]) -> dict:
        _seg(id)
        self._leyendo("leer", id, {"campos": list(campos)})
        origen = self.objetos.get(id)
        if origen is None:
            origen = self.cuentas.get(id)
        if origen is None:
            raise ErrorGraph(100, 33, "Unsupported get request. Object does not exist")
        salida: dict = {"id": id}
        salida.update({c: origen[c] for c in campos if c in origen and c != "id"})
        return salida

    def listar(self, padre: str, arista: str, campos: Sequence[str],
               filtros: Mapping[str, object] | None = None, max_paginas: int = 20,
               limite: int | None = None) -> list[dict]:
        _seg(padre, arista)
        for v in (filtros or {}).values():
            _valor(v)
        self._leyendo("listar", f"{padre}/{arista}",
                      {"campos": list(campos), "filtros": dict(filtros or {}), "limite": limite})
        salida = []
        for oid, (ar, padres) in self.hijos.items():
            if ar == arista and padre in padres and oid in self.objetos:
                obj = self.objetos[oid]
                permitidos = (filtros or {}).get("effective_status")
                if permitidos is not None and obj.get("effective_status") not in permitidos:
                    continue  # como Meta: lista blanca de estados
                salida.append({"id": oid, **{c: obj[c] for c in campos if c in obj and c != "id"}})
        if self.tam_pagina is not None and len(salida) > self.tam_pagina * max_paginas:
            raise ErrorRed("listado incompleto")
        return salida

    def escribir(self, id: str, datos: Mapping[str, object], *, validate_only: bool = False) -> dict:
        _seg(id)
        normal = {k: self._guardar(k, _check(v)) for k, v in datos.items()}
        self._stop(validate_only)
        self._entrada("escribir", id, dict(datos), validate_only)
        self._antes_de_escribir(id, validate_only)
        self._existe(id)
        self._sin_negativos(normal)
        if validate_only:
            return {"success": True}
        obj = self.objetos[id] if id in self.objetos else self.cuentas[id]
        tocado_importe = False
        for k, v in normal.items():
            if k in _IMPORTES and id in self.redondeo:
                v = str(self.redondeo[id])
            tocado_importe = tocado_importe or k in _IMPORTES
            obj[k] = v
        if tocado_importe and id in self.forzar_pausa:
            obj["status"] = "PAUSED"
        self._despues_de_escribir(id, validate_only)
        return {"success": True}

    def crear(self, padre: str, arista: str, datos: Mapping[str, object], *, validate_only: bool = False) -> dict:
        _seg(padre, arista)
        normal = {k: self._guardar(k, _check(v)) for k, v in datos.items()}
        self._stop(validate_only)
        self._entrada("crear", f"{padre}/{arista}", dict(datos), validate_only)
        self._antes_de_escribir(padre, validate_only)
        self._existe(padre)
        self._sin_negativos(normal)
        if validate_only:
            return {"success": True}
        nuevo = str(self._siguiente_id)
        self._siguiente_id += 1
        self.objetos[nuevo] = dict(normal)
        self.hijos[nuevo] = (arista, {padre})
        self._despues_de_escribir(padre, validate_only)
        return {"id": nuevo}

    def subir_imagen(self, act_id: str, contenido: bytes, nombre: str) -> str:
        _seg(act_id)
        self._stop(False)
        self._entrada("subir_imagen", act_id, {"nombre": nombre, "bytes": len(contenido)})
        self._antes_de_escribir(act_id, False)
        self._despues_de_escribir(act_id, False)
        return hashlib.sha256(contenido).hexdigest()[:32]

    def subir_video(self, act_id: str, ruta: Path) -> str:
        _seg(act_id)
        if ruta.stat().st_size > _MAX_VIDEO:
            raise ValueError("vídeo > 100 MB: subida por partes no soportada")
        self._stop(False)
        self._entrada("subir_video", act_id, {"nombre": ruta.name})
        self._antes_de_escribir(act_id, False)
        vid = str(self._siguiente_video)
        self._siguiente_video += 1
        self._despues_de_escribir(act_id, False)
        return vid

    def cuenta(self, act_id: str) -> InfoCuenta:
        r = self.leer(act_id, _CAMPOS_CUENTA)
        moneda = str(r.get("currency", ""))
        tope = _entero(r.get("spend_cap"))
        return InfoCuenta(
            currency=moneda,
            offset=OFFSETS_META.get(moneda),
            timezone_name=str(r.get("timezone_name", "")),
            spend_cap=tope if tope else None,
            account_status=_entero(r.get("account_status")) or 0,
            amount_spent=_entero(r.get("amount_spent")),
        )


def _check(v: object) -> object:
    _valor(v)  # mismo ValueError que el cliente real para None
    return v


def mundo_basico() -> GraphFalso:
    g = GraphFalso()
    g.cuentas[CUENTA] = {"currency": "COP", "timezone_name": "America/Bogota", "spend_cap": "1000000",
                         "amount_spent": "250000", "account_status": 1}
    g.cuentas["act_usd"] = {"currency": "USD", "timezone_name": "America/New_York", "spend_cap": "0",
                            "amount_spent": "0", "account_status": 1}
    cuenta = "0000000000000000"
    activo = {"status": "ACTIVE", "effective_status": "ACTIVE"}
    g.objetos["c1"] = {"account_id": cuenta, **activo, "name": "Campaña"}
    g.objetos["s1"] = {"account_id": cuenta, **activo, "daily_budget": "20000", "bid_amount": "1500",
                       "campaign_id": "c1", "name": "Conjunto 1"}
    g.objetos["s2"] = {"account_id": cuenta, **activo, "daily_budget": "15000", "campaign_id": "c1",
                       "name": "Conjunto 2"}
    g.objetos["a1"] = {"account_id": cuenta, **activo, "adset_id": "s1", "campaign_id": "c1", "name": "Anuncio"}
    g.objetos["x9"] = {"account_id": "999", "status": "ACTIVE", "effective_status": "ACTIVE", "daily_budget": "10000", "name": "Ajeno"}
    g.hijos.update({
        "c1": ("campaigns", {CUENTA}),
        "s1": ("adsets", {CUENTA, "c1"}),
        "s2": ("adsets", {CUENTA, "c1"}),
        "a1": ("ads", {CUENTA, "s1"}),
    })
    return g
