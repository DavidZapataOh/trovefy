import pytest
import yaml
from trovify.arranque.estado import (
    ArranqueCorrupto,
    PasoDesconocido,
    ResultadoVerificacion,
    aplicar_verificacion,
    cargar,
    marcar_bloqueado,
    marcar_hecho,
    porcentaje_fase,
    siguiente,
)
from trovify.cli import main


def _ok(datos=None):
    return ResultadoVerificacion(True, ["e"], "ok", [], datos or {})


def test_se_crea_desde_el_catalogo(tmp_path):
    pasos = cargar(tmp_path)
    ids = [p.id for p in pasos]
    assert ids[:3] == ["00", "01", "02"] and "10b" in ids and "18" in ids
    assert all(p.estado == "pendiente" for p in pasos)
    assert (tmp_path / "config/arranque.yaml").exists()


def test_hecho_no_es_verificado(tmp_path):
    assert marcar_hecho(tmp_path, "04", "ya lo hice").estado == "hecho"
    sin = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(True, [], "ok", []))
    assert sin.estado == "hecho" and "sin evidencia" in sin.nota
    con = ResultadoVerificacion(True, ["config/evidencia/04-business.png"], "ID 123", [], {"business_id": "123"})
    p = aplicar_verificacion(tmp_path, "04", con)
    assert p.estado == "verificado" and p.datos == {"business_id": "123"} and p.fecha
    assert cargar(tmp_path)[4].estado == "verificado"


def test_ok_none_y_false(tmp_path):
    p = aplicar_verificacion(tmp_path, "05", ResultadoVerificacion(None, [], "no medido: sin red", []))
    assert p.estado == "pendiente" and p.nota == "no medido: sin red"
    aplicar_verificacion(tmp_path, "05", _ok())
    p = aplicar_verificacion(tmp_path, "05", ResultadoVerificacion(False, [], "falta 2FA", []))
    assert p.estado == "hecho" and p.nota == "falta 2FA"
    marcar_bloqueado(tmp_path, "06", "sin tarjeta")
    assert aplicar_verificacion(tmp_path, "06", ResultadoVerificacion(True, [], "x", [])).estado == "bloqueado"
    assert aplicar_verificacion(tmp_path, "06", _ok()).estado == "verificado"


def test_porcentaje_cuenta_el_cobro_una_vez(tmp_path):
    for i in ["00", "01", "02", "03", "04", "05", "06", "10b"]:
        aplicar_verificacion(tmp_path, i, _ok())
    assert porcentaje_fase(cargar(tmp_path)) == pytest.approx(8 / 12)
    aplicar_verificacion(tmp_path, "10", _ok())
    assert porcentaje_fase(cargar(tmp_path)) == pytest.approx(8 / 12)


def test_siguiente(tmp_path):
    assert siguiente(cargar(tmp_path)).id == "00"
    for i in [f"{n:02d}" for n in range(10)]:
        aplicar_verificacion(tmp_path, i, _ok())
    assert siguiente(cargar(tmp_path)).id == "10"
    marcar_bloqueado(tmp_path, "10", "sin pago a CO")
    assert siguiente(cargar(tmp_path)).id == "10b"
    aplicar_verificacion(tmp_path, "10b", _ok())
    assert siguiente(cargar(tmp_path)).id == "16"
    aplicar_verificacion(tmp_path, "16", _ok())
    assert siguiente(cargar(tmp_path)) is None


def test_paso_nuevo_del_catalogo_se_anade(tmp_path):
    cargar(tmp_path)
    f = tmp_path / "config/arranque.yaml"
    datos = yaml.safe_load(f.read_text())
    datos["pasos"] = [p for p in datos["pasos"] if p["id"] != "18"]
    datos["pasos"][0]["estado"] = "hecho"
    f.write_text(yaml.safe_dump(datos))
    pasos = cargar(tmp_path)
    assert pasos[0].estado == "hecho" and pasos[-1].id == "18" and pasos[-1].estado == "pendiente"


def test_yaml_corrupto_no_se_sobrescribe(tmp_path):
    (tmp_path / "config").mkdir()
    f = tmp_path / "config/arranque.yaml"
    f.write_text("pasos: [ {id: 00, estado: verificado")
    with pytest.raises(ArranqueCorrupto):
        cargar(tmp_path)
    assert f.read_text() == "pasos: [ {id: 00, estado: verificado"


def test_id_desconocido_y_log(tmp_path):
    with pytest.raises(PasoDesconocido):
        marcar_hecho(tmp_path, "99")
    marcar_hecho(tmp_path, "00")
    assert "arranque" in (tmp_path / "log.md").read_text()


def test_cli(tmp_path, capsys):
    v = str(tmp_path)
    assert main(["arranque", "hecho", "00", "--nota", "listo", "--vault", v]) == 0
    assert main(["arranque", "bloqueado", "01", "--motivo", "sin Obsidian", "--vault", v]) == 0
    capsys.readouterr()
    assert main(["arranque", "estado", "--vault", v]) == 0
    out = capsys.readouterr().out
    assert "Fase 0: 0/12 verificados (0 %)" in out and "bloqueado" in out
    assert main(["arranque", "siguiente", "--vault", v]) == 0
    assert "Siguiente: 00" in capsys.readouterr().out
    assert main(["arranque", "hecho", "99", "--vault", v]) == 2
    assert "99" in capsys.readouterr().err
