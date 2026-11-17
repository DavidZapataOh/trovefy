"""Tarea 4 del plan 18: escritura y diacríticos por idioma (textos propios, escritos para el test)."""

from trovefy.landing.diacriticos import IDIOMAS_REVISADOS, Hallazgo, revisar_texto

BG = ("Somatix е кратък наръчник с леки упражнения за тялото. Всяка вечер отделяте десет минути, сядате "
      "удобно и следвате простите стъпки. Раменете се отпускат, дишането става по-бавно, а сънят идва "
      "по-лесно. Не са нужни уреди, само малко място и желание да опитате.")
RO_SIN = ("Aceste exercitii sunt simple si se pot face acasa in fiecare seara dupa o zi lunga de lucru. "
          "Stai pe un scaun sau pe pat si urmezi pasii din ghid unul cate unul fara grija. Umerii se relaxeaza "
          "incet iar respiratia devine mai lenta si mai calma. Nu ai nevoie de aparate speciale sau de mult "
          "spatiu doar de zece minute libere si de putina rabdare cu tine insuti pana cand corpul invata "
          "ritmul nou al serii linistite.")


def _reglas(h: list[Hallazgo]) -> list[str]:
    return [x.regla for x in h]


def test_idiomas_revisados():
    assert IDIOMAS_REVISADOS == ("bg", "ro")


def test_bg_correcto_sin_hallazgos():
    assert revisar_texto(BG, "bg", frozenset({"Somatix"})) == []


def test_bg_marca_sin_permitir_baja_la_escritura():
    texto = "Somatix Somatix Somatix Somatix. " + "Това е кратък текст."
    assert "escritura" in _reglas(revisar_texto(texto, "bg"))


def test_bg_letras_rusas_fallan():
    h = revisar_texto("Это упражнение помогает телу расслабиться вечером перед сном.", "bg")
    rusas = [x for x in h if x.regla == "letra_rusa"]
    assert rusas and "Это" in rusas[0].detalle and all(x.bloquea for x in h)


def test_bg_homoglifo_latino_falla():
    texto = BG.replace("упражнения", "упрaжнения")  # «a» latina dentro de una palabra cirílica
    h = [x for x in revisar_texto(texto, "bg", frozenset({"Somatix"})) if x.regla == "homoglifo"]
    assert len(h) == 1 and "упрaжнения" in h[0].detalle and h[0].bloquea


def test_bg_mucho_latin_falla():
    texto = ("Tova uprazhnenie pomaga na tyaloto da se otpusne vecher predi san i da diShate bavno. "
             "Това упражнение помага на тялото да се отпусне вечер преди сън и да дишате бавно.")
    h = [x for x in revisar_texto(texto, "bg") if x.regla == "escritura"]
    assert len(h) == 1 and "95" in h[0].detalle


def test_bg_letra_de_otro_alfabeto_cirilico():
    h = revisar_texto("Това є текст", "bg")
    assert "letra_ajena" in _reglas(h)


def test_ro_correcto_sin_hallazgos():
    texto = ("Aceste exerciții ajută corpul să se relaxeze seara. Stai pe un scaun, respiri încet și urmezi "
             "pașii din ghid. În zece minute umerii se lasă în jos și somnul vine mai ușor.")
    assert revisar_texto(texto, "ro") == []


def test_ro_cedilla_falla():
    h = revisar_texto("Aceste exerciţii ajută corpul să se relaxeze seara, înainte de somn.", "ro")
    ced = [x for x in h if x.regla == "cedilla"]
    assert len(ced) == 1 and "exerciţii" in ced[0].detalle and "ț" in ced[0].detalle


def test_ro_sin_diacriticos_falla():
    assert len(RO_SIN.split()) >= 60
    assert "sin_diacriticos" in _reglas(revisar_texto(RO_SIN, "ro"))


def test_ro_corto_sin_diacriticos_no_salta():
    assert "sin_diacriticos" not in _reglas(revisar_texto("Ghid simplu pentru seara", "ro"))


def test_idioma_distinto_falla():
    texto = "This short guide helps your body relax every evening with ten minutes of gentle movement."
    h = revisar_texto(texto, "bg")
    assert "idioma_distinto" in _reglas(h)
    assert any("en" in x.detalle for x in h if x.regla == "idioma_distinto")


def test_texto_corto_no_decide_idioma():
    assert "idioma_distinto" not in _reglas(revisar_texto("Купи", "bg"))


def test_idioma_sin_reglas_no_medido():
    h = revisar_texto("Te ćwiczenia pomagają ciału się rozluźnić wieczorem przed snem i dają spokój.", "pl")
    assert h == [Hallazgo("sin_reglas", "no medido: sin reglas de diacríticos para pl", bloquea=False)]
