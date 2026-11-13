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
from trovefy_ejecutor.render import RECIBIDO, STOP_ACTIVO, texto_ya_procesada
from trovefy_ejecutor.secretos import Secretos
from trovefy_ejecutor.servicio import Ejecutor
from trovefy_ejecutor.simulado import TelegramSimulado
from trovefy_ejecutor.stop import activar_stop, stop_activo

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
                    lambda: gs.subir_video(CUENTA, b"v", "v.mp4")):
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


# == Parte 2: toques, ejecución y resultados ======================================================

def _enviar(m: Montaje, d: dict) -> str:
    m.depositar(d)
    m.ej.ciclo()
    assert m.estado(d["id"]) == "enviada", m.ej.almacen.obtener(d["id"]).datos
    return d["id"]


def test_noop_aceptar_queda_registrado(montaje):
    m = montaje
    id = _enviar(m, noop())
    cb = m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada"
    assert m.tg.respuestas_callback[0] == (cb, RECIBIDO)
    assert m.eventos("transicion", id=id, tipo="noop", de="enviada", a="aceptada")
    assert m.eventos("ejecucion", id=id, ok=True)
    fila = m.ej.almacen.obtener(id)
    assert fila.datos["callback_id"] == cb
    msg = m.mensaje_de(id)
    assert "EJECUTADA 15:00" in msg["texto"] and not msg["botones"]
    assert (m.vault / f"propuestas/{id}.md").exists() and m.ej.auditoria.verificar()
    assert f"callback_id: {cb}" in (m.vault / f"propuestas/{id}.md").read_text()


def test_doble_toque_ejecuta_una_vez(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.tg.tocar(id, "A", m.clave)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada"
    assert len(m.graph.escrituras()) == 1 and m.graph.objetos[S1]["daily_budget"] == "26000"
    assert m.textos()[1] == texto_ya_procesada("ejecutada")
    assert [r[1] for r in m.tg.respuestas_callback] == [RECIBIDO, RECIBIDO]
    m.tg.tocar(id, "A", m.clave)  # y en otro ciclo, tampoco
    m.ej.ciclo()
    assert len(m.graph.escrituras()) == 1


def test_rechazar_con_motivo(montaje):
    m = montaje
    id = _enviar(m, presupuesto(id="P-20261112-002"))
    m.tg.tocar(id, "R", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "rechazada" and m.graph.escrituras() == []
    msg = m.mensaje_de(id)
    assert "RECHAZADA 15:00" in msg["texto"] and not msg["botones"]
    pregunta = next(k for k, v in m.tg.mensajes.items() if "¿Motivo?" in v["texto"])
    assert m.ej.almacen.obtener(id).datos["pregunta_motivo"] == pregunta
    m.tg.escribir("pico puntual", responde_a=pregunta)
    m.ej.ciclo()
    nota = m.vault / "raw/telegram/motivos/2026-11-12-P-20261112-002.md"
    assert nota.exists() and "> pico puntual" in nota.read_text()
    assert m.eventos("motivo_rechazo", id=id)
    m.tg.escribir("otra cosa", responde_a=pregunta)  # segunda nota: -2, nunca pisa la primera
    m.ej.ciclo()
    assert (m.vault / "raw/telegram/motivos/2026-11-12-P-20261112-002-2.md").exists()
    assert "> pico puntual" in nota.read_text()


def test_motivo_solo_si_la_propuesta_esta_rechazada(montaje):
    m = montaje
    id = _enviar(m, presupuesto(id="P-20261112-002"))
    pregunta = m.ej.almacen.obtener(id).message_id
    m.tg.mensajes[pregunta]["texto"] = "P-20261112-002 · ¿Motivo? (responde a este mensaje, opcional)"
    m.tg.escribir("intento", responde_a=pregunta)
    m.ej.ciclo()
    assert not (m.vault / "raw/telegram/motivos").exists()
    assert m.estado(id) == "enviada"


def test_firma_falsa_y_user_ajeno(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    from trovefy_ejecutor.callbacks import firmar
    data = firmar(id, "A", 42, m.clave)
    m.tg.tocar(id, "A", m.clave, data=data[:-1] + ("x" if data[-1] != "x" else "y"))
    m.tg.tocar(id, "A", m.clave, user_id=99)
    m.tg.tocar(id, "A", b"otra-clave" * 4)
    m.ej.ciclo()
    assert m.estado(id) == "enviada" and m.graph.escrituras() == []
    motivos = [e["motivo"] for e in m.eventos("callback_invalido")]
    assert motivos == ["callback_firma", "callback_usuario_ajeno", "callback_firma"]


def test_stop_activo_no_ejecuta(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    activar_stop(m.rutas, "prueba", T0)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "enviada" and m.graph.escrituras() == []
    assert m.mensaje_de(id)["texto"].endswith(STOP_ACTIVO)
    assert m.tg.respuestas_callback[0][1] == RECIBIDO


def test_caducada_al_tocar_no_ejecuta(montaje):
    m = montaje
    id = _enviar(m, presupuesto())  # caduca a los 45 min de creada
    m.reloj.avanzar(hours=1)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "caducada" and m.graph.escrituras() == []
    msg = m.mensaje_de(id)
    assert msg["texto"].endswith("CADUCADA, no se ejecutó nada") and not msg["botones"]


def test_callback_futuro_no_ejecuta(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.tg.tocar(id, "A", m.clave, fecha=T0 + timedelta(minutes=10))
    m.ej.ciclo()
    assert m.estado(id) == "enviada" and m.graph.escrituras() == []
    assert m.eventos("callback_invalido", motivo="callback_futuro")


def test_desfase_grande_bloquea_ejecucion(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.tg._ahora = lambda: m.reloj() - timedelta(seconds=400)
    m.tg.escribir("/estado")
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "aceptada" and m.graph.escrituras() == []
    assert any("hwclock -s" in t for t in m.textos())


def test_stop_a_mitad_de_lote(montaje):
    m = montaje
    id = _enviar(m, lote())
    m.graph.al_escribir = lambda: activar_stop(m.rutas, "prueba", T0)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert len(m.graph.escrituras()) == 1
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and fila.datos["parcial"] is True and fila.datos["error"] == "stop"
    texto = m.mensaje_de(id)["texto"]
    assert "no se cambió nada" not in texto and "se aplicó una parte" in texto


def test_discrepancia_crea_nueva_propuesta(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.graph.forzar_pausa = {S1}
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "discrepancia" and fila.datos["nueva_propuesta"] == "P-20261112-800"
    assert m.estado("P-20261112-800") == "enviada"
    assert "nueva propuesta P-20261112-800" in m.mensaje_de(id)["texto"]
    assert m.mensaje_de("P-20261112-800")["texto"].startswith("P-20261112-800 · ACTIVAR")


def test_obsoleta_al_ejecutar(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.graph.cambiar(S1, daily_budget=21000)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "obsoleta" and m.graph.escrituras() == []
    assert "OBSOLETA" in m.mensaje_de(id)["texto"]


def test_limites_se_comprueban_otra_vez_antes_de_ejecutar(montaje):
    m = montaje
    id = _enviar(m, presupuesto())
    m.limites(1, paso_max_pct=10)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "paso_excesivo" in fila.datos["motivo"]
    assert m.graph.escrituras() == []


@pytest.mark.parametrize("fallo", ["red", "moneda", "limites_rotos"])
def test_fallo_antes_de_ejecutar_es_fallida_sin_escribir(montaje, fallo):
    m = montaje
    id = _enviar(m, presupuesto())
    if fallo == "red":
        m.graph.red_al_leer = True
    elif fallo == "moneda":
        m.graph.cuentas[CUENTA]["currency"] = "USD"
    else:
        m.rutas.limites.write_text("version: 1\n")
        os.utime(m.rutas.limites, ns=(0, m.rutas.limites.stat().st_mtime_ns + 5_000_000))
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "fallida" and m.graph.escrituras() == []


def test_token_caducado_avisa_y_bloquea_el_gasto(montaje):
    from trovefy_ejecutor.graph import ErrorGraph

    m = montaje
    id = _enviar(m, presupuesto())
    id2 = _enviar(m, pausar())
    m.graph.errores_reales[S1] = ErrorGraph(190, 463, "token caducado")
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and fila.datos["error"] == "token"
    assert any("/arranque paso 13" in t for t in m.textos())
    escrituras = len(m.graph.escrituras())
    m.tg.tocar(id2, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id2) == "fallida" and len(m.graph.escrituras()) == escrituras
    assert "token" in m.ej.almacen.obtener(id2).datos["motivo"]


def test_pausar_alta_con_gasto_activo_se_envia_y_ejecuta(montaje):
    m = montaje
    m.reloj.t = datetime(2026, 11, 12, 23, 30, tzinfo=ZONA_COT)
    id = _enviar(m, pausar(prioridad="alta", creada=(m.reloj.t - timedelta(minutes=1)).isoformat()))
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada" and m.graph.objetos[S1]["status"] == "PAUSED"


def test_montaje_solo_validar(montaje):
    m = montaje
    m.depositar(estructura(solo_validar=True))
    m.ej.ciclo()
    assert m.estado("P-20261112-002") == "ejecutada"
    assert [x for x in m.graph.llamadas if x.metodo == "crear" and not x.validate_only] == []
    assert m.graph.escrituras() == []
    ev = m.eventos("ejecucion", id="P-20261112-002")
    assert ev[-1]["validate_only"] is True and ev[-1]["ok"] is True
    assert m.ej.almacen.en_estado("recibida", "enviada") == []
    assert any(t.startswith("P-20261112-002") and "EJECUTADA" in t for t in m.textos())


def test_montaje_crea_en_pausa_y_propone_activar(montaje):
    m = montaje
    crear = m.graph.crear

    def crear_con_cuenta(padre, arista, datos, *, validate_only=False):  # como Meta: lo creado es de la cuenta
        r = crear(padre, arista, datos, validate_only=validate_only)
        if not validate_only:
            m.graph.objetos[r["id"]]["account_id"] = CUENTA.removeprefix("act_")
        return r

    m.graph.crear = crear_con_cuenta
    m.depositar(estructura())
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-002")
    assert fila.estado == "ejecutada" and fila.datos["ids_creados"]["campana"]
    assert fila.datos["nueva_propuesta"] == "P-20261112-800"
    assert m.estado("P-20261112-800") == "enviada"
    assert m.mensaje_de("P-20261112-800")["texto"].startswith("P-20261112-800 · ACTIVAR")
    assert len(m.graph.escrituras()) > 0 and all(o["status"] == "PAUSED" for k, o in m.graph.objetos.items()
                                                 if k.startswith("900") and "status" in o)


def test_montaje_sin_vault_es_fallida(tmp_path):
    m = _montaje(tmp_path, vault=False)
    m.depositar(estructura(solo_validar=True))
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-002")
    assert fila.estado == "fallida" and "sin vault configurado" in fila.datos["motivo"]
    assert m.graph.escrituras() == []
    m.ej.almacen.cerrar()


def test_montaje_con_stop_se_rechaza(montaje):
    m = montaje
    activar_stop(m.rutas, "prueba", T0)
    m.depositar(estructura())
    m.ej.ciclo()
    assert m.estado("P-20261112-002") == "rechazada" and m.graph.llamadas == []


def test_montaje_fuera_de_limites_se_rechaza(montaje):
    m = montaje
    m.depositar(estructura(pagina_id="999"))
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-002")
    assert fila.estado == "rechazada" and "pagina_no_permitida" in fila.datos["motivo"]
    assert [x for x in m.graph.llamadas if x.metodo == "crear"] == []


def test_error_inesperado_al_ejecutar_es_discrepancia(montaje, monkeypatch):
    from trovefy_ejecutor import servicio

    def roto(*a, **k):
        raise RuntimeError("boom")

    m = montaje
    id = _enviar(m, presupuesto())
    monkeypatch.setattr(servicio, "ejecutar", roto)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "discrepancia"


def test_cambio_de_limite_que_no_se_puede_escribir_es_fallida(montaje, monkeypatch):
    m = montaje

    def no_puedo(cambio, cuenta):
        raise OSError("disco lleno")

    monkeypatch.setattr(m.ej, "_aplicar_cambio_limite", no_puedo)
    d = {"version": 1, "id": "P-20261112-006", "tipo": "limite_ejecutor", "creada": _creada(),
         "origen": "/limites", "cuenta": CUENTA, "motivo": "subir tope",
         "operaciones": [{"entidad": "ejecutor", "id": CUENTA, "campo": "tope_gasto_diario_total",
                          "de_esperado": 165000, "a": 150000, "unidad": "minima", "moneda": "COP"}]}
    id = _enviar(m, d)
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    fila = m.ej.almacen.obtener(id)
    assert fila.estado == "fallida" and "limites.yaml" in fila.datos["detalle"]
    assert not m.eventos("limite_cambiado")
    assert m.eventos("ejecucion", id=id, ok=False)


def test_cambio_de_limite_aplicado_se_audita(montaje, monkeypatch):
    m = montaje
    aplicados = []
    monkeypatch.setattr(m.ej, "_aplicar_cambio_limite", lambda c, cuenta: aplicados.append((c, cuenta)))
    d = {"version": 1, "id": "P-20261112-006", "tipo": "limite_ejecutor", "creada": _creada(),
         "origen": "/limites", "motivo": "más pasos",
         "operaciones": [{"entidad": "ejecutor", "id": "global", "campo": "paso_max_pct",
                          "de_esperado": 50, "a": 40}]}
    id = _enviar(m, d)
    assert "paso_max_pct (global): 50 → 40" in m.mensaje_de(id)["texto"]
    m.tg.tocar(id, "A", m.clave)
    m.ej.ciclo()
    assert m.estado(id) == "ejecutada" and aplicados[0][0]["a"] == 40
    assert m.eventos("limite_cambiado", clave="paso_max_pct", de=50, a=40)


def test_stop_activo_inexistente_por_defecto(montaje):
    assert not stop_activo(montaje.rutas)


def test_token_caducado_al_leer_tambien_bloquea(montaje):
    m = montaje
    m.graph.token_caduca_tras = 0
    m.depositar(presupuesto())
    m.ej.ciclo()
    assert m.estado("P-20261112-003") == "rechazada"
    assert m.ej.almacen.leer_kv("token_caducado")
    assert any("/arranque paso 13" in t for t in m.textos())


# == Parte 3: comandos ===========================================================================

def test_stop_por_telegram_es_inmediato(montaje):
    m = montaje
    m.tg.escribir("/stop")
    m.ej.ciclo()
    assert stop_activo(m.rutas)
    assert m.eventos("stop", activo=True)
    assert m.textos()[-1] == ("STOP activo desde 15:00. No pausa campañas: para pausarlas, /reanudar y luego "
                              "/pausar_todo.")
    assert not m.tg.mensajes[max(m.tg.mensajes)]["botones"]
    m.tg.escribir("/stop")
    m.ej.ciclo()
    assert m.textos()[-1] == "STOP ya estaba activo" and len(m.eventos("stop", activo=True)) == 1
    m.tg.escribir("/reanudar")
    m.ej.ciclo()
    pide = m.tg.mensajes[max(m.tg.mensajes)]
    assert "¿Quitar el STOP?" in pide["texto"] and len(pide["botones"][0]) == 2
    assert stop_activo(m.rutas)  # /reanudar solo pide confirmación


def test_reanudar_confirmado_y_q_no_se_reutiliza(montaje):
    m = montaje
    m.tg.escribir("/stop")
    m.tg.escribir("/reanudar")
    m.ej.ciclo()
    q = "Q-20261112-150000"
    m.tg.tocar(q, "A", m.clave)
    m.ej.ciclo()
    assert not stop_activo(m.rutas) and m.eventos("stop", activo=False)
    pide = next(v for v in m.tg.mensajes.values() if "¿Quitar el STOP?" in v["texto"])
    assert "STOP quitado 15:00" in pide["texto"] and not pide["botones"]
    m.tg.escribir("/stop")
    m.ej.ciclo()
    from trovefy_ejecutor.callbacks import firmar
    mid = next(k for k, v in m.tg.mensajes.items() if "¿Quitar el STOP?" in v["texto"])
    m.tg._poner({"callback_query": {  # el mismo botón Q- otra vez (p. ej. un mensaje viejo), en sus 10 min
        "id": "repetido", "from": {"id": 42, "is_bot": False}, "data": firmar(q, "A", 42, m.clave),
        "message": {"message_id": mid, "date": int(T0.timestamp()), "chat": {"id": 42, "type": "private"}}}})
    m.ej.ciclo()
    assert stop_activo(m.rutas)
    assert m.eventos("callback_invalido", motivo="callback_confirmacion_usada")
    assert "esta confirmación ya se usó" in m.textos()[-1].lower()


def test_reanudar_rechazado_no_quita_stop(montaje):
    m = montaje
    m.tg.escribir("/stop")
    m.tg.escribir("/reanudar")
    m.ej.ciclo()
    m.tg.tocar("Q-20261112-150000", "R", m.clave)
    m.ej.ciclo()
    assert stop_activo(m.rutas)
    pide = next(v for v in m.tg.mensajes.values() if "¿Quitar el STOP?" in v["texto"])
    assert "RECHAZADA 15:00" in pide["texto"] and not pide["botones"]


def test_confirmacion_caducada_responde_y_audita(montaje):
    m = montaje
    m.tg.escribir("/stop")
    m.tg.escribir("/reanudar")
    m.ej.ciclo()
    m.reloj.avanzar(minutes=11)
    m.tg.tocar("Q-20261112-150000", "A", m.clave)
    m.ej.ciclo()
    assert stop_activo(m.rutas)
    assert m.eventos("callback_invalido", motivo="callback_caducada")
    assert m.tg.respuestas_callback[-1][1] == texto_ya_procesada("caducada")


def test_estado(montaje):
    m = montaje
    _enviar(m, presupuesto())
    m.tg.escribir("/estado")
    m.ej.ciclo()
    t = m.textos()[-1]
    assert "STOP: no" in t and "35.000 COP" in t and "P-20261112-003 · presupuesto" in t


def test_estado_sin_graph_dice_no_medido(montaje):
    m = montaje
    m.graph.red_al_leer = True
    m.tg.escribir("/estado")
    m.ej.ciclo()
    assert "no medido" in m.textos()[-1]


def test_limites_por_cuenta_y_sin_configurar(tmp_path):
    m = _montaje(tmp_path)
    m.tg.escribir("/limites")
    m.ej.ciclo()
    t = m.textos()[-1]
    assert "tope_gasto_diario_total: 165.000 COP" in t and "paso_max_pct: 50" in t
    m.limites(None)
    m.tg.escribir("/limites")
    m.ej.ciclo()
    assert "sin configurar (P-21)" in m.textos()[-1]
    m.ej.almacen.cerrar()


def test_cambio_de_limite_por_telegram_pide_botones(montaje):
    m = montaje
    m.tg.escribir("/limites tope_gasto_diario_total 150.000")
    m.ej.ciclo()
    assert m.estado("P-20261112-900") == "enviada"
    texto = m.mensaje_de("P-20261112-900")["texto"]
    assert "165.000 COP → 150.000 COP" in texto and "Lo pide: tú (Telegram)" in texto
    m.tg.escribir("/limites paso_max_pct 40")
    m.ej.ciclo()
    assert m.estado("P-20261112-901") == "enviada"


def test_cambio_de_limite_invalido_responde_el_error(montaje):
    m = montaje
    m.tg.escribir("/limites offset 1")
    m.tg.escribir("/limites paso_max_pct 50")
    m.ej.ciclo()
    assert "no se cambia por Telegram" in m.textos()[0]
    assert m.textos()[1] == "paso_max_pct ya vale eso: no hay nada que cambiar"
    assert m.ej.almacen.obtener("P-20261112-900") is None


def test_cambio_de_limite_sin_moneda_viva_no_se_propone(montaje):
    m = montaje
    m.graph.red_al_leer = True
    m.tg.escribir("/limites tope_gasto_diario_total 150.000")
    m.ej.ciclo()
    assert "no está confirmada" in m.textos()[-1]
    assert m.ej.almacen.obtener("P-20261112-900") is None


def test_pausar_todo(montaje):
    m = montaje
    m.graph.objetos["100000002"] = {"account_id": "0000000000000000", "status": "ACTIVE",
                                    "effective_status": "CAMPAIGN_PAUSED", "name": "otra"}
    m.graph.hijos["100000002"] = ("campaigns", {CUENTA})
    m.graph.objetos["100000003"] = {"account_id": "0000000000000000", "status": "PAUSED",
                                    "effective_status": "PAUSED", "name": "pausada"}
    m.graph.hijos["100000003"] = ("campaigns", {CUENTA})
    m.reloj.t = datetime(2026, 11, 12, 23, 30, tzinfo=ZONA_COT)  # prioridad alta: pasa el silencio
    m.tg._ahora = m.reloj
    m.tg.escribir("/pausar_todo")
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-900")
    assert fila.estado == "enviada" and fila.propuesta.prioridad == "alta" and fila.tipo == "lote"
    assert sorted(op.id for op in fila.propuesta.operaciones) == [C1, "100000002"]  # status ACTIVE, en local
    listados = [x for x in m.graph.llamadas if x.metodo == "listar" and x.ruta == f"{CUENTA}/campaigns"]
    assert listados[0].datos["filtros"] == {}
    m.tg.tocar("P-20261112-900", "A", m.clave)
    m.ej.ciclo()
    assert m.estado("P-20261112-900") == "ejecutada"
    assert m.graph.objetos[C1]["status"] == "PAUSED"


def test_pausar_todo_sin_campanas_activas(montaje):
    m = montaje
    m.graph.objetos[C1]["status"] = "PAUSED"
    m.tg.escribir("/pausar_todo")
    m.ej.ciclo()
    assert m.textos()[-1] == "No hay campañas activas" and m.ej.almacen.obtener("P-20261112-900") is None


def test_responder_y_ignorar(montaje):
    m = montaje
    m.tg.escribir("hola")
    m.tg.escribir("/emparejar")
    m.tg._poner({"message": {"message_id": 99, "from": {"id": 7, "is_bot": False}, "chat": {"id": 7},
                             "date": int(T0.timestamp()), "text": "/stop"}})
    m.ej.ciclo()
    assert m.textos()[0].startswith("Comandos:") and "Ya está emparejado" in m.textos()[1]
    assert not stop_activo(m.rutas) and m.eventos("mensaje_ignorado", motivo="chat_ajeno")
    assert m.ej.almacen.ultimo_update() == 3


# == Ronda de arreglos 1 =========================================================================

def test_stop_y_luego_pausar_todo_responde_y_no_escribe(montaje):
    m = montaje
    m.tg.escribir("/stop")
    m.tg.escribir("/pausar_todo")
    m.ej.ciclo()
    assert m.estado("P-20261112-900") == "rechazada" and m.graph.escrituras() == []
    assert m.textos()[-1].endswith("STOP activo: primero /reanudar y luego /pausar_todo")


def test_propuesta_de_telegram_rechazada_al_recibir_responde_el_motivo(montaje):
    m = montaje
    m.limites(1, paso_max_pct=10)
    m.ej.ciclo()
    m.tg.escribir("/limites paso_max_pct 200")  # ErrorComando: ya lo respondía
    m.ej.ciclo()
    m.graph.cuentas[CUENTA]["currency"] = "USD"
    m.tg.escribir("/pausar_todo")
    m.ej.ciclo()
    assert m.estado("P-20261112-900") == "rechazada"
    assert "P-20261112-900" in m.textos()[-1] and "P-21" in m.textos()[-1]


def test_propuesta_de_claude_rechazada_no_avisa(montaje):
    m = montaje
    m.depositar(presupuesto(a=40000))
    m.ej.ciclo()
    assert m.tg.mensajes == {}


def test_pedir_cambio_con_propuesta_invalida_responde(montaje, monkeypatch):
    from trovefy_ejecutor import servicio
    from trovefy_ejecutor.esquema import PropuestaInvalida

    def invalida(datos):
        raise PropuestaInvalida("esquema: roto")

    monkeypatch.setattr(servicio, "cargar_propuesta", invalida)
    m = montaje
    m.tg.escribir("/limites paso_max_pct 40")
    m.ej.ciclo()
    assert "esquema: roto" in m.textos()[-1]


def test_gasto_tras_lote_con_activacion_sin_doble_conteo(montaje):
    from trovefy_ejecutor.esquema import cargar_propuesta
    from trovefy_ejecutor.vivo import valores_vivos

    m = montaje
    m.graph.cambiar(S2, status="PAUSED", effective_status="PAUSED")
    ops = [{"entidad": "adset", "id": S2, "campo": "daily_budget", "de_esperado": 15000, "a": 18000,
            "unidad": "minima", "moneda": "COP"},
           {"entidad": "adset", "id": S2, "campo": "status", "de_esperado": "PAUSED", "a": "ACTIVE"}]
    p = cargar_propuesta(presupuesto(id="P-20261112-007", tipo="lote", operaciones=ops))
    vv = valores_vivos(p, m.graph, ahora=m.reloj)
    assert Ejecutor._gasto_tras(p, vv) == (20000 + 18000, False)
    del m.graph.objetos[S2]["daily_budget"]  # sin presupuesto propio ni de campaña: desconocido
    p2 = cargar_propuesta(presupuesto(id="P-20261112-007", tipo="lote", operaciones=[ops[1]]))
    assert Ejecutor._gasto_tras(p2, valores_vivos(p2, m.graph, ahora=m.reloj)) == (None, True)


def test_alerta_texto_guardado_redactado(montaje):
    m = montaje
    m.depositar(alerta(texto=f"clave {TOKEN_TG}"))
    m.ej.ciclo()
    fila = m.ej.almacen.obtener("P-20261112-010")
    assert TOKEN_TG not in json.dumps(fila.datos)
    assert TOKEN_TG not in (m.vault / "propuestas/P-20261112-010.md").read_text()


def test_fallo_entre_registrar_y_procesar_deja_la_fila_rechazada(montaje, monkeypatch):
    m = montaje
    procesar = m.ej.buzon.procesar

    def roto(ruta, resultado):
        if resultado["estado"] == "recibida":
            raise OSError("disco lleno")
        return procesar(ruta, resultado)

    monkeypatch.setattr(m.ej.buzon, "procesar", roto)
    m.depositar(noop())
    m.ej.ciclo()
    assert m.estado("P-20261112-001") == "rechazada" and m.tg.mensajes == {}
    assert not list((m.rutas.spool / "entrada").glob("*.json"))
    assert m.eventos("transicion", id="P-20261112-001", a="rechazada")


def test_segundo_motivo_con_vault_caido_no_se_pierde(montaje):
    m = montaje
    id = _enviar(m, presupuesto(id="P-20261112-002"))
    m.tg.tocar(id, "R", m.clave)
    m.ej.ciclo()
    pregunta = m.ej.almacen.obtener(id).datos["pregunta_motivo"]
    os.chmod(m.vault, 0o500)  # no se pueden crear carpetas nuevas: las notas quedan en cola
    try:
        m.tg.escribir("primero", responde_a=pregunta)
        m.tg.escribir("segundo", responde_a=pregunta)
        m.ej.ciclo()
    finally:
        os.chmod(m.vault, 0o750)
    m.ej.copia.reintentar()
    base = m.vault / "raw/telegram/motivos"
    textos = sorted(f.read_text() for f in base.glob("*.md"))
    assert len(textos) == 2 and any("> primero" in t for t in textos) and any("> segundo" in t for t in textos)


def test_graph_con_stop_misma_interfaz_que_cliente():
    import inspect

    from trovefy_ejecutor.graph import ClienteGraph
    from trovefy_ejecutor.servicio import GraphConStop
    for nombre in ("leer", "buscar", "escribir", "crear", "subir_imagen", "subir_video", "cuenta"):
        real = list(inspect.signature(getattr(ClienteGraph, nombre)).parameters)
        envuelto = list(inspect.signature(getattr(GraphConStop, nombre)).parameters)
        assert real == envuelto, nombre
    # subir_video recibe los bytes verificados, nunca una ruta que se pueda releer (TOCTOU)
    assert list(inspect.signature(ClienteGraph.subir_video).parameters) == ["self", "act_id", "contenido", "nombre"]


def test_deposito_de_claude_con_origen_telegram_no_responde_en_telegram(montaje):
    """La respuesta en Telegram al rechazar se decide por el rango del id (900–999), no por ``origen``."""
    m = montaje
    activar_stop(m.rutas, "prueba", T0)
    m.depositar(pausar(origen="telegram:x"))
    m.ej.ciclo()
    assert m.estado("P-20261112-005") == "rechazada" and m.tg.mensajes == {}
