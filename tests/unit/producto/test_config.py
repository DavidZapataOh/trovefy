from decimal import Decimal

import pytest
import yaml
from trovefy.producto.config import (
    PLANTILLA,
    ConfigInvalida,
    ConfigProducto,
    cargar_config,
    iniciar_config,
    tope_de,
)
from trovefy.vault import frontmatter

P = "p-0042-respira"


def _ruta(v):
    return v / "config" / "producto.yaml"


def _editar(v, clave, valor):
    datos = yaml.safe_load(_ruta(v).read_text(encoding="utf-8"))
    nodo = datos
    *camino, ultima = clave.split(".")
    for parte in camino:
        nodo = nodo[parte]
    nodo[ultima]["valor"] = valor
    _ruta(v).write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_plantilla_carga(tmp_path):
    iniciar_config(tmp_path)
    c = cargar_config(tmp_path)
    assert isinstance(c, ConfigProducto)
    assert c.tope_usd == Decimal("2.00")
    assert c.palabras_por_pagina == 350
    assert c.modelos_imagen == ("gpt-image-2",)
    assert c.resolucion == "1k"
    assert c.paginas_min == {"ebook": 20, "kit": 10, "bono": 4, "bump": 4, "upsell": 8}
    assert (c.seccion_palabras_min, c.puntuacion_min) == (300, 85)


def test_plantilla_hojas_valor_fuente_fecha():
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))

    def hojas(nodo):
        if isinstance(nodo, dict) and "valor" in nodo:
            yield nodo
        elif isinstance(nodo, dict):
            for v in nodo.values():
                yield from hojas(v)

    todas = list(hojas(datos))
    assert len(todas) == 11
    for h in todas:
        assert set(h) == {"valor", "fuente", "fecha"} and h["fuente"].strip()


@pytest.mark.parametrize("malo", [-1, "2.005", 0, "dos", 2.005, True, None])
def test_tope_negativo_o_float_raro(tmp_path, malo):
    iniciar_config(tmp_path)
    _editar(tmp_path, "apimart.tope_producto_usd", malo)
    with pytest.raises(ConfigInvalida):
        cargar_config(tmp_path)


@pytest.mark.parametrize(("clave", "malo"), [
    ("apimart.resolucion", "8k"),
    ("apimart.modelos_imagen", []),
    ("apimart.modelos_imagen", ["gpt-image-2", ""]),
    ("plan.palabras_por_pagina", 0),
    ("plan.palabras_por_pagina", 350.5),
    ("plan.paginas_min.ebook", -3),
    ("gates.puntuacion_min", 101),
])
def test_valores_invalidos(tmp_path, clave, malo):
    iniciar_config(tmp_path)
    _editar(tmp_path, clave, malo)
    with pytest.raises(ConfigInvalida):
        cargar_config(tmp_path)


def test_hoja_sin_fuente_es_invalida(tmp_path):
    iniciar_config(tmp_path)
    datos = yaml.safe_load(_ruta(tmp_path).read_text(encoding="utf-8"))
    del datos["apimart"]["resolucion"]["fuente"]
    _ruta(tmp_path).write_text(yaml.safe_dump(datos), encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="fuente"):
        cargar_config(tmp_path)


def test_falta_una_clave(tmp_path):
    iniciar_config(tmp_path)
    datos = yaml.safe_load(_ruta(tmp_path).read_text(encoding="utf-8"))
    del datos["plan"]["paginas_min"]["bump"]
    _ruta(tmp_path).write_text(yaml.safe_dump(datos), encoding="utf-8")
    with pytest.raises(ConfigInvalida, match="bump"):
        cargar_config(tmp_path)


def test_falta_archivo(tmp_path):
    with pytest.raises(FileNotFoundError, match="trovefy producto iniciar"):
        cargar_config(tmp_path)


def test_iniciar_no_sobrescribe(tmp_path):
    ruta = iniciar_config(tmp_path)
    assert ruta == _ruta(tmp_path)
    ruta.write_text("editado: true", encoding="utf-8")
    with pytest.raises(FileExistsError):
        iniciar_config(tmp_path)
    assert ruta.read_text(encoding="utf-8") == "editado: true"


def _producto(v, **meta):
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", {"tipo": "producto", **meta}, "# x\n")


def _registrada(nombre, zona="-05:00"):
    """``registrada`` coherente con el nombre ``AAAA-MM-DD-HHMMSS`` (hora local de la zona dada)."""
    return f"{nombre[:10]}T{nombre[11:13]}:{nombre[13:15]}:{nombre[15:17]}{zona}"


def _decision(v, nombre, nuevo, cita="súbelo a 3", producto=P, registrada=None):
    meta = {"tipo": "decision", "producto": producto, "decision": "tope_apimart", "tope_anterior_usd": "2.00",
            "tope_nuevo_usd": nuevo, "cita": cita,
            "registrada": _registrada(nombre) if registrada is None else registrada}
    frontmatter.escribir(v / "productos" / P / "decisiones" / f"{nombre}-tope-apimart.md", meta, "# Tope\n")


def test_tope_del_producto_gana(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd="3.00")
    _decision(tmp_path, "2026-11-14-100000", "3")
    assert tope_de(tmp_path, P, cfg) == Decimal("3.00")


def test_tope_del_producto_sin_decision_falla_cerrado(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd="300.00")
    with pytest.raises(ConfigInvalida, match="cita"):
        tope_de(tmp_path, P, cfg)


@pytest.mark.parametrize("decisiones", [
    [("2026-11-14-100000", "3", "")],                                    # sin cita
    [("2026-11-14-100000", "300", "súbelo"), ("2026-11-15-100000", "3", "a 3")],  # la última manda
    [("2026-11-14-100000", "4", "a 4")],                                  # no coincide
])
def test_tope_del_producto_no_coincide_con_la_decision(tmp_path, decisiones):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd="300")
    for nombre, nuevo, cita in decisiones:
        _decision(tmp_path, nombre, nuevo, cita)
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)


def test_tope_ignora_decision_sin_cita_posterior(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd="3")
    _decision(tmp_path, "2026-11-14-100000", "3", "a 3")
    _decision(tmp_path, "2026-11-15-100000", "300", "  ")  # sin cita: no cuenta
    assert tope_de(tmp_path, P, cfg) == Decimal(3)


def test_tope_decision_de_otro_producto_no_vale(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd="3")
    _decision(tmp_path, "2026-11-14-100000", "3", "a 3", producto="p-0043-dishai")
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)


def test_tope_ordena_por_registrada_y_no_por_el_nombre(tmp_path):
    """La decisión de las 06:00:05-05:00 (11:00:05Z) es posterior a la de las 10:00:01Z aunque su nombre ordene antes."""
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _decision(tmp_path, "2026-11-16-100000", "3", "a 3", registrada="2026-11-16T10:00:00+00:00")
    _decision(tmp_path, "2026-11-16-100001", "4.5", "a 4.5", registrada="2026-11-16T10:00:01+00:00")
    _decision(tmp_path, "2026-11-16-060005", "6", "a 6", registrada="2026-11-16T06:00:05-05:00")
    _producto(tmp_path, apimart_tope_usd="6")
    assert tope_de(tmp_path, P, cfg) == Decimal(6)
    _producto(tmp_path, apimart_tope_usd="4.5")
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)


def test_tope_no_depende_de_la_zona_del_proceso(tmp_path, monkeypatch):
    import time

    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _decision(tmp_path, "2026-11-16-100000", "3", "a 3", registrada="2026-11-16T10:00:00+00:00")
    _decision(tmp_path, "2026-11-16-060005", "6", "a 6", registrada="2026-11-16T06:00:05-05:00")
    _producto(tmp_path, apimart_tope_usd="6")
    for zona in ("UTC", "Asia/Tokyo", "America/Bogota"):
        monkeypatch.setenv("TZ", zona)
        time.tzset()
        assert tope_de(tmp_path, P, cfg) == Decimal(6), zona
    monkeypatch.delenv("TZ")
    time.tzset()


@pytest.mark.parametrize("registrada", [
    "2099-01-01T00:00:00+00:00",   # futura
    None,                           # sin registrada
    "2026-11-14T10:00:00",          # sin zona
    "ayer",                          # ilegible
])
def test_tope_rechaza_decisiones_futuras_o_sin_registrada(tmp_path, registrada):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _decision(tmp_path, "2026-11-14-100000", "3", "a 3")
    nombre = "2099-01-01-000000" if registrada and registrada.startswith("2099") else "2026-11-15-100000"
    _decision(tmp_path, nombre, "50", "a 50", registrada=registrada or "")
    if registrada is None:
        ruta = tmp_path / "productos" / P / "decisiones" / f"{nombre}-tope-apimart.md"
        meta, cuerpo = frontmatter.leer(ruta)
        del meta["registrada"]
        frontmatter.escribir(ruta, meta, cuerpo)
    _producto(tmp_path, apimart_tope_usd="50")
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)
    _producto(tmp_path, apimart_tope_usd="3")
    assert tope_de(tmp_path, P, cfg) == Decimal(3)


def test_tope_rechaza_nombre_que_no_cuadra_con_registrada(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _decision(tmp_path, "2026-11-14-100000", "3", "a 3")
    _decision(tmp_path, "2026-11-15-100000", "50", "a 50", registrada="2026-11-15T11:00:00-05:00")
    _producto(tmp_path, apimart_tope_usd="50")
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)


def test_mensaje_de_desajuste_explica_la_recuperacion(tmp_path):
    iniciar_config(tmp_path)
    _decision(tmp_path, "2026-11-14-100000", "3", "a 3")
    _producto(tmp_path, apimart_tope_usd="2.50")
    with pytest.raises(ConfigInvalida, match="mismo importe"):
        tope_de(tmp_path, P, cargar_config(tmp_path))


def test_tope_por_defecto(tmp_path):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    assert tope_de(tmp_path, P, cfg) == Decimal("2.00")  # sin PRODUCTO.md
    _producto(tmp_path)
    assert tope_de(tmp_path, P, cfg) == Decimal("2.00")  # sin la clave


@pytest.mark.parametrize("malo", ["-1", "3.005", 0])
def test_tope_del_producto_invalido(tmp_path, malo):
    iniciar_config(tmp_path)
    cfg = cargar_config(tmp_path)
    _producto(tmp_path, apimart_tope_usd=malo)
    with pytest.raises(ConfigInvalida):
        tope_de(tmp_path, P, cfg)


def test_tope_de_producto_mal_escrito(tmp_path):
    iniciar_config(tmp_path)
    with pytest.raises(ValueError):
        tope_de(tmp_path, "../x", cargar_config(tmp_path))


def test_valor_null_es_no_medido(tmp_path):
    iniciar_config(tmp_path)
    _editar(tmp_path, "plan.palabras_por_pagina", None)
    with pytest.raises(ConfigInvalida) as exc:
        cargar_config(tmp_path)
    assert str(exc.value) == "no medido: falta plan.palabras_por_pagina en config/producto.yaml"


def test_paginas_min_inmutable(tmp_path):
    iniciar_config(tmp_path)
    c = cargar_config(tmp_path)
    with pytest.raises(TypeError):
        c.paginas_min["ebook"] = 1  # type: ignore[index]


@pytest.mark.parametrize("malo", [["-modelo"], ["con espacio"], ["x" * 65], ["a;b"], [3]])
def test_modelos_imagen_mal_escritos(tmp_path, malo):
    iniciar_config(tmp_path)
    _editar(tmp_path, "apimart.modelos_imagen", malo)
    with pytest.raises(ConfigInvalida, match="modelos_imagen"):
        cargar_config(tmp_path)


def test_modelos_imagen_validos(tmp_path):
    iniciar_config(tmp_path)
    _editar(tmp_path, "apimart.modelos_imagen", ["gpt-image-2", "openai/gpt-4o_image.v1"])
    assert cargar_config(tmp_path).modelos_imagen == ("gpt-image-2", "openai/gpt-4o_image.v1")


def test_usa_hojas_publicas_de_economia():
    import inspect

    import trovefy.producto.config as pc
    from trovefy.economia import config as ec

    assert ec.es_hoja is ec._es_hoja and ec.revisar_hojas is ec._revisar_hojas
    fuente = inspect.getsource(pc)
    assert "_es_hoja" not in fuente and "_revisar_hojas" not in fuente


def test_fuente_de_resolucion_dice_lo_medido():
    """Ruling R-C: la documentación de gpt-image-2 (2026-11-16) da 15 proporciones y todas admiten 4k."""
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    fuente = datos["apimart"]["resolucion"]["fuente"]
    assert "6 proporciones" not in fuente and "15 proporciones" in fuente and "4k" in fuente
