import threading
from datetime import UTC, datetime, timedelta

import pytest
from fabricas import alerta, estructura, presupuesto
from trovefy_ejecutor.esquema import cargar_propuesta
from trovefy_ejecutor.estado import (
    TRANSICIONES,
    Almacen,
    IdDuplicado,
    TransicionInvalida,
)

T0 = datetime(2026, 11, 12, 19, 5, tzinfo=UTC)


def test_ciclo_y_doble_toque(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    a.registrar(cargar_propuesta(presupuesto()))
    assert a.transicion("P-20261112-004", "recibida", "enviada")
    a.guardar_mensaje("P-20261112-004", -100123, 42)
    assert a.transicion("P-20261112-004", "enviada", "aceptada", callback_id="cb1")
    assert not a.transicion("P-20261112-004", "enviada", "aceptada")  # segundo toque
    f = a.obtener("P-20261112-004")
    assert f.estado == "aceptada" and f.datos["callback_id"] == "cb1" and f.message_id == 42
    assert f.clase == "gasto" and f.chat_id == -100123
    assert [h[1] for h in a.historial("P-20261112-004")] == ["recibida", "enviada", "aceptada"]
    assert a.historial("P-20261112-004")[0][0] is None


def test_enviada_a_enviada_guarda_datos_y_no_cuenta_como_envio(tmp_path):
    reloj = iter([T0 + timedelta(minutes=m) for m in range(10)])
    a = Almacen(tmp_path / "e.sqlite", reloj=lambda: next(reloj))
    a.registrar(cargar_propuesta(presupuesto()))
    a.transicion("P-20261112-004", "recibida", "enviada")
    assert a.transicion("P-20261112-004", "enviada", "enviada", recordatorio_1h=True, pregunta_motivo=77)
    f = a.obtener("P-20261112-004")
    assert f.estado == "enviada" and f.datos["pregunta_motivo"] == 77
    envios = [h[2] for h in a.historial("P-20261112-004") if h[1] == "enviada" and h[0] != "enviada"]
    assert envios == [T0 + timedelta(minutes=1)]
    assert a.envios_desde(T0) == [T0 + timedelta(minutes=1)]


def test_alerta_ejecutada_cuenta_como_envio(tmp_path):
    reloj = iter([T0 + timedelta(minutes=m) for m in range(10)])
    a = Almacen(tmp_path / "e.sqlite", reloj=lambda: next(reloj))
    a.registrar(cargar_propuesta(alerta()))
    pid = alerta()["id"]
    a.transicion(pid, "recibida", "ejecutando")
    a.transicion(pid, "ejecutando", "ejecutada")
    assert a.envios_desde(T0) == [T0 + timedelta(minutes=2)]
    assert a.envios_desde(T0 + timedelta(minutes=3)) == []


def test_no_gasto_recibida_a_ejecutando_y_tabla():
    assert "ejecutando" in TRANSICIONES["recibida"]
    assert TRANSICIONES["enviada"] == frozenset({"enviada", "aceptada", "rechazada", "caducada", "obsoleta"})
    assert TRANSICIONES["aceptada"] == frozenset({"ejecutando", "obsoleta", "fallida"})
    assert TRANSICIONES["ejecutando"] == frozenset({"ejecutada", "fallida", "discrepancia"})
    assert TRANSICIONES["ejecutada"] == frozenset()


def test_estructura_no_gasto_pasa_a_ejecutando(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    a.registrar(cargar_propuesta(estructura()))
    assert a.transicion("P-20261112-002", "recibida", "ejecutando")
    assert a.obtener("P-20261112-002").clase == "no_gasto"


def test_transicion_fuera_de_tabla(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    a.registrar(cargar_propuesta(presupuesto()))
    with pytest.raises(TransicionInvalida):
        a.transicion("P-20261112-004", "recibida", "ejecutada")


def test_id_duplicado_no_toca_la_primera(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    a.registrar(cargar_propuesta(presupuesto()))
    a.transicion("P-20261112-004", "recibida", "enviada")
    with pytest.raises(IdDuplicado):
        a.registrar(cargar_propuesta(presupuesto(motivo="otra")))
    f = a.obtener("P-20261112-004")
    assert f.estado == "enviada" and f.propuesta.motivo.startswith("ROAS")
    assert len(a.historial("P-20261112-004")) == 2


def test_en_estado_ordena_por_recibida_y_obtener_ausente(tmp_path):
    reloj = iter([T0 + timedelta(minutes=m) for m in range(10)])
    a = Almacen(tmp_path / "e.sqlite", reloj=lambda: next(reloj))
    a.registrar(cargar_propuesta(presupuesto(id="P-20261112-009")))
    a.registrar(cargar_propuesta(presupuesto(id="P-20261112-001")))
    assert [f.id for f in a.en_estado("recibida")] == ["P-20261112-009", "P-20261112-001"]
    assert a.en_estado("enviada") == []
    assert a.obtener("P-20261112-777") is None


def test_carrera_entre_dos_conexiones(tmp_path):
    ruta = tmp_path / "e.sqlite"
    Almacen(ruta).registrar(cargar_propuesta(presupuesto()))
    Almacen(ruta).transicion("P-20261112-004", "recibida", "enviada")
    res = []
    hilos = [threading.Thread(target=lambda: res.append(Almacen(ruta).transicion("P-20261112-004", "enviada", "aceptada")))
             for _ in range(8)]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    assert res.count(True) == 1


def test_update_id_y_cambios(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    assert a.ultimo_update() == 0
    a.marcar_update(900)
    a.marcar_update(899)
    assert a.ultimo_update() == 900
    assert a.ultimo_cambio("120245000000000101", "daily_budget") is None
    for m in (0, 20, 40, 70):
        a.registrar_cambio("120245000000000101", "daily_budget", T0 + timedelta(minutes=m))
    assert a.cambios_desde("120245000000000101", "daily_budget", T0 + timedelta(minutes=10)) == 3
    assert a.ultimo_cambio("120245000000000101", "daily_budget") == T0 + timedelta(minutes=70)
    with pytest.raises(ValueError):
        a.registrar_cambio("1", "daily_budget", datetime(2026, 11, 12))
    with pytest.raises(ValueError):
        a.cambios_desde("1", "daily_budget", datetime(2026, 11, 12))
    with pytest.raises(ValueError):
        a.envios_desde(datetime(2026, 11, 12))


def test_permisos_600_y_persistencia(tmp_path):
    ruta = tmp_path / "e.sqlite"
    Almacen(ruta).registrar(cargar_propuesta(presupuesto()))
    assert (ruta.stat().st_mode & 0o777) == 0o600
    assert Almacen(ruta).obtener("P-20261112-004").estado == "recibida"


def _limite():
    d = presupuesto(id="P-20261112-006", tipo="limite_ejecutor", operaciones=[
        {"entidad": "ejecutor", "id": "global", "campo": "max_ops_hora", "de_esperado": 10, "a": 20}])
    del d["cuenta"]
    return d


def test_gasto_y_limite_nunca_saltan_aceptada(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    a.registrar(cargar_propuesta(presupuesto()))
    a.registrar(cargar_propuesta(_limite()))
    for pid in ("P-20261112-004", "P-20261112-006"):
        with pytest.raises(TransicionInvalida):
            a.transicion(pid, "recibida", "ejecutando")
        assert a.obtener(pid).estado == "recibida" and len(a.historial(pid)) == 1


def test_noop_notificacion_puede_ejecutar(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    a.registrar(cargar_propuesta({"version": 1, "id": "P-20261112-001", "tipo": "noop",
                                  "creada": "2026-11-12T09:00:00-05:00", "origen": "/arranque"}))
    assert a.transicion("P-20261112-001", "recibida", "ejecutando")


def test_commit_fallido_no_deja_la_transaccion_abierta(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    real = a._con

    class Falla:
        fallar = True

        def execute(self, sql, *args):
            if sql == "COMMIT" and Falla.fallar:
                Falla.fallar = False
                raise OSError("disco lleno")
            return real.execute(sql, *args)

    a._con = Falla()
    with pytest.raises(OSError):
        a.registrar(cargar_propuesta(presupuesto()))
    a.registrar(cargar_propuesta(presupuesto()))  # la conexión sigue sirviendo
    assert a.obtener("P-20261112-004").estado == "recibida"


def test_transicion_de_id_inexistente_devuelve_false(tmp_path):
    a = Almacen(tmp_path / "e.sqlite")
    assert a.transicion("P-20261112-777", "recibida", "enviada") is False
