"""Validación de los emails del checkout (plan 19, Tarea 10). Los textos los escribe Claude en la sesión, en
``checkout/<PAIS>/emails/<clave>.md``; el código solo valida (D-01: sin escasez falsa ni testimonios inventados)."""
from __future__ import annotations

import pytest
from trovefy.checkout.emails import CLAVES_EMAIL, validar_email

ENTREGA_BG = """---
asunto: Вашето ръководство е готово
---
Здравейте,

Благодарим ви за поръчката. Ръководството „Спокойно тяло“ е прикачено към този имейл и можете да го
изтеглите веднага. Ако имате въпроси, просто отговорете на това писмо и ще ви помогнем.

Поздрави,
Екипът на Somatix
"""


def _email(tmp_path, texto: str, nombre: str = "entrega.md"):
    ruta = tmp_path / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


def test_claves():
    assert CLAVES_EMAIL == ("entrega", "seguimiento_72h")


def test_email_entrega_bg_ok(tmp_path):
    assert validar_email(_email(tmp_path, ENTREGA_BG), "bg", "entrega") == []


def test_email_con_testimonio_inventado(tmp_path):
    texto = ENTREGA_BG.replace("Поздрави,", "«Това ръководство промени живота ми!» — Мария, София\n\nПоздрави,")
    problemas = validar_email(_email(tmp_path, texto), "bg", "entrega")
    assert any("testimonio" in p for p in problemas)


def test_email_con_escasez(tmp_path):
    texto = ENTREGA_BG.replace("Поздрави,", "Остават само 2 места за бонуса!\n\nПоздрави,")
    problemas = validar_email(_email(tmp_path, texto), "bg", "entrega")
    assert any("escasez" in p and "остават" in p for p in problemas)


def test_email_en_otro_idioma(tmp_path):
    texto = ("---\nasunto: Tu guía está lista\n---\nHola,\n\nGracias por tu compra. La guía está adjunta a este "
             "correo y puedes descargarla ahora mismo. Si tienes dudas, responde a este mensaje.\n")
    problemas = validar_email(_email(tmp_path, texto), "bg", "entrega")
    assert any("idioma" in p for p in problemas)


def test_email_sin_asunto(tmp_path):
    texto = ENTREGA_BG.replace("asunto: Вашето ръководство е готово\n", "")
    assert any("asunto" in p for p in validar_email(_email(tmp_path, texto), "bg", "entrega"))


def test_email_con_secreto(tmp_path):
    texto = ENTREGA_BG.replace("Поздрави,", "EAAB" + "x7Yq" * 30 + "\n\nПоздрави,")
    assert any("secreto" in p for p in validar_email(_email(tmp_path, texto), "bg", "entrega"))


def test_email_que_no_existe_o_enlace(tmp_path):
    assert validar_email(tmp_path / "no.md", "bg", "entrega")
    real = _email(tmp_path, ENTREGA_BG)
    enlace = tmp_path / "enlace.md"
    enlace.symlink_to(real)
    assert any("enlace" in p for p in validar_email(enlace, "bg", "entrega"))


def test_clave_desconocida(tmp_path):
    with pytest.raises(ValueError):
        validar_email(_email(tmp_path, ENTREGA_BG), "bg", "bienvenida")
