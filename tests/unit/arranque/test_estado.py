import pytest
import yaml
from trovefy.arranque.estado import (
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
from trovefy.cli import main


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
    assert "Siguiente: 02" in capsys.readouterr().out  # 00 hecho y 01 bloqueado se saltan
    assert main(["arranque", "hecho", "99", "--vault", v]) == 2
    assert "99" in capsys.readouterr().err


def test_evidencia_vieja_no_revive_un_paso(tmp_path):
    aplicar_verificacion(tmp_path, "04", _ok())
    p = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(False, [], "cambió", []))
    assert p.estado == "hecho" and p.evidencia == []
    p = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(True, [], "ok", []))
    assert p.estado == "hecho" and p.evidencia == []


def test_reverificacion_reemplaza_evidencia_y_conserva_nota(tmp_path):
    aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(True, ["vieja"], "ID 1", [], {"a": "1"}))
    p = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(True, ["nueva"], "ID 2", [], {"b": "2"}))
    assert p.evidencia == ["nueva"] and p.datos == {"a": "1", "b": "2"}
    p = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(True, [], "x", []))
    assert p.estado == "verificado" and p.nota.startswith("ID 2") and "sin evidencia" in p.nota
    p = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(None, [], "no medido: red", []))
    assert p.nota.startswith("ID 2") and "no medido: red" in p.nota


def test_siguiente_con_bloqueados_no_dice_completa(tmp_path, capsys):
    v = str(tmp_path)
    for i in [f"{n:02d}" for n in range(10)] + ["16"]:
        aplicar_verificacion(tmp_path, i, _ok())
    marcar_bloqueado(tmp_path, "10", "sin pago a CO")
    marcar_bloqueado(tmp_path, "10b", "sin KYC")
    capsys.readouterr()
    assert main(["arranque", "siguiente", "--vault", v]) == 0
    out = capsys.readouterr().out
    assert "completa" not in out and "sin pago a CO" in out and "sin KYC" in out


def test_sin_evidencia_conserva_el_motivo_de_un_bloqueo(tmp_path):
    marcar_bloqueado(tmp_path, "03", "falta el DNI")
    p = aplicar_verificacion(tmp_path, "03", ResultadoVerificacion(None, [], "no medido: sin red", []))
    assert p.estado == "bloqueado" and p.nota == "falta el DNI · no medido: sin red"
    p = aplicar_verificacion(tmp_path, "03", ResultadoVerificacion(None, [], "no medido: sin red", []))
    assert p.nota == "falta el DNI · no medido: sin red"  # no se repite


def test_nota_sin_motivo_no_deja_separador(tmp_path):
    marcar_bloqueado(tmp_path, "03", "falta el DNI")
    p = aplicar_verificacion(tmp_path, "03", ResultadoVerificacion(None, [], "", []))
    assert p.nota == "falta el DNI"


def test_fallo_conserva_el_motivo_de_un_bloqueo(tmp_path):
    marcar_bloqueado(tmp_path, "03", "falta el DNI")
    p = aplicar_verificacion(tmp_path, "03", ResultadoVerificacion(False, [], "clave rechazada", []))
    assert p.estado == "bloqueado" and p.nota == "falta el DNI · clave rechazada"
    p = aplicar_verificacion(tmp_path, "04", ResultadoVerificacion(False, [], "falla", []))
    assert p.nota == "falla"


def test_siguiente_salta_hecho_y_bloqueado(tmp_path):
    marcar_hecho(tmp_path, "00")
    assert siguiente(cargar(tmp_path)).id == "01"
    aplicar_verificacion(tmp_path, "01", _ok())
    marcar_bloqueado(tmp_path, "02", "espera /trovefy:cazar (plan 07)")
    assert siguiente(cargar(tmp_path)).id == "03"


def test_siguiente_cli_con_hechos_no_dice_completa(tmp_path, capsys):
    for i in [f"{n:02d}" for n in range(10)] + ["16"]:
        aplicar_verificacion(tmp_path, i, _ok())
    marcar_hecho(tmp_path, "05", "esperando revisión")
    marcar_bloqueado(tmp_path, "10", "x")
    marcar_bloqueado(tmp_path, "10b", "y")
    aplicar_verificacion(tmp_path, "05", ResultadoVerificacion(False, [], "falla", []))
    capsys.readouterr()
    assert main(["arranque", "siguiente", "--vault", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "completa" not in out and "05" in out


def test_verificado_a_mano_sin_evidencia_cuenta_como_hecho(tmp_path):
    cargar(tmp_path)
    ruta = tmp_path / "config" / "arranque.yaml"
    d = yaml.safe_load(ruta.read_text())
    for e in d["pasos"]:
        if e["id"] in ("00", "01"):
            e["estado"] = "verificado"
            e["evidencia"] = ["config/evidencia/x.json"] if e["id"] == "01" else []
    ruta.write_text(yaml.safe_dump(d, allow_unicode=True))
    por = {p.id: p for p in cargar(tmp_path)}
    assert por["00"].estado == "hecho" and por["01"].estado == "verificado"
    assert porcentaje_fase(list(por.values())) == pytest.approx(1 / 12)


def test_estado_cli_muestra_la_nota_truncada(tmp_path, capsys):
    marcar_bloqueado(tmp_path, "02", "espera /trovefy:cazar (plan 07)")
    marcar_hecho(tmp_path, "03", "n" * 200)
    capsys.readouterr()
    assert main(["arranque", "estado", "--vault", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "espera /trovefy:cazar (plan 07)" in out
    assert "n" * 200 not in out and "n" * 70 in out


def _con_verificador(monkeypatch, funcion):
    from trovefy.arranque.verificadores import REGISTRO
    monkeypatch.setitem(REGISTRO, "03", funcion)


def test_cli_encabezado_de_arreglos_coincide_con_la_convencion(tmp_path, capsys, monkeypatch):
    _con_verificador(monkeypatch, lambda v: ResultadoVerificacion(False, [], "mal", ["haz esto"]))
    assert main(["arranque", "verificar", "03", "--vault", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "Para arreglarlo (los comandos de sistema van en una terminal de Ubuntu (WSL) aparte):" in out
    assert "con `!`" not in out


def test_cli_excepcion_del_verificador_es_no_medido(tmp_path, capsys, monkeypatch):
    def explota(v):
        raise ValueError("secreto-sk-123")

    _con_verificador(monkeypatch, explota)
    assert main(["arranque", "verificar", "03", "--vault", str(tmp_path)]) == 3
    cap = capsys.readouterr()
    assert "no medido: error del verificador (ValueError)" in cap.out
    assert "secreto-sk-123" not in cap.out + cap.err and "Traceback" not in cap.err
    log = (tmp_path / "log.md").read_text()
    assert log.count("verificar 03") == 1 and "secreto-sk-123" not in log


def test_siguiente_no_manda_a_hotmart_si_whop_esta_hecho(tmp_path):
    for i in [f"{n:02d}" for n in range(10)]:
        marcar_bloqueado(tmp_path, i, "x")
    marcar_hecho(tmp_path, "10")
    s = siguiente(cargar(tmp_path))
    assert s is None or s.id != "10b"
    aplicar_verificacion(tmp_path, "10", _ok())
    s = siguiente(cargar(tmp_path))
    assert s is None or s.id != "10b"


def test_siguiente_ofrece_hotmart_solo_con_whop_bloqueado(tmp_path):
    for i in [f"{n:02d}" for n in range(10)]:
        marcar_bloqueado(tmp_path, i, "x")
    assert siguiente(cargar(tmp_path)).id == "10"
    marcar_bloqueado(tmp_path, "10", "Whop no paga a Colombia")
    assert siguiente(cargar(tmp_path)).id == "10b"
