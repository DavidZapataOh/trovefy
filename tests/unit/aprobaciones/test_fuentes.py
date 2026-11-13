import json
import os
import sys
import types
from datetime import datetime

import pytest
from trovefy.aprobaciones import fuentes
from trovefy.aprobaciones.fuentes import (
    BuzonNoDisponible,
    depositar,
    leer_estado,
    ruta_spool,
)

CUENTA = "act_0000000000000000"


@pytest.fixture
def spool(tmp_path, monkeypatch):
    s = tmp_path / "spool"
    (s / "estado").mkdir(parents=True)
    monkeypatch.setenv("TROVEFY_SPOOL", str(s))
    return s


def test_ruta_spool_por_defecto(monkeypatch):
    monkeypatch.delenv("TROVEFY_SPOOL", raising=False)
    assert str(ruta_spool()) == "/var/spool/trovefy"


def test_spool_inexistente_no_medido(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "no-existe"))
    r = leer_estado("latido")
    assert r.datos is None and r.motivo.startswith("no medido: el ejecutor aún no está instalado (no existe ")


def test_lee_latido_con_campos_extra(spool):
    d = {"fecha": "2026-11-12T10:00:00-05:00", "version": "1", "modo": "simulado", "pendientes": 2}
    (spool / "estado/latido.json").write_text(json.dumps(d))
    r = leer_estado("latido")
    assert r.datos == d and r.motivo is None


def test_sin_archivo(spool):
    assert leer_estado("stop").motivo == "no medido: el ejecutor no ha escrito stop.json"


def test_json_roto(spool):
    (spool / "estado/limites.json").write_text("{no")
    assert leer_estado("limites").motivo == "no medido: limites.json ilegible"


def test_no_es_objeto(spool):
    (spool / "estado/limites.json").write_text("[1]")
    assert leer_estado("limites").datos is None


def test_nombre_desconocido(spool):
    with pytest.raises(ValueError):
        leer_estado("../x")


def test_meta_de_otra_cuenta(spool):
    (spool / "estado/meta.json").write_text(json.dumps({"cuenta": "act_1", "currency": "COP", "offset": 100}))
    r = leer_estado("meta", cuenta=CUENTA)
    assert r.datos is None and r.motivo == "no medido: meta.json es de otra cuenta"
    (spool / "estado/meta.json").write_text(json.dumps({"cuenta": CUENTA, "currency": "COP", "offset": 100}))
    assert leer_estado("meta", cuenta=CUENTA).datos["offset"] == 100


def test_no_sigue_symlink_fuera_del_spool(spool, tmp_path):
    fuera = tmp_path / "secreto.json"
    fuera.write_text('{"x": 1}')
    os.symlink(fuera, spool / "estado/latido.json")
    r = leer_estado("latido")
    assert r.datos is None and "ilegible" in r.motivo


def test_sin_permiso(spool, monkeypatch):
    def boom(*a, **k):
        raise PermissionError
    monkeypatch.setattr(fuentes.os, "open", boom)
    assert leer_estado("latido").motivo.startswith("no medido: sin permiso para leer ")


@pytest.fixture
def buzon_falso(monkeypatch):
    llamadas = []
    m = types.ModuleType("trovefy.buzon")

    def dep(datos, *, spool, vault, ahora):
        llamadas.append((datos, spool, vault, ahora))
        return spool / "entrada" / "P-20261112-007.json"

    m.depositar = dep
    for n in ("StopActivo", "PropuestaInvalida", "IdDuplicado", "CupoAgotado"):
        setattr(m, n, type(n, (Exception,), {}))
    monkeypatch.setitem(sys.modules, "trovefy.buzon", m)
    return m, llamadas


def test_stop_bloquea_deposito(tmp_path, buzon_falso):
    _, llamadas = buzon_falso
    (tmp_path / ".trovefy").mkdir()
    (tmp_path / ".trovefy/STOP").write_text("")
    with pytest.raises(BuzonNoDisponible, match="STOP del cerebro activo: no se deposita nada"):
        depositar(tmp_path, {"tipo": "noop"})
    assert llamadas == []


def test_sin_modulo_buzon(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "trovefy.buzon", None)
    with pytest.raises(BuzonNoDisponible, match="plan 12"):
        depositar(tmp_path, {"tipo": "noop"})


def test_deposita_y_devuelve_id(tmp_path, spool, buzon_falso):
    _, llamadas = buzon_falso
    ahora = datetime(2026, 11, 12, 10, tzinfo=fuentes.ZONA_COT)
    assert depositar(tmp_path, {"tipo": "noop"}, ahora=lambda: ahora) == "P-20261112-007"
    _datos, sp, vault, a = llamadas[0]
    assert sp == spool and vault == tmp_path and a == ahora


@pytest.mark.parametrize("exc", ["StopActivo", "PropuestaInvalida", "IdDuplicado", "CupoAgotado"])
def test_traduce_errores(tmp_path, spool, buzon_falso, exc):
    m, _ = buzon_falso

    def dep(*a, **k):
        raise getattr(m, exc)("mensaje claro")

    m.depositar = dep
    with pytest.raises(BuzonNoDisponible, match="mensaje claro"):
        depositar(tmp_path, {})


def test_oserror_permiso(tmp_path, spool, buzon_falso):
    m, _ = buzon_falso

    def dep(*a, **k):
        raise PermissionError(13, "denegado")

    m.depositar = dep
    with pytest.raises(BuzonNoDisponible, match="sin permiso para depositar"):
        depositar(tmp_path, {})


def test_oserror_otro(tmp_path, spool, buzon_falso):
    m, _ = buzon_falso

    def dep(*a, **k):
        raise OSError("disco lleno")

    m.depositar = dep
    with pytest.raises(BuzonNoDisponible, match="disco lleno"):
        depositar(tmp_path, {})
