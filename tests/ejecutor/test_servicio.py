"""Servicio del ejecutor (plan 12, Tarea 4): buzón, envío a Telegram, despacho de acciones y ejecución.

Todo en ``tmp_path``: buzón, base, auditoría, STOP y vault; Telegram y Graph en proceso.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import yaml
from ejecutor.conftest import datos_limites
from ejecutor.falsos.graph_falso import GraphFalso, mundo_basico
from trovefy_ejecutor import ejecutar as _ejecutar
from trovefy_ejecutor.config import RutasEjecutor
from trovefy_ejecutor.ejecutar import NO_SOPORTADO_P07
from trovefy_ejecutor.reloj import ZONA_COT
from trovefy_ejecutor.secretos import Secretos
from trovefy_ejecutor.servicio import Ejecutor
from trovefy_ejecutor.simulado import TelegramSimulado
from trovefy_ejecutor.stop import activar_stop

CUENTA = "act_0000000000000000"
C1, S1, S2, A1 = "100000001", "100000011", "100000012", "100000021"
T0 = datetime(2026, 11, 12, 15, 0, tzinfo=ZONA_COT)
CLAVE = b"k" * 32
TOKEN_META = "EAAsecretoDeMeta1234567890"
TOKEN_TG = "123456:" + "B" * 35
PAGINA, DATASET = "1357661930771909", "8877665544"
RUTA_IMG, BYTES_IMG = "productos/p-0001/creativos/BG/t1/img01.jpg", b"\xff\xd8\xff imagen de prueba"


class Reloj:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def avanzar(self, **kw) -> None:
        self.t += timedelta(**kw)


def mundo() -> GraphFalso:
    """``mundo_basico`` con ids numéricos (los que acepta el esquema de §5.2)."""
    g = mundo_basico()
    ren = {"c1": C1, "s1": S1, "s2": S2, "a1": A1}
    objetos = {}
    for k, v in g.objetos.items():
        v = dict(v)
        for campo in ("campaign_id", "adset_id"):
            if campo in v:
                v[campo] = ren[v[campo]]
        objetos[ren.get(k, k)] = v
    g.objetos = objetos
    g.hijos = {ren[k]: (ar, {ren.get(x, x) for x in padres}) for k, (ar, padres) in g.hijos.items()}
    return g


@dataclass
class Montaje:
    tmp: Path
    rutas: RutasEjecutor
    tg: TelegramSimulado
    graph: GraphFalso
    secretos: Secretos
    reloj: Reloj
    ej: Ejecutor
    clave: bytes = CLAVE

    @property
    def vault(self) -> Path:
        assert self.rutas.vault is not None
        return self.rutas.vault

    def depositar(self, d: dict, nombre: str | None = None) -> Path:
        ruta = self.rutas.spool / "entrada" / (nombre or f"{d['id']}.json")
        ruta.write_text(json.dumps(d), encoding="utf-8")
        viejo = self.reloj().timestamp() - 60
        os.utime(ruta, (viejo, viejo))
        return ruta

    def eventos(self, nombre: str, **filtro) -> list[dict]:
        out = []
        for linea in self.rutas.auditoria.read_text(encoding="utf-8").splitlines():
            x = json.loads(linea)
            if x["evento"] == nombre and all(x["datos"].get(k) == v for k, v in filtro.items()):
                out.append(x["datos"])
        return out

    def estado(self, id: str) -> str:
        fila = self.ej.almacen.obtener(id)
        assert fila is not None
        return fila.estado

    def textos(self) -> list[str]:
        return [self.tg.mensajes[k]["texto"] for k in sorted(self.tg.mensajes)]

    def mensaje_de(self, id: str) -> dict:
        fila = self.ej.almacen.obtener(id)
        assert fila is not None and fila.message_id is not None
        return self.tg.mensajes[fila.message_id]

    def limites(self, offset: int | None = 1, **globales) -> None:
        d = datos_limites(offset)
        d["cuentas"][CUENTA]["paginas_permitidas"] = [PAGINA]
        d.update(globales)
        self.rutas.limites.write_text(yaml.safe_dump(d))
        os.chmod(self.rutas.limites, 0o600)
        st = self.rutas.limites.stat()
        os.utime(self.rutas.limites, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


def _montaje(tmp_path: Path, offset: int | None = 1, vault: bool = True) -> Montaje:
    _ejecutar._EMITIDOS.clear()
    datos = tmp_path / "datos"
    rutas = RutasEjecutor(secretos=tmp_path / "secretos.env", limites=tmp_path / "limites.yaml",
                          base=datos / "estado.sqlite", auditoria=datos / "auditoria.jsonl", stop=datos / "STOP",
                          spool=tmp_path / "spool", vault=(tmp_path / "vault") if vault else None)
    if vault:
        f = tmp_path / "vault" / RUTA_IMG
        f.parent.mkdir(parents=True)
        f.write_bytes(BYTES_IMG)
    reloj = Reloj(T0)
    tg = TelegramSimulado(42, 42, ahora=reloj)
    secretos = Secretos(meta_token=TOKEN_META, telegram_bot_token=TOKEN_TG, hmac_clave=CLAVE,
                        telegram_user_id=42, telegram_chat_id=42, claude_uid=os.geteuid())
    m = Montaje(tmp_path, rutas, tg, mundo(), secretos, reloj, None)  # type: ignore[arg-type]
    m.limites(offset)
    m.ej = Ejecutor(rutas, tg, m.graph, secretos, reloj=reloj, modo="simulado")
    return m


@pytest.fixture
def montaje(tmp_path: Path):
    m = _montaje(tmp_path)
    try:
        yield m
    finally:
        m.ej.almacen.cerrar()
        _ejecutar._EMITIDOS.clear()


# -- fábricas (dicts de §5.2, creadas un minuto antes de T0) ---------------------------------------
def _creada() -> str:
    return (T0 - timedelta(minutes=1)).isoformat()


def noop(id: str = "P-20261112-001", **c) -> dict:
    d = {"version": 1, "id": id, "tipo": "noop", "creada": _creada(), "origen": "/probar",
         "motivo": "Prueba de extremo a extremo", "prioridad": "normal", "expira_en_min": 30}
    d.update(copy.deepcopy(c))
    return d


def presupuesto(id: str = "P-20261112-003", de: int = 20000, a: int = 26000, ent: str = S1, **c) -> dict:
    d = {"version": 1, "id": id, "tipo": "presupuesto", "creada": _creada(), "origen": "/leer --intradia",
         "producto": "p-0001-herramientas", "pais": "BG", "cuenta": CUENTA,
         "operaciones": [{"entidad": "adset", "id": ent, "campo": "daily_budget", "de_esperado": de, "a": a,
                          "unidad": "minima", "moneda": "COP"}],
         "motivo": "ROAS neto acum. 2,6", "reinicia_aprendizaje": False, "prioridad": "normal",
         "expira_en_min": 45}
    d.update(copy.deepcopy(c))
    return d


def pausar(id: str = "P-20261112-005", ent: str = S1, **c) -> dict:
    d = presupuesto(id=id, tipo="pausar", operaciones=[{"entidad": "adset", "id": ent, "campo": "status",
                                                        "de_esperado": "ACTIVE", "a": "PAUSED"}])
    d.update(copy.deepcopy(c))
    return d


def lote(id: str = "P-20261112-007", **c) -> dict:
    ops = [{"entidad": "adset", "id": S1, "campo": "daily_budget", "de_esperado": 20000, "a": 15000,
            "unidad": "minima", "moneda": "COP"},
           {"entidad": "adset", "id": S2, "campo": "daily_budget", "de_esperado": 15000, "a": 10000,
            "unidad": "minima", "moneda": "COP"}]
    return presupuesto(id=id, tipo="lote", operaciones=ops, **c)


def alerta(id: str = "P-20261112-010", **c) -> dict:
    d = {"version": 1, "id": id, "tipo": "alerta", "creada": _creada(), "origen": "/vigia", "nivel": "aviso",
         "titulo": "Saldo APIMart bajo", "texto": "Quedan 0,80 USD."}
    d.update(copy.deepcopy(c))
    return d


def estructura(id: str = "P-20261112-002", **c) -> dict:
    d = {"version": 1, "id": id, "tipo": "crear_estructura_pausada", "creada": _creada(), "origen": "/montar",
         "producto": "p-0001", "pais": "BG", "cuenta": CUENTA, "pagina_id": PAGINA, "dataset_id": DATASET,
         "medios": [{"ref": "img01", "ruta": RUTA_IMG, "sha256": hashlib.sha256(BYTES_IMG).hexdigest()}],
         "campana": {"nombre": "PRUEBA BG | ABO", "objetivo": "OUTCOME_SALES", "tipo_presupuesto": "ABO",
                     "spend_cap": 90000, "bid_strategy": "LOWEST_COST_WITHOUT_CAP"},
         "conjuntos": [{"nombre": "01 IMG", "daily_budget": 20000, "paises": ["BG"], "idiomas": ["bg"],
                        "evento": "PURCHASE", "ubicaciones_excluidas": ["audience_network"],
                        "anuncios": [{"nombre": "AD01", "medio": "img01", "texto": "Texto", "titulo": "Titulo",
                                      "descripcion": "Descripcion", "cta": "LEARN_MORE",
                                      "url": "https://example.com/bg"}]}],
         "unidad": "minima", "moneda": "COP"}
    d.update(copy.deepcopy(c))
    return d


def resultado_procesado(m: Montaje, id: str) -> dict:
    return json.loads((m.rutas.spool / "procesadas" / f"{id}.resultado.json").read_text())


# == Parte 1: buzón, validación y envío ===========================================================

def test_noop_se_envia_con_botones(montaje):
    m = montaje
    m.depositar(noop())
    m.ej.ciclo()
    assert m.estado("P-20261112-001") == "enviada"
    msg = m.mensaje_de("P-20261112-001")
    assert msg["texto"].startswith("P-20261112-001 · PRUEBA") and len(msg["botones"][0]) == 2
    assert m.eventos("recibida", id="P-20261112-001")
    assert m.eventos("transicion", id="P-20261112-001", de="recibida", a="enviada")
    assert resultado_procesado(m, "P-20261112-001")["estado"] == "recibida"
    assert not list((m.rutas.spool / "entrada").glob("*.json"))


def test_presupuesto_valido_se_envia_con_el_valor_vivo(montaje):
    m = montaje
    m.depositar(presupuesto())
    m.ej.ciclo()
    assert m.estado("P-20261112-003") == "enviada"
    texto = m.mensaje_de("P-20261112-003")["texto"]
    assert "20.000 → 26.000 COP" in texto
    assert "tras el cambio: 41.000 / tope 165.000" in texto
    fila = m.ej.almacen.obtener("P-20261112-003")
    assert fila.datos["texto"] == texto and "enviada_en" in fila.datos


def test_tipo_no_soportado(montaje):
    m = montaje
    d = presupuesto(id="P-20261112-008", tipo="agenda",
                    operaciones=[{"entidad": "adset", "id": S1, "campo": "budget_schedules", "de_esperado": None,
                                  "a": None, "parametros": {"franjas": []}}])
    m.depositar(d)
    m.ej.ciclo()
    assert m.tg.mensajes == {}
    assert resultado_procesado(m, "P-20261112-008") == {"estado": "rechazada", "motivo": NO_SOPORTADO_P07}
    assert m.eventos("validacion_rechazada", id="P-20261112-008", motivo=NO_SOPORTADO_P07)


def test_deposito_de_otro_uid_no_llega(montaje, monkeypatch):
    from trovefy_ejecutor import deposito, servicio

    def falso(ruta, uids):
        raise deposito.DepositoRechazado("depositado por uid 4242", 4242)

    monkeypatch.setattr(servicio, "comprobar_origen", falso)
    m = montaje
    m.depositar(noop())
    m.ej.ciclo()
    assert m.ej.almacen.obtener("P-20261112-001") is None and m.tg.mensajes == {}
    assert (m.rutas.spool / "procesadas" / "P-20261112-001.json").exists()
    ev = m.eventos("validacion_rechazada", id="P-20261112-001")
    assert ev and ev[0]["uid"] == 4242 and "4242" in ev[0]["motivo"]


def test_json_invalido_y_nombre_que_no_es_el_id(montaje):
    m = montaje
    (m.rutas.spool / "entrada" / "P-20261112-011.json").write_text("{no es json")
    os.utime(m.rutas.spool / "entrada" / "P-20261112-011.json", (T0.timestamp() - 60,) * 2)
    m.depositar(noop(id="P-20261112-012"), nombre="P-20261112-013.json")
    m.ej.ciclo()
    assert m.tg.mensajes == {} and m.ej.almacen.obtener("P-20261112-012") is None
    assert len(m.eventos("validacion_rechazada")) == 2
    assert not list((m.rutas.spool / "entrada").glob("*.json"))


def test_id_reservado_al_ejecutor_o_a_telegram_se_rechaza(montaje):
    m = montaje
    m.depositar(noop(id="P-20261112-950"))
    m.depositar(noop(id="P-20261112-850"))
    m.ej.ciclo()
    assert m.tg.mensajes == {}
    assert m.ej.almacen.obtener("P-20261112-950") is None and m.ej.almacen.obtener("P-20261112-850") is None


def test_id_duplicado_no_toca_la_fila(montaje):
    m = montaje
    m.depositar(noop())
    m.ej.ciclo()
    m.depositar(noop(motivo="otra"))
    m.ej.ciclo()
    assert m.estado("P-20261112-001") == "enviada" and len(m.tg.mensajes) == 1
    assert m.eventos("validacion_rechazada", id="P-20261112-001")


def test_obsoleta_no_se_envia(montaje):
    m = montaje
    m.graph.cambiar(S1, daily_budget=22000)
    m.depositar(presupuesto())
    m.ej.ciclo()
    assert m.estado("P-20261112-003") == "obsoleta" and m.tg.mensajes == {}


def test_limite_violado_no_se_envia(montaje):
    m = montaje
    m.depositar(presupuesto(a=40000))
    m.ej.ciclo()
    assert m.estado("P-20261112-003") == "rechazada" and m.tg.mensajes == {}
    ev = m.eventos("validacion_rechazada", id="P-20261112-003")
    assert ev and "paso_excesivo" in ev[0]["motivo"]
    assert "paso_excesivo" in m.ej.almacen.obtener("P-20261112-003").datos["motivo"]


def test_moneda_sin_offset_rechaza_importes(tmp_path):
    m = _montaje(tmp_path, offset=None)
    m.depositar(presupuesto())
    m.depositar(pausar())
    m.depositar(noop())
    m.ej.ciclo()
    for id in ("P-20261112-003", "P-20261112-005"):
        assert m.estado(id) == "rechazada"
        assert "P-21" in m.ej.almacen.obtener(id).datos["motivo"]
    assert m.estado("P-20261112-001") == "enviada"
    m.ej.almacen.cerrar()


def test_moneda_viva_distinta_de_limites_rechaza(montaje):
    m = montaje
    m.graph.cuentas[CUENTA]["currency"] = "USD"
    m.depositar(pausar())
    m.ej.ciclo()
    assert m.estado("P-20261112-005") == "rechazada"
    assert "moneda viva ≠ limites.yaml (P-21)" in m.ej.almacen.obtener("P-20261112-005").datos["motivo"]


@pytest.mark.parametrize("fallo", ["red", "ajena"])
def test_error_de_lectura_es_rechazo_y_no_tumba_el_ciclo(montaje, fallo):
    m = montaje
    if fallo == "red":
        m.graph.red_al_leer = True
        m.depositar(presupuesto())
    else:
        m.graph.objetos[S1]["account_id"] = "999"
        m.depositar(presupuesto())
    m.depositar(noop())
    m.ej.ciclo()
    assert m.estado("P-20261112-003") == "rechazada"
    assert m.estado("P-20261112-001") == "enviada"


def test_comprobar_que_lanza_es_rechazo(montaje, monkeypatch):
    from trovefy_ejecutor import servicio

    def roto(*a, **k):
        raise RuntimeError("fallo interno")

    monkeypatch.setattr(servicio, "comprobar", roto)
    m = montaje
    m.depositar(pausar())
    m.ej.ciclo()
    assert m.estado("P-20261112-005") == "rechazada" and m.tg.mensajes == {}


def test_stop_activo_rechaza_al_recibir(montaje):
    m = montaje
    activar_stop(m.rutas, "prueba", T0)
    m.depositar(pausar())
    m.ej.ciclo()
    assert m.estado("P-20261112-005") == "rechazada" and m.tg.mensajes == {}


def test_silencio_deja_en_cola_y_alta_pasa(montaje):
    m = montaje
    m.reloj.t = datetime(2026, 11, 12, 23, 30, tzinfo=ZONA_COT)
    m.depositar(noop(creada=(m.reloj.t - timedelta(minutes=1)).isoformat()))
    m.depositar(pausar(prioridad="alta", creada=(m.reloj.t - timedelta(minutes=1)).isoformat()))
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-001")
    assert fila.estado == "recibida" and fila.datos["en_cola"] is True
    assert m.estado("P-20261112-005") == "enviada"
    assert m.mensaje_de("P-20261112-005")["sonido"] is True


def test_alerta_se_envia_y_queda_ejecutada(montaje):
    m = montaje
    m.depositar(alerta())
    m.ej.ciclo()
    assert m.estado("P-20261112-010") == "ejecutada"
    assert m.textos() == ["AVISO · Saldo APIMart bajo\nQuedan 0,80 USD.\nP-20261112-010"]
    assert not m.tg.mensajes[1]["botones"]


def test_error_en_una_propuesta_no_tumba_el_ciclo(montaje, monkeypatch):
    m = montaje
    original = m.ej._despachar

    def a_veces(id):
        if id == "P-20261112-003":
            raise RuntimeError(f"roto {TOKEN_META}")
        return original(id)

    monkeypatch.setattr(m.ej, "_despachar", a_veces)
    m.depositar(presupuesto())
    m.depositar(noop())
    m.ej.ciclo()
    assert m.estado("P-20261112-001") == "enviada"
    errores = m.eventos("error")
    assert errores and all(TOKEN_META not in json.dumps(e) for e in errores)


def test_graph_con_stop(tmp_path):
    from trovefy_ejecutor.graph import DetenidoPorStop
    from trovefy_ejecutor.servicio import GraphConStop

    rutas = RutasEjecutor(secretos=tmp_path / "s", limites=tmp_path / "l", base=tmp_path / "b",
                          auditoria=tmp_path / "a", stop=tmp_path / "STOP", spool=tmp_path / "sp", vault=None)
    g = mundo()
    gs = GraphConStop(g, rutas)
    assert gs.leer(S1, ["daily_budget"])["daily_budget"] == "20000"
    activar_stop(rutas, "prueba", T0)
    for llamada in (lambda: gs.escribir(S1, {"daily_budget": 1}, validate_only=True),
                    lambda: gs.escribir(S1, {"daily_budget": 1}),
                    lambda: gs.crear(CUENTA, "campaigns", {"name": "x"}, validate_only=True),
                    lambda: gs.subir_imagen(CUENTA, b"x", "x.jpg"),
                    lambda: gs.subir_video(CUENTA, tmp_path / "v.mp4")):
        with pytest.raises(DetenidoPorStop):
            llamada()
    assert g.escrituras() == [] and not [x for x in g.llamadas if x.metodo != "leer"]
    assert gs.leer(S1, ["status"])["status"] == "ACTIVE"  # leer, listar, buscar y cuenta pasan
    assert gs.listar(CUENTA, "campaigns", ["id"]) and gs.cuenta(CUENTA).currency == "COP"
    assert gs.buscar("adlocale", "Bulgarian", ["key", "name"])
    assert "EAA" not in repr(gs) and repr(gs) == "GraphConStop()"


def test_ejecutor_sin_tokens_en_repr_ni_auditoria(montaje):
    m = montaje
    m.depositar(presupuesto())
    m.ej.ciclo()
    assert TOKEN_META not in repr(m.ej) and TOKEN_TG not in repr(m.ej)
    crudo = m.rutas.auditoria.read_text()
    assert TOKEN_META not in crudo and TOKEN_TG not in crudo
