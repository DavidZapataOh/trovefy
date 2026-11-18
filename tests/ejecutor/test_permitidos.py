"""Dataset y página en los límites del ejecutor (plan 19, Tarea 9): edición por líneas de ``limites.yaml``.

Claude nunca edita ``limites.yaml``: esto lo ejecuta el usuario como ``trovefy-exec``. Todo en tmp_path.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from trovefy_ejecutor.limites import LimitesInvalidos, cargar_limites
from trovefy_ejecutor.permitidos import anadir_permitido, permitir_en_archivo

PLANTILLA = Path(__file__).resolve().parents[2] / "templates/ejecutor/limites.yaml"
CUENTA = "act_0000000000000000"
DATASET = "1111111111111111"
PAGINA = "2222222222222222"


def _archivo(tmp_path: Path, texto: str | None = None) -> Path:
    ruta = tmp_path / "limites.yaml"
    ruta.write_text(PLANTILLA.read_text(encoding="utf-8") if texto is None else texto, encoding="utf-8")
    os.chmod(ruta, 0o600)
    return ruta


def _cuenta(texto: str) -> dict:
    return yaml.safe_load(texto)["cuentas"][CUENTA]


def test_anadir_dataset_conserva_comentarios():
    texto = PLANTILLA.read_text(encoding="utf-8")
    nuevo, cambiado = anadir_permitido(texto, CUENTA, "datasets_permitidos", DATASET)
    assert cambiado is True
    assert _cuenta(nuevo)["datasets_permitidos"] == [DATASET]
    linea = next(ln for ln in nuevo.splitlines() if "datasets_permitidos:" in ln)
    assert "# se completa en el paso 11" in linea
    # El resto del archivo, comentarios incluidos, queda igual.
    assert [ln for ln in nuevo.splitlines() if "datasets_permitidos" not in ln] == \
           [ln for ln in texto.splitlines() if "datasets_permitidos" not in ln]


def test_anadir_pagina_y_dataset_juntos():
    texto, _ = anadir_permitido(PLANTILLA.read_text(encoding="utf-8"), CUENTA, "paginas_permitidas", PAGINA)
    texto, _ = anadir_permitido(texto, CUENTA, "datasets_permitidos", DATASET)
    texto, cambiado = anadir_permitido(texto, CUENTA, "datasets_permitidos", "3333333333333333")
    assert cambiado
    c = _cuenta(texto)
    assert c["paginas_permitidas"] == [PAGINA]
    assert c["datasets_permitidos"] == [DATASET, "3333333333333333"]
    assert all(isinstance(x, str) for x in c["datasets_permitidos"])


def test_anadir_es_idempotente():
    texto, _ = anadir_permitido(PLANTILLA.read_text(encoding="utf-8"), CUENTA, "datasets_permitidos", DATASET)
    otra, cambiado = anadir_permitido(texto, CUENTA, "datasets_permitidos", DATASET)
    assert cambiado is False and otra == texto


def test_anadir_lista_en_bloque():
    texto = PLANTILLA.read_text(encoding="utf-8").replace(
        "    datasets_permitidos: []             # se completa en el paso 11 (/tracking)",
        '    datasets_permitidos:                # se completa en el paso 11 (/tracking)\n      - "4444444444444444"')
    nuevo, cambiado = anadir_permitido(texto, CUENTA, "datasets_permitidos", DATASET)
    assert cambiado
    assert _cuenta(nuevo)["datasets_permitidos"] == ["4444444444444444", DATASET]


@pytest.mark.parametrize("malo", ["12ab", "", "act_1", "1" * 21, "1 2", "1\n- 2"])
def test_id_invalido(malo):
    with pytest.raises(ValueError):
        anadir_permitido(PLANTILLA.read_text(encoding="utf-8"), CUENTA, "datasets_permitidos", malo)


def test_clave_desconocida():
    with pytest.raises(ValueError):
        anadir_permitido(PLANTILLA.read_text(encoding="utf-8"), CUENTA, "cuentas_permitidas", DATASET)  # type: ignore[arg-type]


def test_cuenta_sin_seccion():
    with pytest.raises(ValueError):
        anadir_permitido(PLANTILLA.read_text(encoding="utf-8"), "act_1234", "datasets_permitidos", DATASET)


def test_permitir_en_archivo(tmp_path):
    ruta = _archivo(tmp_path)
    assert permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET) is True
    assert DATASET in cargar_limites(ruta).cuentas[CUENTA].datasets_permitidos
    assert ruta.stat().st_mode & 0o777 == 0o600
    assert permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET) is False
    assert not [p for p in tmp_path.iterdir() if p.name not in ("limites.yaml", "limites.yaml.lock")]  # sin tmp


def test_archivo_invalido_no_se_reemplaza(tmp_path):
    ruta = _archivo(tmp_path, PLANTILLA.read_text(encoding="utf-8").replace("version: 1", "version: 2"))
    antes = ruta.read_bytes()
    with pytest.raises(LimitesInvalidos):
        permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET)
    assert ruta.read_bytes() == antes
    assert sorted(p.name for p in tmp_path.iterdir()) == ["limites.yaml", "limites.yaml.lock"]


def test_no_sigue_enlaces(tmp_path):
    real = _archivo(tmp_path)
    enlace = tmp_path / "enlace.yaml"
    enlace.symlink_to(real)
    antes = real.read_bytes()
    with pytest.raises(ValueError):
        permitir_en_archivo(enlace, CUENTA, "datasets_permitidos", DATASET)
    assert real.read_bytes() == antes


# --- L5 (revisión T6–10): candado, cambio concurrente y fsync del directorio --------------------------------


def test_candado_ocupado_no_escribe(tmp_path):
    import fcntl

    ruta = _archivo(tmp_path)
    antes = ruta.read_bytes()
    fd = os.open(tmp_path / "limites.yaml.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        with pytest.raises(ValueError, match="otro proceso"):
            permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET, espera_s=0)
    finally:
        os.close(fd)
    assert ruta.read_bytes() == antes
    assert permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET, espera_s=0) is True
    assert (tmp_path / "limites.yaml.lock").stat().st_mode & 0o777 == 0o600


def test_cambio_del_servicio_a_la_vez_no_se_pisa(tmp_path, monkeypatch):
    """El servicio (plan 12) reescribe limites.yaml con os.replace y sin candado: si cambia mientras permitir
    valida su temporal, permitir no lo pisa."""
    from trovefy_ejecutor import permitidos

    ruta = _archivo(tmp_path)
    del_servicio = ruta.read_text(encoding="utf-8").replace("# ", "#  ", 1)
    real = permitidos.cargar_limites

    def cargar_y_cambiar(tmp, *a, **kw):
        lim = real(tmp, *a, **kw)
        ruta.write_text(del_servicio, encoding="utf-8")
        return lim

    monkeypatch.setattr(permitidos, "cargar_limites", cargar_y_cambiar)
    with pytest.raises(ValueError, match="cambió"):
        permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET, espera_s=0)
    assert ruta.read_text(encoding="utf-8") == del_servicio
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]


def test_fsync_del_directorio(tmp_path, monkeypatch):
    import stat

    from trovefy_ejecutor import permitidos

    ruta = _archivo(tmp_path)
    directorios: list[bool] = []
    real = os.fsync

    def fsync(fd):
        directorios.append(stat.S_ISDIR(os.fstat(fd).st_mode))
        real(fd)

    monkeypatch.setattr(permitidos.os, "fsync", fsync)
    assert permitir_en_archivo(ruta, CUENTA, "datasets_permitidos", DATASET, espera_s=0) is True
    assert directorios[-1] is True and False in directorios
