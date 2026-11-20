"""Ficha de la tanda: 20 briefs, 10 elegidos (plan 21, Tarea 3)."""

import copy

import pytest
from trovefy.creativos.brief import BriefInvalido, escribir_ficha, validar_brief
from trovefy.creativos.config import cargar_config
from trovefy.creativos.contexto import cargar_contexto, ruta_tanda

from .ejemplos import AHORA, PAIS, P, brief_ok, crear_vault


@pytest.fixture
def base(tmp_path):
    vault = crear_vault(tmp_path)
    return vault, cargar_contexto(vault, P, PAIS), cargar_config(vault)


def _motivos(datos, ctx, cfg) -> str:
    with pytest.raises(BriefInvalido) as e:
        validar_brief(datos, ctx, cfg)
    return "\n".join(e.value.motivos)


def test_brief_ok(base):
    vault, ctx, cfg = base
    ficha = validar_brief(brief_ok(), ctx, cfg)
    assert len(ficha.candidatos) == 20 and len(ficha.elegidos) == 10
    assert ficha.nombre("AD01") == "AD01 G1 сън без хапчета"
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    ruta = escribir_ficha(vault, ctx, ficha, AHORA, carpeta)
    assert "Matriz hook × formato" in ruta.read_text(encoding="utf-8")


def test_faltan_candidatos(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"] = d["candidatos"][:19]
    assert "deben ser 20" in _motivos(d, ctx, cfg)


def test_reparto_7_3_sin_mezcla(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][9] = {**d["candidatos"][9], "formato": "tipografico"}
    d["candidatos"][9].pop("voz")
    assert "deben ser 3 y 7" in _motivos(d, ctx, cfg)


def test_reparto_sigue_mezcla_medida(tmp_path):
    vault = crear_vault(tmp_path, mezcla="## Top\n\n- imagen 60 % (6)\n")
    ctx, cfg = cargar_contexto(vault, P, PAIS), cargar_config(vault)
    formatos = ["tipografico", "broll_voz", "ugc", "mockup", "claymation", "3d", "meme", "escena",
                "ficha_del_producto", "tipografico"]
    ficha = validar_brief(brief_ok(formatos), ctx, cfg)
    assert sum(1 for e in ficha.elegidos if ficha.brief(e.ad).tipo == "video") == 4


def test_mezcla_85_da_8_2(tmp_path):
    vault = crear_vault(tmp_path, mezcla="## Top\n\n- imagen 85 % (17)\n")
    ctx, cfg = cargar_contexto(vault, P, PAIS), cargar_config(vault)
    formatos = ["tipografico", "broll_voz", "mockup", "meme", "zoom_lento", "escena", "ficha_del_producto",
                "tipografico", "meme", "antes_despues_del_uso"]
    ficha = validar_brief(brief_ok(formatos), ctx, cfg)  # con 2 vídeos no se exigen las cuatro plantillas
    assert sum(1 for e in ficha.elegidos if ficha.brief(e.ad).tipo == "imagen") == 8


def test_falta_una_plantilla_con_7_videos(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][2] = {**d["candidatos"][2], "formato": "scroll_pdf"}  # el ugc pasa a scroll del PDF
    assert "falta ugc" in _motivos(d, ctx, cfg)


def test_video_sin_voz_rechazado(base):
    _, ctx, cfg = base
    d = brief_ok()
    del d["candidatos"][1]["voz"]
    assert "un vídeo sin guion de voz" in _motivos(d, ctx, cfg)


def test_test_con_un_solo_angulo(base):
    _, ctx, cfg = base
    d = brief_ok()
    for c in d["candidatos"][:5]:
        c["angulo"] = "сън без хапчета"
    assert "probar ángulos" in _motivos(d, ctx, cfg)


def test_respaldo_inexistente(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][0]["respaldo"] = "core.mecanismo_pasos[9]"
    assert "respaldo «core.mecanismo_pasos[9]» no existe" in _motivos(d, ctx, cfg)


def test_titulo_largo(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][0]["titulo"] = "а" * 41
    assert "el título tiene 41 letras" in _motivos(d, ctx, cfg)


def test_gancho_fuera_de_las_125(base):
    _, ctx, cfg = base
    d = brief_ok()
    c = d["candidatos"][0]
    c["texto"] = "Методът ти помага да заспиш спокойно и без хапчета, само по пет минути вечер, с прости стъпки. " \
                 "Още повече думи тук за дължина. " + c["gancho"]
    assert "el gancho no está en las primeras 125" in _motivos(d, ctx, cfg)


def test_texto_en_otro_idioma(base):
    _, ctx, cfg = base
    d = brief_ok()
    c = d["candidatos"][0]
    c["gancho"] = "No puedes dormir"
    c["texto"] = ("No puedes dormir? El método te ayuda a dormir tranquila y sin pastillas, solo cinco minutos "
                  "cada noche con pasos sencillos para el cuerpo y la mente.")
    assert "el texto parece es, no bg" in _motivos(d, ctx, cfg)


def test_alfabeto_mezclado(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][0]["titulo"] = "Зaспи спокойно"  # «a» latina dentro de una palabra cirílica
    assert "mezcla cirílico" in _motivos(d, ctx, cfg)


def test_precio_mal_escrito(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][0]["precio_dicho"] = "само 13.90 EUR"
    assert "el precio dicho" in _motivos(d, ctx, cfg)


def test_referencia_ajena_rechazada(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][0]["referencias"] = ["mockup", "anuncio-competidor-07"]
    m = _motivos(d, ctx, cfg)
    assert "«anuncio-competidor-07» no es un medio propio" in m and "«mockup»" not in m


def test_texto_con_secreto(base):
    _, ctx, cfg = base
    d = copy.deepcopy(brief_ok())
    d["candidatos"][0]["texto"] += " sk-ant-api03-" + "A" * 90
    assert "forma de secreto" in _motivos(d, ctx, cfg)


def test_video_con_formato_de_estatico(base):
    _, ctx, cfg = base
    d = brief_ok()
    d["candidatos"][0]["tipo"] = "video"  # tipografico es un estático
    assert "que no es de video" in _motivos(d, ctx, cfg)
