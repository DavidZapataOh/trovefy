from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from trovefy import secretos
from trovefy.modelar.aprobacion import (
    APROBACIONES,
    aprobar,
    cerrar,
    excepcion_vigente,
    puede_avanzar,
    rechazar,
    registrar_excepcion,
)
from trovefy.modelar.salida import cargar_oferta
from trovefy.vault import frontmatter
from trovefy.vault.producto import estado_pais

P = "p-0042-kit-demo"
COT = ZoneInfo("America/Bogota")
AHORA = datetime(2026, 11, 13, 18, 0, tzinfo=COT)
CUERPO_OFERTA = (
    f"# Oferta · {P} · XE\n\n"
    f"Fuente: `productos/{P}/modelar.yaml`. Aprobación: presentada.\n\n"
    "## Teardown del original\n"
)
MOTIVO_FLOJO = "nuestra oferta no supera al original en los ejes flojos"


def _vault(tmp_path, *, senal=True, motivo="mejora en 3 ejes flojos", estado="aprobado", fecha="2026-11-13",
           aprobacion="presentada"):
    carpeta = tmp_path / "productos" / P
    frontmatter.escribir(carpeta / "PRODUCTO.md", {
        "tipo": "producto", "fecha": "2026-11-12", "oferta_id": "o-demo",
        "paises": {"XE": {"estado": estado}, "XR": {"estado": "auditado"}},
        "oferta": {"aprobacion": "presentada", "fecha": fecha},
        "senales": {"se_puede_mejorar": senal, "motivo": motivo, "fuente": f"productos/{P}/OFERTA.md"},
    }, f"# Producto {P}\n")
    frontmatter.escribir(carpeta / "decisiones" / "2026-11-12-eleccion.md", {
        "tipo": "decision", "fecha": "2026-11-12", "fuente": "usuario", "pais": "XE", "reserva": "XR",
        "producto": P, "fuera_de_mercados": False,
    }, "País elegido: XE\n")
    frontmatter.escribir(carpeta / "OFERTA.md", {
        "tipo": "oferta", "producto": P, "pais": "XE", "fecha": fecha,
        "fuente": f"productos/{P}/modelar.yaml", "aprobacion": aprobacion,
        "se_puede_mejorar": senal, "se_puede_mejorar_motivo": motivo,
        "core": {"promesa_h1": "Casa en orden en 7 días"},
    }, CUERPO_OFERTA)
    return tmp_path


def _producto(vault):
    return frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")[0]


def _log(vault):
    ruta = vault / "log.md"
    return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


def test_aprobaciones():
    assert APROBACIONES == ("presentada", "aprobada", "aprobada_tacita", "rechazada")


def test_cerrar_marca_tacita_y_avanza(tmp_path):
    v = _vault(tmp_path)
    linea = cerrar(v, P, AHORA)
    assert linea == f"Oferta de {P}: aprobada tácitamente; XE pasa a modelado"
    oferta = cargar_oferta(v, P)
    assert oferta["aprobacion"] == "aprobada_tacita"
    assert oferta["aprobacion_fecha"] == "2026-11-13T18:00:00-05:00"
    assert oferta["core"] == {"promesa_h1": "Casa en orden en 7 días"}  # lo demás intacto
    assert "Aprobación: aprobada tácitamente." in (v / "productos" / P / "OFERTA.md").read_text(encoding="utf-8")
    assert estado_pais(v, P, "XE") == "modelado"
    assert estado_pais(v, P, "XR") == "auditado"
    meta = _producto(v)
    assert meta["paises"]["XE"]["historial"][-1]["evidencia"] == [f"productos/{P}/OFERTA.md"]
    assert meta["oferta"]["aprobacion"] == "aprobada_tacita"
    assert meta["oferta"]["aprobacion_fecha"] == "2026-11-13T18:00:00-05:00"


def test_cerrar_es_idempotente(tmp_path):
    v = _vault(tmp_path)
    cerrar(v, P, AHORA)
    log = _log(v)
    oferta = (v / "productos" / P / "OFERTA.md").read_bytes()
    producto = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    linea = cerrar(v, P, datetime(2026, 11, 14, 9, 0, tzinfo=COT))
    assert _log(v) == log
    assert (v / "productos" / P / "OFERTA.md").read_bytes() == oferta
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == producto
    assert "XE ya está en modelado" in linea


def test_rechazar_bloquea(tmp_path):
    v = _vault(tmp_path)
    ruta = rechazar(v, P, "No me convence el precio", AHORA)
    assert ruta == v / "productos" / P / "decisiones" / "2026-11-13-oferta-rechazada.md"
    meta, cuerpo = frontmatter.leer(ruta)
    assert meta["tipo"] == "decision" and meta["fuente"] == "usuario"
    assert meta["cita"] == "No me convence el precio"
    assert "> No me convence el precio" in cuerpo
    assert cargar_oferta(v, P)["aprobacion"] == "rechazada"
    assert _producto(v)["oferta"]["aprobacion"] == "rechazada"
    log = _log(v)
    oferta = (v / "productos" / P / "OFERTA.md").read_bytes()
    linea = cerrar(v, P, AHORA)
    assert "rechazada" in linea
    assert _log(v) == log
    assert (v / "productos" / P / "OFERTA.md").read_bytes() == oferta
    assert estado_pais(v, P, "XE") == "aprobado"


def test_rechazar_tras_aprobar_falla(tmp_path):
    v = _vault(tmp_path)
    aprobar(v, P, "sí", AHORA)
    with pytest.raises(ValueError, match="la oferta ya quedó aprobada; para cambiarla, rehaz /modelar"):
        rechazar(v, P, "mejor no", AHORA)
    v2 = _vault(tmp_path / "otro")
    cerrar(v2, P, AHORA)
    with pytest.raises(ValueError, match="ya quedó aprobada"):
        rechazar(v2, P, "mejor no", AHORA)
    assert not list((v2 / "productos" / P / "decisiones").glob("*-oferta-rechazada.md"))


def test_senal_false_no_avanza_sin_excepcion(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    linea = cerrar(v, P, AHORA)
    assert estado_pais(v, P, "XE") == "aprobado"
    assert cargar_oferta(v, P)["aprobacion"] == "aprobada_tacita"
    assert "registras la excepción" in linea
    assert "se puede mejorar: no)" in linea


def test_senal_no_medida_no_avanza(tmp_path):
    v = _vault(tmp_path, senal=None, motivo="no medida: cobertura 60 < 70")
    linea = cerrar(v, P, AHORA)
    assert estado_pais(v, P, "XE") == "aprobado"
    assert "se puede mejorar: no medida" in linea


def test_excepcion_permite_avanzar(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    cerrar(v, P, AHORA)
    cita = "Lo sé, pero sigue: el original vende igual"
    ruta = registrar_excepcion(v, P, "XE", cita, datetime(2026, 11, 13, 18, 5, tzinfo=COT))
    assert ruta == v / "productos" / P / "decisiones" / "2026-11-13-excepcion-r16.md"
    meta, cuerpo = frontmatter.leer(ruta)
    assert meta["tipo"] == "decision" and meta["fuente"] == "usuario"
    assert meta["regla"] == "R16" and meta["senal"] == "se_puede_mejorar"
    assert meta["valor"] is False and meta["motivo"] == MOTIVO_FLOJO
    assert meta["cita"] == cita
    assert f"> {cita}" in cuerpo
    assert estado_pais(v, P, "XE") == "modelado"
    assert excepcion_vigente(v, P) == ruta


def test_excepcion_antes_de_aprobar_no_avanza_hasta_cerrar(tmp_path):
    v = _vault(tmp_path, senal=None, motivo="no medida")
    registrar_excepcion(v, P, "XE", "sigue", AHORA)
    assert estado_pais(v, P, "XE") == "aprobado"  # la oferta sigue presentada
    assert "XE pasa a modelado" in cerrar(v, P, AHORA)
    assert estado_pais(v, P, "XE") == "modelado"


def test_excepcion_anterior_a_la_oferta_no_vale(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    registrar_excepcion(v, P, "XE", "sigue", datetime(2026, 11, 10, 12, 0, tzinfo=COT))
    assert excepcion_vigente(v, P) is None
    linea = cerrar(v, P, AHORA)
    assert estado_pais(v, P, "XE") == "aprobado"
    assert "registras la excepción" in linea


def test_excepcion_de_otro_pais_falla(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    with pytest.raises(ValueError, match="XR"):
        registrar_excepcion(v, P, "XR", "sigue", AHORA)
    assert not (v / "productos" / P / "decisiones" / "2026-11-13-excepcion-r16.md").exists()


def test_excepcion_mismo_dia_no_pisa_la_anterior(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    primera = registrar_excepcion(v, P, "XE", "primera", AHORA)
    segunda = registrar_excepcion(v, P, "XE", "segunda", datetime(2026, 11, 13, 19, 0, tzinfo=COT))
    assert segunda == primera  # la del día con el nombre fijo es siempre la última
    assert frontmatter.leer(segunda)[0]["cita"] == "segunda"
    anteriores = list((v / "productos" / P / "decisiones").glob("2026-11-13-*-excepcion-r16.md"))
    assert [frontmatter.leer(a)[0]["cita"] for a in anteriores] == ["primera"]
    assert excepcion_vigente(v, P) == segunda


@pytest.mark.parametrize("cita", ["", "   ", "\n"])
def test_cita_vacia(tmp_path, cita):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    antes = _log(v)
    for llamada in (lambda: aprobar(v, P, cita, AHORA), lambda: rechazar(v, P, cita, AHORA),
                    lambda: registrar_excepcion(v, P, "XE", cita, AHORA)):
        with pytest.raises(ValueError, match="cita"):
            llamada()
    assert _log(v) == antes
    assert cargar_oferta(v, P)["aprobacion"] == "presentada"


def test_aprobar_guarda_cita_literal(tmp_path):
    v = _vault(tmp_path)
    linea = aprobar(v, P, "¡Vale! sí, sigue", AHORA)
    oferta = cargar_oferta(v, P)
    assert oferta["aprobacion"] == "aprobada"
    assert oferta["aprobacion_cita"] == "¡Vale! sí, sigue"
    assert _producto(v)["oferta"]["aprobacion_cita"] == "¡Vale! sí, sigue"
    assert estado_pais(v, P, "XE") == "modelado"
    assert linea == f"Oferta de {P}: aprobada; XE pasa a modelado"
    # cerrar después no la rebaja a tácita
    cerrar(v, P, AHORA)
    assert cargar_oferta(v, P)["aprobacion"] == "aprobada"


def test_aprobar_rechazada_falla(tmp_path):
    v = _vault(tmp_path)
    rechazar(v, P, "no", AHORA)
    with pytest.raises(ValueError, match="rechazada: vuelve a /modelar"):
        aprobar(v, P, "bueno, sí", AHORA)


def test_cita_con_secreto_no_escribe(tmp_path):
    v = _vault(tmp_path)
    oferta = (v / "productos" / P / "OFERTA.md").read_bytes()
    with pytest.raises(ValueError, match="secreto"):
        aprobar(v, P, "vale, mi clave es " + "sk" + "-" + "q" * 24, AHORA)
    assert (v / "productos" / P / "OFERTA.md").read_bytes() == oferta
    assert _log(v) == ""


def test_sin_revision_de_secretos_no_escribe(tmp_path, monkeypatch):
    v = _vault(tmp_path)
    oferta = (v / "productos" / P / "OFERTA.md").read_bytes()
    monkeypatch.setattr(secretos, "_candidatos_hooks", lambda: [tmp_path / "hooks"])
    with pytest.raises(secretos.RevisionSecretosNoDisponible):
        cerrar(v, P, AHORA)
    assert (v / "productos" / P / "OFERTA.md").read_bytes() == oferta
    assert estado_pais(v, P, "XE") == "aprobado"


def test_oferta_manda_sobre_producto(tmp_path):
    """R-T7b: tras rehacer, PRODUCTO.md puede traer restos; la aprobación se lee de OFERTA.md."""
    v = _vault(tmp_path, estado="modelado")
    ruta = v / "productos" / P / "PRODUCTO.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta["oferta"] = {"aprobacion": "aprobada", "aprobacion_cita": "vieja", "fecha": "2026-11-13"}
    frontmatter.escribir(ruta, meta, cuerpo)
    linea = cerrar(v, P, AHORA)
    assert cargar_oferta(v, P)["aprobacion"] == "aprobada_tacita"
    assert _producto(v)["oferta"]["aprobacion"] == "aprobada_tacita"
    assert _producto(v)["oferta"]["aprobacion_cita"] is None
    assert "XE ya está en modelado" in linea


def test_oferta_de_otro_pais_no_avanza(tmp_path):
    v = _vault(tmp_path)
    ruta = v / "productos" / P / "OFERTA.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta["pais"] = "XR"
    frontmatter.escribir(ruta, meta, cuerpo)
    linea = cerrar(v, P, AHORA)
    assert estado_pais(v, P, "XE") == "aprobado"
    assert "rehaz /modelar" in linea


def test_puede_avanzar():
    ok, _ = puede_avanzar({"aprobacion": "aprobada", "se_puede_mejorar": True}, None)
    assert ok
    ok, motivo = puede_avanzar({"aprobacion": "rechazada", "se_puede_mejorar": True}, None)
    assert (ok, motivo) == (False, "la oferta está rechazada: vuelve a /modelar")
    ok, motivo = puede_avanzar({"aprobacion": "presentada", "se_puede_mejorar": True}, None)
    assert not ok and "presentada" in motivo
    ok, motivo = puede_avanzar({"aprobacion": "aprobada_tacita", "se_puede_mejorar": False}, None)
    assert (ok, motivo) == (False, ("falta la tercera señal (se puede mejorar: no); sin las tres señales no se "
                                   "produce: o mejoras la oferta o registras la excepción con las palabras "
                                   "del usuario"))
    ok, motivo = puede_avanzar({"aprobacion": "aprobada_tacita", "se_puede_mejorar": None}, None)
    assert not ok and "(se puede mejorar: no medida)" in motivo


def test_puede_avanzar_con_excepcion(tmp_path):
    exc = tmp_path / "2026-11-13-excepcion-r16.md"
    assert not puede_avanzar({"aprobacion": "aprobada", "se_puede_mejorar": False}, exc)[0]  # no existe
    exc.write_text("x", encoding="utf-8")
    assert puede_avanzar({"aprobacion": "aprobada", "se_puede_mejorar": False}, exc)[0]
    assert not puede_avanzar({"aprobacion": "rechazada", "se_puede_mejorar": False}, exc)[0]


def test_sin_oferta(tmp_path):
    v = _vault(tmp_path)
    (v / "productos" / P / "OFERTA.md").unlink()
    with pytest.raises(FileNotFoundError, match="falta OFERTA.md: /modelar"):
        cerrar(v, P, AHORA)
    assert excepcion_vigente(v, P) is None


def test_excepcion_con_senal_medida_no_hace_falta(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="no hace falta excepción"):
        registrar_excepcion(v, P, "XE", "sigue", AHORA)
    assert not (v / "productos" / P / "decisiones" / "2026-11-13-excepcion-r16.md").exists()
