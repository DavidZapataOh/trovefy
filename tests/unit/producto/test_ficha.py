import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from trovefy.producto.config import iniciar_config
from trovefy.producto.ficha import (
    EstadoNoValido,
    Ficha,
    PiezaFicha,
    SinTresSenales,
    comprobar_precondiciones,
    crear_ficha,
    leer_ficha,
    slug_de,
)
from trovefy.vault import frontmatter
from trovefy.vault.producto import EstadoInesperado

P = "p-0042-respira"
FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "producto" / P
COT = ZoneInfo("America/Bogota")
AHORA = datetime(2026, 11, 16, 10, 0, tzinfo=COT)
MERCADOS = """\
ZZ: {idioma: es, moneda: EUR, zona: Europe/Madrid, banda_eur: [9, 19], estado: activo}
ZY: {idioma: bg, moneda: EUR, zona: Europe/Sofia, banda_eur: [9, 19], estado: activo}
"""


def _vault(tmp_path) -> Path:
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    (v / "config" / "mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    iniciar_config(v)
    shutil.copytree(FIXTURE, v / "productos" / P)
    return v


def _editar(v, nombre, cambio):
    ruta = v / "productos" / P / f"{nombre}.md"
    meta, cuerpo = frontmatter.leer(ruta)
    cambio(meta)
    frontmatter.escribir(ruta, meta, cuerpo)


def _estado(v, estado):
    _editar(v, "PRODUCTO", lambda m: m["paises"]["ZZ"].update(estado=estado))


# --- precondiciones ---------------------------------------------------------------------------------


def test_modelado_permite(tmp_path):
    v = _vault(tmp_path)
    assert comprobar_precondiciones(v, P, "ZZ", ahora=AHORA) is None


def test_estado_aprobado_no_produce(tmp_path):
    v = _vault(tmp_path)
    _estado(v, "aprobado")
    with pytest.raises(EstadoNoValido, match="primero /modelar") as exc:
        comprobar_precondiciones(v, P, "ZZ", ahora=AHORA)
    assert str(exc.value) == "ZZ está en «aprobado»: primero /modelar"
    assert isinstance(exc.value, EstadoInesperado)


def test_pais_sin_estado_no_produce(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(EstadoNoValido, match="primero /modelar"):
        comprobar_precondiciones(v, P, "ZY", ahora=AHORA)


@pytest.mark.parametrize("estado", ["producido", "con_landing", "con_checkout", "listo"])
def test_estado_posterior_permite(tmp_path, estado):
    v = _vault(tmp_path)
    _estado(v, estado)
    assert comprobar_precondiciones(v, P, "ZZ", ahora=AHORA) is None


def test_sin_tercera_senal_no_produce(tmp_path):
    v = _vault(tmp_path)
    _editar(v, "PRODUCTO", lambda m: m["senales"].update(se_puede_mejorar=None))
    with pytest.raises(SinTresSenales, match="se puede mejorar"):
        comprobar_precondiciones(v, P, "ZZ", ahora=AHORA)


@pytest.mark.parametrize("senal", ["ya_se_vende", "hueco_por_pais"])
def test_senal_de_auditoria_falsa_no_produce(tmp_path, senal):
    v = _vault(tmp_path)
    _editar(v, "AUDITORIA", lambda m: m["senales"].update({senal: False}))
    with pytest.raises(SinTresSenales):
        comprobar_precondiciones(v, P, "ZZ", ahora=AHORA)


def test_sin_auditoria_no_produce(tmp_path):
    v = _vault(tmp_path)
    (v / "productos" / P / "AUDITORIA.md").unlink()
    with pytest.raises(SinTresSenales, match="AUDITORIA.md"):
        comprobar_precondiciones(v, P, "ZZ", ahora=AHORA)


def _excepcion(v, nombre="2026-11-14-excepcion-r16.md", **cambios):
    meta = {"tipo": "decision", "fecha": "2026-11-14", "registrada": "2026-11-14T09:00:00-05:00",
            "fuente": "usuario", "producto": P, "pais": "ZZ", "regla": "R16", "senal": "se_puede_mejorar",
            "valor": None, "motivo": "no medida", "oferta": f"productos/{P}/OFERTA.md",
            "oferta_fecha": "2026-11-13", "cita": "produce igual, asumo el riesgo"}
    meta.update(cambios)
    frontmatter.escribir(v / "productos" / P / "decisiones" / nombre, meta, "Excepción.\n")


def test_excepcion_escrita_permite(tmp_path):
    v = _vault(tmp_path)
    _editar(v, "PRODUCTO", lambda m: m["senales"].update(se_puede_mejorar=None))
    _excepcion(v)
    assert comprobar_precondiciones(v, P, "ZZ", ahora=AHORA) is None


def test_excepcion_senales_anulada_no_permite(tmp_path):
    # Resolución 8: ``decisiones/*-excepcion-senales.md`` ya no vale.
    v = _vault(tmp_path)
    _editar(v, "PRODUCTO", lambda m: m["senales"].update(se_puede_mejorar=None))
    _excepcion(v, nombre="2026-11-14-excepcion-senales.md")
    with pytest.raises(SinTresSenales):
        comprobar_precondiciones(v, P, "ZZ", ahora=AHORA)


def test_tercera_en_auditoria_no_basta(tmp_path):
    # Resolución 8: la tercera se lee de PRODUCTO.md, no de AUDITORIA.md.
    v = _vault(tmp_path)
    _editar(v, "PRODUCTO", lambda m: m["senales"].update(se_puede_mejorar=False))
    _editar(v, "AUDITORIA", lambda m: m["senales"].update(se_puede_mejorar=True))
    with pytest.raises(SinTresSenales):
        comprobar_precondiciones(v, P, "ZZ", ahora=AHORA)


# --- ficha ------------------------------------------------------------------------------------------


def test_ficha_piezas_de_oferta_y_escalera(tmp_path):
    # Ruling R1: principal, bonos y bump siempre; u1/u2/u3/downsell solo con activo: true.
    v = _vault(tmp_path)
    ruta = crear_ficha(v, P, "ZZ", "sanitario", "ebook", AHORA)
    assert ruta == v / "productos" / P / "entregable" / "FICHA.md"
    ficha = leer_ficha(v, P)
    assert tuple(p.id for p in ficha.piezas) == ("principal", "bono-1", "bono-2", "bump", "u1")
    assert ficha.piezas[0] == PiezaFicha("principal", "Respira y duerme", "ebook", 20)
    assert ficha.piezas[1] == PiezaFicha("bono-1", "Audioguía de la respiración 4-7-8", "bono", 4)
    assert ficha.piezas[3] == PiezaFicha("bump", "Respira en la oficina", "bump", 4)
    assert ficha.piezas[4] == PiezaFicha("u1", "Calma para la ansiedad de la mañana", "upsell", 8)


def test_ficha_campos(tmp_path):
    v = _vault(tmp_path)
    crear_ficha(v, P, "ZZ", "sanitario", "ebook", AHORA)
    ficha = leer_ficha(v, P)
    assert isinstance(ficha, Ficha)
    assert (ficha.p_id, ficha.pais, ficha.idioma, ficha.slug) == (P, "ZZ", "es", "respira-lento")
    assert ficha.unidad_venta == "Un plan de 21 días con una práctica de 10 minutos"
    assert ficha.promesa == "Duerme mejor en 21 días con 10 minutos de respiración al día"
    assert ficha.avatar.startswith("Persona que trabaja con pantallas")
    assert (ficha.exigencia, ficha.tipo) == ("sanitario", "ebook")


def test_ficha_escribe_log(tmp_path):
    v = _vault(tmp_path)
    crear_ficha(v, P, "ZZ", "normal", "kit", AHORA)
    log = (v / "log.md").read_text(encoding="utf-8")
    assert "producto" in log and f"productos/{P}/entregable/FICHA.md" in log


def test_ficha_kit_usa_su_minimo(tmp_path):
    v = _vault(tmp_path)
    crear_ficha(v, P, "ZZ", "normal", "kit", AHORA)
    assert leer_ficha(v, P).piezas[0] == PiezaFicha("principal", "Respira y duerme", "kit", 10)


def test_paginas_del_entregable_ganan_si_son_mas(tmp_path):
    v = _vault(tmp_path)
    _editar(v, "OFERTA", lambda m: m["core"]["bonos"][0].update(paginas=12))
    _editar(v, "ESCALERA", lambda m: m["paises"]["ZZ"]["pasos"]["u1"].update(paginas=3))
    crear_ficha(v, P, "ZZ", "normal", "ebook", AHORA)
    piezas = {p.id: p for p in leer_ficha(v, P).piezas}
    assert piezas["bono-1"].paginas_objetivo == 12
    assert piezas["u1"].paginas_objetivo == 8


def test_todos_los_pasos_activos(tmp_path):
    v = _vault(tmp_path)

    def activar(m):
        for paso in ("u2", "u3", "downsell"):
            m["paises"]["ZZ"]["pasos"][paso]["activo"] = True

    _editar(v, "ESCALERA", activar)
    crear_ficha(v, P, "ZZ", "normal", "ebook", AHORA)
    ids = tuple(p.id for p in leer_ficha(v, P).piezas)
    assert ids == ("principal", "bono-1", "bono-2", "bump", "u1", "u2", "u3", "downsell")


def test_escalera_sin_pasos_falla(tmp_path):
    v = _vault(tmp_path)
    _editar(v, "ESCALERA", lambda m: m["paises"]["ZZ"].update(pasos=None))
    with pytest.raises(ValueError, match="ESCALERA.md"):
        crear_ficha(v, P, "ZZ", "normal", "ebook", AHORA)


def test_slug_transliterado(tmp_path):
    assert slug_de("Дишай") == "dishai"
    assert slug_de("Подреден дом") == "podreden-dom"
    assert slug_de("Щастие: юни, ябълка, жълт") == "shtastie-yuni-yabalka-zhalt"
    assert slug_de("Respiración  Lenta!") == "respiracion-lenta"
    v = _vault(tmp_path)
    _editar(v, "BRANDBOOK", lambda m: m.update(nombre_local="Дишай"))
    crear_ficha(v, P, "ZZ", "normal", "ebook", AHORA)
    assert leer_ficha(v, P).slug == "dishai"


def test_slug_vacio_falla():
    with pytest.raises(ValueError, match="nombre_local"):
        slug_de("¡¿?!")


def test_reescribe_conservando_avatar_editado(tmp_path):
    v = _vault(tmp_path)
    ruta = crear_ficha(v, P, "ZZ", "normal", "ebook", AHORA)
    meta, cuerpo = frontmatter.leer(ruta)
    meta["avatar"] = "Enfermera de turno de noche que no consigue dormir de día"
    frontmatter.escribir(ruta, meta, cuerpo)
    crear_ficha(v, P, "ZZ", "sanitario", "ebook", AHORA)
    ficha = leer_ficha(v, P)
    assert ficha.avatar == "Enfermera de turno de noche que no consigue dormir de día"
    assert ficha.exigencia == "sanitario"


@pytest.mark.parametrize(("exigencia", "tipo"), [("alta", "ebook"), ("normal", "libro")])
def test_valores_no_admitidos(tmp_path, exigencia, tipo):
    v = _vault(tmp_path)
    with pytest.raises(ValueError):
        crear_ficha(v, P, "ZZ", exigencia, tipo, AHORA)


def test_ficha_con_secreto_no_se_escribe(tmp_path):
    v = _vault(tmp_path)
    _editar(v, "OFERTA", lambda m: m["core"].update(avatar="clave sk-ant-api03-" + "A" * 90))
    with pytest.raises(ValueError, match="secreto"):
        crear_ficha(v, P, "ZZ", "normal", "ebook", AHORA)
    assert not (v / "productos" / P / "entregable" / "FICHA.md").exists()


def test_leer_ficha_sin_archivo(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(FileNotFoundError, match="FICHA.md"):
        leer_ficha(v, P)
