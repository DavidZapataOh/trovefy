import os
from datetime import UTC, datetime

import pytest
from trovefy_ejecutor.config import rutas_por_defecto
from trovefy_ejecutor.stop import activar_stop, quitar_stop, stop_activo


def test_ciclo(tmp_path):
    r = rutas_por_defecto({"TROVEFY_EJECUTOR_HOME": str(tmp_path)})
    assert not stop_activo(r)
    activar_stop(r, "/stop desde Telegram", datetime(2026, 11, 12, 20, tzinfo=UTC))
    assert stop_activo(r) and quitar_stop(r) and not stop_activo(r) and not quitar_stop(r)


def test_enlace_roto_cuenta_como_stop(tmp_path):
    r = rutas_por_defecto({"TROVEFY_EJECUTOR_HOME": str(tmp_path)})
    r.stop.parent.mkdir(parents=True)
    r.stop.symlink_to(tmp_path / "no-existe")
    assert stop_activo(r)


@pytest.mark.skipif(os.geteuid() == 0, reason="root lee aunque el directorio no tenga permisos")
def test_directorio_ilegible_cuenta_como_stop(tmp_path):
    r = rutas_por_defecto({"TROVEFY_EJECUTOR_HOME": str(tmp_path)})
    r.stop.parent.mkdir(parents=True)
    os.chmod(r.stop.parent, 0o000)
    try:
        assert stop_activo(r)
    finally:
        os.chmod(r.stop.parent, 0o700)


def test_activar_stop_rechaza_fecha_sin_zona(tmp_path):
    r = rutas_por_defecto({"TROVEFY_EJECUTOR_HOME": str(tmp_path)})
    with pytest.raises(ValueError):
        activar_stop(r, "/stop", datetime(2026, 11, 12, 20))
    assert not os.path.lexists(r.stop)
