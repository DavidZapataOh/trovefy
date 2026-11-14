from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from trovefy import secretos
from trovefy.vault import frontmatter
from trovefy.vault.producto import (
    ESTADOS_FASE2,
    EstadoInesperado,
    actualizar_producto,
    avanzar_estado,
    estado_pais,
    pais_elegido,
    ruta_producto,
)

P = "p-0042-kit-demo"
AHORA = datetime(2026, 11, 13, 9, 30, tzinfo=ZoneInfo("America/Bogota"))
CUERPO = (
    f"# Producto {P}\n\n"
    "- Oferta: [[wiki/ofertas/o-demo]]\n"
    f"- Auditoría: [[productos/{P}/AUDITORIA]]\n"
    "- Decisiones: carpeta decisiones/\n"
)


def _producto(vault, paises, **extra):
    meta = {"tipo": "producto", "fecha": "2026-11-12", "fuente": "wiki/ofertas/o-demo.md",
            "oferta_id": "o-demo", "paises": paises, **extra}
    ruta = vault / "productos" / P / "PRODUCTO.md"
    frontmatter.escribir(ruta, meta, CUERPO)
    return ruta


def _cuerpo_crudo(ruta):
    return ruta.read_text(encoding="utf-8").split("\n---\n", 1)[1]


def test_estados_fase2():
    assert ESTADOS_FASE2 == ("aprobado", "modelado", "producido", "con_landing", "con_checkout", "listo")


def test_avanza_de_aprobado_a_modelado(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "aprobado", "nota": "x"}}, referencia={"pais": "XE"})
    antes = _cuerpo_crudo(ruta)
    devuelta = avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", "OFERTA.md aprobada", "modelar", AHORA)
    assert devuelta == ruta
    meta, cuerpo = frontmatter.leer(ruta)
    assert meta["paises"]["XE"]["estado"] == "modelado"
    assert meta["paises"]["XE"]["nota"] == "x"
    assert meta["paises"]["XE"]["historial"] == [
        {"de": "aprobado", "a": "modelado", "fecha": "2026-11-13T09:30:00-05:00",
         "evidencia": ["OFERTA.md aprobada"]},
    ]
    assert meta["oferta_id"] == "o-demo"
    assert meta["referencia"] == {"pais": "XE"}
    assert cuerpo == CUERPO
    assert _cuerpo_crudo(ruta) == antes
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert log.count("\n") == 1
    assert "modelar" in log and "XE" in log and "aprobado → modelado" in log
    assert f"productos/{P}/PRODUCTO.md" in log


def test_evidencia_lista_y_historial_se_acumula(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado", "historial": [
        {"de": "aprobado", "a": "modelado", "fecha": "2026-11-12T08:00:00-05:00", "evidencia": ["a"]}]}})
    avanzar_estado(tmp_path, P, "XE", "modelado", "producido", ["entregable/QC.md", "entregable/x.pdf"],
                   "producto", AHORA)
    hist = frontmatter.leer(ruta)[0]["paises"]["XE"]["historial"]
    assert [h["a"] for h in hist] == ["modelado", "producido"]
    assert hist[1]["evidencia"] == ["entregable/QC.md", "entregable/x.pdf"]


def test_no_avanza_desde_otro_estado(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "auditado"}})
    antes = ruta.read_bytes()
    with pytest.raises(EstadoInesperado) as e:
        avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", "x", "modelar", AHORA)
    assert str(e.value) == "XE está en auditado: modelar solo avanza desde aprobado"
    assert isinstance(e.value, ValueError)
    assert ruta.read_bytes() == antes
    assert not (tmp_path / "log.md").exists()


def test_pais_sin_estado(tmp_path):
    _producto(tmp_path, {})
    with pytest.raises(EstadoInesperado, match="XE está en sin estado: modelar solo avanza desde aprobado"):
        avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", "x", "modelar", AHORA)


def test_no_salta_estados(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    antes = ruta.read_bytes()
    with pytest.raises(ValueError) as e:
        avanzar_estado(tmp_path, P, "XE", "aprobado", "producido", "x", "modelar", AHORA)
    assert not isinstance(e.value, EstadoInesperado)
    with pytest.raises(ValueError):
        avanzar_estado(tmp_path, P, "XE", "modelado", "aprobado", "x", "modelar", AHORA)
    with pytest.raises(ValueError):
        avanzar_estado(tmp_path, P, "XE", "listo", "otro", "x", "modelar", AHORA)
    assert ruta.read_bytes() == antes


def test_evidencia_vacia(tmp_path):
    _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    for mala in ("", "  ", [], ["ok", ""]):
        with pytest.raises(ValueError, match="evidencia"):
            avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", mala, "modelar", AHORA)


def test_no_toca_otros_paises(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "aprobado"}, "XR": {"estado": "auditado", "k": [1, 2]}})
    avanzar_estado(tmp_path, P, "xe", "aprobado", "modelado", "x", "modelar", AHORA)
    paises = frontmatter.leer(ruta)[0]["paises"]
    assert paises["XR"] == {"estado": "auditado", "k": [1, 2]}
    assert paises["XE"]["estado"] == "modelado"


def test_estado_pais(tmp_path):
    _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    assert estado_pais(tmp_path, P, "XE") == "aprobado"
    assert estado_pais(tmp_path, P, "XR") is None


def test_producto_inexistente(tmp_path):
    with pytest.raises(FileNotFoundError, match="/trovefy:auditar"):
        estado_pais(tmp_path, P, "XE")
    with pytest.raises(FileNotFoundError):
        avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", "x", "modelar", AHORA)


def test_actualizar_no_borra_ni_cambia_estado(tmp_path):
    hist = [{"de": "aprobado", "a": "modelado", "fecha": "f", "evidencia": ["e"]}]
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado", "historial": hist, "landing": {"url": "u", "qa": {"fecha": "f"}}}},
                     senales={"ya_se_vende": True})
    devuelta = actualizar_producto(
        tmp_path, P,
        {"paises": {"XE": {"estado": "listo", "historial": [], "landing": {"qa": {"version": 2}}}},
         "senales": {"se_puede_mejorar": True, "motivo": "autopsia"},
         "oferta": {"aprobacion": "presentada", "fecha": "2026-11-13"}},
        [], "modelar", AHORA,
    )
    assert devuelta == ruta
    meta, cuerpo = frontmatter.leer(ruta)
    xe = meta["paises"]["XE"]
    assert xe["estado"] == "modelado"
    assert xe["historial"] == hist
    assert xe["landing"] == {"url": "u", "qa": {"fecha": "f", "version": 2}}
    assert meta["senales"] == {"ya_se_vende": True, "se_puede_mejorar": True, "motivo": "autopsia"}
    assert meta["oferta"] == {"aprobacion": "presentada", "fecha": "2026-11-13"}
    assert meta["oferta_id"] == "o-demo" and meta["tipo"] == "producto"
    assert cuerpo == CUERPO
    log = (tmp_path / "log.md").read_text(encoding="utf-8")
    assert log.count("\n") == 1 and "modelar" in log


def test_actualizar_no_sustituye_mapa_por_escalar(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado"}}, senales={"ya_se_vende": True})
    antes = ruta.read_bytes()
    with pytest.raises(ValueError, match="senales"):
        actualizar_producto(tmp_path, P, {"senales": None}, [], "modelar", AHORA)
    with pytest.raises(ValueError, match="paises"):
        actualizar_producto(tmp_path, P, {"paises": "XE"}, [], "modelar", AHORA)
    assert ruta.read_bytes() == antes


def test_enlaces_no_se_duplican(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado"}})
    enlaces = [f"- Oferta propia: [[productos/{P}/OFERTA]]", f"- Escalera: [[productos/{P}/ESCALERA]]",
               "- Oferta: [[wiki/ofertas/o-demo]]"]
    actualizar_producto(tmp_path, P, {}, enlaces, "modelar", AHORA)
    actualizar_producto(tmp_path, P, {}, enlaces, "modelar", AHORA)
    cuerpo = frontmatter.leer(ruta)[1]
    assert cuerpo.startswith(CUERPO)
    for e in enlaces:
        assert cuerpo.count(e) == 1
    assert cuerpo.endswith(f"- Escalera: [[productos/{P}/ESCALERA]]\n")


def test_actualizar_rechaza_secretos(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado"}})
    antes = ruta.read_bytes()
    with pytest.raises(ValueError, match="secreto"):
        actualizar_producto(tmp_path, P, {"nota": "clave " + "sk" + "-" + "q" * 24}, [], "modelar", AHORA)
    assert ruta.read_bytes() == antes


def test_sin_revision_de_secretos_no_escribe(tmp_path, monkeypatch):
    ruta = _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    antes = ruta.read_bytes()
    monkeypatch.setattr(secretos, "_candidatos_hooks", lambda: [tmp_path / "hooks"])
    with pytest.raises(secretos.RevisionSecretosNoDisponible):
        avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", "x", "modelar", AHORA)
    assert ruta.read_bytes() == antes


def _eleccion(vault, nombre, pais, reserva=None, fuera=False):
    meta = {"tipo": "decision", "fecha": nombre[:10], "fuente": "usuario", "pais": pais, "reserva": reserva,
            "producto": P, "fuera_de_mercados": fuera}
    ruta = vault / "productos" / P / "decisiones" / nombre
    frontmatter.escribir(ruta, meta, "# Elección\n")
    return ruta


def test_pais_elegido_salta_fuera_de_mercados(tmp_path):
    _eleccion(tmp_path, "2026-11-10-eleccion.md", "XR")
    buena = _eleccion(tmp_path, "2026-11-11-1-eleccion.md", "XE", "XR")
    _eleccion(tmp_path, "2026-11-11-eleccion.md", "ZZ", fuera=True)
    _eleccion(tmp_path, "2026-11-09-eleccion.md", "XR")
    assert pais_elegido(tmp_path, P) == ("XE", "XR", buena)


def test_pais_elegido_respeta_mercados(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "mercados.yaml").write_text(
        "XE: {idioma: xe, moneda: EUR, zona: Europe/Paris, banda_eur: [11.9, 15.9], estado: activo}\n",
        encoding="utf-8")
    buena = _eleccion(tmp_path, "2026-11-10-eleccion.md", "XE")
    _eleccion(tmp_path, "2026-11-11-eleccion.md", "XR")
    assert pais_elegido(tmp_path, P) == ("XE", None, buena)


def test_pais_elegido_sin_eleccion(tmp_path):
    with pytest.raises(FileNotFoundError) as e:
        pais_elegido(tmp_path, P)
    assert str(e.value) == "falta la elección de país en decisiones/: /auditar"
    _eleccion(tmp_path, "2026-11-11-eleccion.md", "ZZ", fuera=True)
    with pytest.raises(FileNotFoundError):
        pais_elegido(tmp_path, P)


def test_p_id_invalido(tmp_path):
    for malo in ("../x", "p-42-x", "p-0042-Kit", "p-0042-kit/../../x", ""):
        with pytest.raises(ValueError):
            ruta_producto(tmp_path, malo)
    with pytest.raises(ValueError):
        estado_pais(tmp_path, "../x", "XE")
    assert ruta_producto(tmp_path, P) == tmp_path / "productos" / P / "PRODUCTO.md"


def test_pais_invalido(tmp_path):
    _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    with pytest.raises(ValueError):
        avanzar_estado(tmp_path, P, "X/E", "aprobado", "modelado", "x", "modelar", AHORA)


def test_actualizar_solo_estado_no_crea_pais(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado"}})
    actualizar_producto(tmp_path, P, {"paises": {"XR": {"estado": "listo"}}}, [], "modelar", AHORA)
    assert frontmatter.leer(ruta)[0]["paises"] == {"XE": {"estado": "modelado"}}


def test_actualizar_normaliza_codigo_de_pais(tmp_path):
    ruta = _producto(tmp_path, {"BG": {"estado": "modelado", "nota": "x"}})
    actualizar_producto(tmp_path, P, {"paises": {"bg": {"landing": {"url": "u"}}}}, [], "modelar", AHORA)
    assert frontmatter.leer(ruta)[0]["paises"] == {"BG": {"estado": "modelado", "nota": "x",
                                                           "landing": {"url": "u"}}}


def test_actualizar_rechaza_pais_mal_escrito_o_duplicado(tmp_path):
    ruta = _producto(tmp_path, {"BG": {"estado": "modelado"}})
    antes = ruta.read_bytes()
    with pytest.raises(ValueError, match="país mal escrito"):
        actualizar_producto(tmp_path, P, {"paises": {"B/G": {"a": 1}}}, [], "modelar", AHORA)
    with pytest.raises(ValueError, match="BG"):
        actualizar_producto(tmp_path, P, {"paises": {"bg": {"a": 1}, "BG": {"b": 2}}}, [], "modelar", AHORA)
    assert ruta.read_bytes() == antes


def test_ahora_sin_zona_horaria(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    antes = ruta.read_bytes()
    ingenua = datetime(2026, 11, 13, 9, 30)
    with pytest.raises(ValueError, match="zona horaria"):
        avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", "x", "modelar", ingenua)
    with pytest.raises(ValueError, match="zona horaria"):
        actualizar_producto(tmp_path, P, {"nota": "x"}, [], "modelar", ingenua)
    assert ruta.read_bytes() == antes


def test_evidencia_tupla_se_guarda_como_lista(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", ("a.md", "b.md"), "modelar", AHORA)
    assert frontmatter.leer(ruta)[0]["paises"]["XE"]["historial"][0]["evidencia"] == ["a.md", "b.md"]


def test_evidencia_de_tipo_erroneo(tmp_path):
    _producto(tmp_path, {"XE": {"estado": "aprobado"}})
    for mala in (3, None, {"a": "b"}, b"x", [1]):
        with pytest.raises(ValueError, match="evidencia"):
            avanzar_estado(tmp_path, P, "XE", "aprobado", "modelado", mala, "modelar", AHORA)


def test_actualizar_sin_cambios_no_escribe(tmp_path):
    ruta = _producto(tmp_path, {"XE": {"estado": "modelado"}}, senales={"ya_se_vende": True})
    antes = ruta.read_bytes()
    devuelta = actualizar_producto(tmp_path, P, {"senales": {"ya_se_vende": True},
                                                 "paises": {"XE": {"estado": "listo"}}},
                                   ["- Oferta: [[wiki/ofertas/o-demo]]"], "modelar", AHORA)
    assert devuelta == ruta
    assert ruta.read_bytes() == antes
    assert not (tmp_path / "log.md").exists()
