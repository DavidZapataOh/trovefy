import os
import stat

import pytest
from trovefy_ejecutor.candado import MENSAJE_OTRO, OtroEjecutorActivo, candado
from trovefy_ejecutor.deposito import DepositoRechazado, comprobar_origen


def test_segundo_candado_falla(tmp_path):
    ruta = tmp_path / "e.lock"
    with candado(ruta), pytest.raises(OtroEjecutorActivo), candado(ruta):
        pass
    with candado(tmp_path / "e.lock"):  # liberado al salir
        pass


def test_candado_0600_y_no_se_borra(tmp_path):
    ruta = tmp_path / "e.lock"
    with candado(ruta):
        assert stat.S_IMODE(ruta.stat().st_mode) == 0o600
    assert ruta.exists()


def test_candado_libera_con_excepcion(tmp_path):
    ruta = tmp_path / "e.lock"
    with pytest.raises(RuntimeError), candado(ruta):
        raise RuntimeError("x")
    with candado(ruta):
        pass


def test_candado_no_deja_fd_abierto(tmp_path):
    antes = set(os.listdir("/proc/self/fd"))
    with candado(tmp_path / "e.lock"):
        pass
    assert set(os.listdir("/proc/self/fd")) == antes


def test_mensaje_otro():
    assert "systemctl stop trovefy-ejecutor" in MENSAJE_OTRO


def test_deposito_de_otro_uid_se_rechaza(tmp_path):
    f = tmp_path / "P-20261112-001.json"
    f.write_text("{}")
    with pytest.raises(DepositoRechazado) as e:
        comprobar_origen(f, {os.getuid() + 1})
    assert e.value.uid == os.getuid() and "uid" in e.value.motivo
    comprobar_origen(f, {os.getuid()})


@pytest.mark.parametrize("nombre", ["hola.json", "P-20261112-1.json", "P-20261112-001.json.x"])
def test_nombre_no_valido(tmp_path, nombre):
    f = tmp_path / nombre
    f.write_text("{}")
    with pytest.raises(DepositoRechazado) as e:
        comprobar_origen(f, {os.getuid()})
    assert e.value.motivo == "nombre no válido"


def test_inexistente_es_rechazo(tmp_path):
    with pytest.raises(DepositoRechazado):
        comprobar_origen(tmp_path / "P-20261112-001.json", {os.getuid()})


def test_enlace_no_se_sigue(tmp_path):
    destino = tmp_path / "x"
    destino.write_text("{}")
    f = tmp_path / "P-20261112-001.json"
    f.symlink_to(destino)
    # lstat del enlace: uid propio, no lanza (Buzon.leer rechaza el enlace)
    comprobar_origen(f, {os.getuid()})
