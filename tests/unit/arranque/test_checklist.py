import json

from trovify.arranque.estado import cargar
from trovify.arranque.verificadores import REGISTRO
from trovify.arranque.verificadores.checklist import CHECKLISTS, verificar_checklist
from trovify.cli import main

TODO = {"perfil_propio": True, "dos_fa": True, "sin_vpn": True}


def test_checklist_completo(tmp_path):
    r = verificar_checklist(tmp_path, "03", TODO)
    assert r.ok is True and r.evidencia
    datos = json.loads((tmp_path / r.evidencia[0]).read_text())
    assert datos["respuestas"] == TODO and datos["fecha"]


def test_checklist_con_un_no(tmp_path):
    r = verificar_checklist(tmp_path, "03", {**TODO, "dos_fa": False})
    assert r.ok is False and "2FA" in r.motivo and not r.evidencia


def test_checklist_incompleto(tmp_path):
    assert verificar_checklist(tmp_path, "03", {"perfil_propio": True}).ok is False


def test_textos_del_checklist():
    assert CHECKLISTS["03"]["sin_vpn"] == "No vas a usar VPN el día de crear el Business"


def test_verificar_03_sin_respuestas_no_mide(tmp_path):
    r = REGISTRO["03"](tmp_path)
    assert r.ok is None and "checklist 03" in r.motivo


def test_cli_checklist_verifica(tmp_path, capsys):
    args = ["arranque", "checklist", "03", "--vault", str(tmp_path)]
    for k in TODO:
        args += ["--respuesta", f"{k}=si"]
    assert main(args) == 0
    assert next(p for p in cargar(tmp_path) if p.id == "03").estado == "verificado"


def test_cli_checklist_con_no_y_respuesta_mala(tmp_path, capsys):
    assert main(["arranque", "checklist", "03", "--vault", str(tmp_path),
                 "--respuesta", "perfil_propio=si", "--respuesta", "dos_fa=no", "--respuesta", "sin_vpn=si"]) == 1
    assert main(["arranque", "checklist", "03", "--vault", str(tmp_path), "--respuesta", "dos_fa=quizá"]) == 2
    assert main(["arranque", "checklist", "03", "--vault", str(tmp_path), "--respuesta", "otra=si"]) == 2
    assert main(["arranque", "checklist", "99", "--vault", str(tmp_path)]) == 2
