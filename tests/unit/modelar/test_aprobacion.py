from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from trovefy import secretos
from trovefy.modelar.aprobacion import (
    APROBACIONES,
    MOTIVO_RECHAZADA,
    Cierre,
    aprobar,
    cerrar,
    excepcion_vigente,
    oferta_aprobada,
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
    linea = cerrar(v, P, AHORA).linea
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
    linea = cerrar(v, P, datetime(2026, 11, 14, 9, 0, tzinfo=COT)).linea
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
    linea = cerrar(v, P, AHORA).linea
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
    linea = cerrar(v, P, AHORA).linea
    assert estado_pais(v, P, "XE") == "aprobado"
    assert cargar_oferta(v, P)["aprobacion"] == "aprobada_tacita"
    assert "registras la excepción" in linea
    assert "se puede mejorar: no)" in linea


def test_senal_no_medida_no_avanza(tmp_path):
    v = _vault(tmp_path, senal=None, motivo="no medida: cobertura 60 < 70")
    linea = cerrar(v, P, AHORA).linea
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
    assert "XE pasa a modelado" in cerrar(v, P, AHORA).linea
    assert estado_pais(v, P, "XE") == "modelado"


def test_excepcion_anterior_a_la_oferta_no_vale(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    registrar_excepcion(v, P, "XE", "sigue", datetime(2026, 11, 10, 12, 0, tzinfo=COT))
    assert excepcion_vigente(v, P) is None
    linea = cerrar(v, P, AHORA).linea
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
    linea = cerrar(v, P, AHORA).linea
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
    linea = cerrar(v, P, AHORA).linea
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


# --- ronda de revisión de la Tarea 8 ----------------------------------------------------------------

SECRETO = "sk" + "-" + "q" * 24


def _ruta(v, nombre):
    return v / "productos" / P / nombre


def _foto(v):
    """Todo lo que hay en el producto y el log, para comprobar que no se escribe nada."""
    carpeta = v / "productos" / P
    archivos = {r.relative_to(carpeta).as_posix(): r.read_bytes() for r in carpeta.rglob("*") if r.is_file()}
    return archivos, _log(v)


def _lineas_log(v):
    return [x for x in _log(v).splitlines() if x]


@pytest.mark.parametrize("cita", ["vale\n\t" + SECRETO, "sí\x07" + SECRETO, "ok\r\n\t\t" + SECRETO])
def test_secreto_tras_escape_yaml_no_escribe(tmp_path, cita):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    antes = _foto(v)
    for llamada in (lambda: aprobar(v, P, cita, AHORA), lambda: rechazar(v, P, cita, AHORA),
                    lambda: registrar_excepcion(v, P, "XE", cita, AHORA)):
        with pytest.raises(ValueError, match="secreto") as exc:
            llamada()
        assert SECRETO not in str(exc.value)
    assert _foto(v) == antes


def test_secreto_en_la_oferta_tras_escape_no_escribe(tmp_path):
    """Un secreto escondido en otro campo de OFERTA.md tampoco pasa al reescribirla."""
    v = _vault(tmp_path)
    ruta = _ruta(v, "OFERTA.md")
    meta, cuerpo = frontmatter.leer(ruta)
    meta["core"] = {"nota\t" + SECRETO: "x", "promesa_h1": ["a", "b\n\t" + SECRETO]}
    frontmatter.escribir(ruta, meta, cuerpo)
    antes = _foto(v)
    with pytest.raises(ValueError, match="secreto"):
        cerrar(v, P, AHORA)
    assert _foto(v) == antes


@pytest.mark.parametrize("cita", ["vale\x85sigue", "sí\u0080", "\u009fok"])
def test_cita_con_control_c1(tmp_path, cita):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    antes = _foto(v)
    for llamada in (lambda: aprobar(v, P, cita, AHORA), lambda: rechazar(v, P, cita, AHORA),
                    lambda: registrar_excepcion(v, P, "XE", cita, AHORA)):
        with pytest.raises(ValueError, match=r"caracteres de control.*U\+00[89][0-9A-F]"):
            llamada()
    assert _foto(v) == antes


def _excepcion(v, nombre, **campos):
    meta = {"tipo": "decision", "fecha": "2026-11-13", "registrada": "2026-11-13T18:00:00-05:00",
            "fuente": "usuario", "producto": P, "pais": "XE", "regla": "R16", "senal": "se_puede_mejorar",
            "valor": False, "motivo": MOTIVO_FLOJO, "oferta": f"productos/{P}/OFERTA.md",
            "oferta_fecha": "2026-11-13", "cita": "sigue"}
    meta.update(campos)
    meta = {k: x for k, x in meta.items() if x is not ...}
    ruta = _ruta(v, "decisiones") / nombre
    frontmatter.escribir(ruta, meta, "x\n")
    return ruta


def test_excepcion_completa_a_mano_vale(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    ruta = _excepcion(v, "2026-11-13-excepcion-r16.md")
    assert excepcion_vigente(v, P, AHORA) == ruta


@pytest.mark.parametrize("campos", [
    {"fecha": "2099-01-01", "registrada": "2099-01-01T00:00:00-05:00"},  # futura
    {"fecha": "2026-11-13", "registrada": "2026-11-12T23:00:00-05:00"},  # posterior a registrada
    {"registrada": ...},
    {"registrada": "ayer"},
    {"cita": ...},
    {"cita": "   "},
    {"cita": 42},
    {"fuente": "claude"},
    {"fuente": ...},
    {"senal": "otra"},
    {"senal": ...},
    {"pais": "XR"},
    {"producto": "p-0043-otro"},
    {"oferta_fecha": "2026-11-12"},
    {"oferta_fecha": ...},
    {"fecha": "2026-11-13T00:00:00"},  # fecha no estricta
    {"fecha": "2026-11-13x"},
    {"regla": "R15"},
    {"tipo": "nota"},
])
def test_excepcion_falsa_o_incompleta_se_ignora(tmp_path, campos):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    _excepcion(v, "2026-11-13-excepcion-r16.md", **campos)
    assert excepcion_vigente(v, P, AHORA) is None
    linea = cerrar(v, P, AHORA).linea
    assert estado_pais(v, P, "XE") == "aprobado"
    assert "registras la excepción" in linea


def test_excepcion_minima_falsa_se_ignora(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    frontmatter.escribir(_ruta(v, "decisiones") / "2099-01-01-excepcion-r16.md",
                         {"tipo": "decision", "regla": "R16", "producto": P, "pais": "XE", "fecha": "2099-01-01"},
                         "x\n")
    assert excepcion_vigente(v, P, AHORA) is None
    cerrar(v, P, AHORA)
    assert estado_pais(v, P, "XE") == "aprobado"


def test_excepcion_ilegible_se_salta(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    dir_ = _ruta(v, "decisiones")
    (dir_ / "2026-11-13-2-excepcion-r16.md").write_text("---\nfecha: [2026\n---\nroto\n", encoding="utf-8")
    (dir_ / "2026-11-13-3-excepcion-r16.md").write_bytes(b"---\nfecha: \xff\xfe\n---\n")
    (dir_ / "2026-11-13-4-excepcion-r16.md").write_text("---\n- una\n- lista\n---\n", encoding="utf-8")
    (dir_ / "2026-11-13-5-excepcion-r16.md").mkdir()
    assert excepcion_vigente(v, P, AHORA) is None
    assert "registras la excepción" in cerrar(v, P, AHORA).linea
    buena = _excepcion(v, "2026-11-13-excepcion-r16.md")
    assert excepcion_vigente(v, P, AHORA) == buena
    assert "XE pasa a modelado" in cerrar(v, P, AHORA).linea


def test_orden_de_excepciones(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    d13a = registrar_excepcion(v, P, "XE", "a", datetime(2026, 11, 13, 18, 0, tzinfo=COT))
    registrar_excepcion(v, P, "XE", "b", datetime(2026, 11, 13, 19, 0, tzinfo=COT))
    d14 = registrar_excepcion(v, P, "XE", "c", datetime(2026, 11, 14, 8, 0, tzinfo=COT))
    dir_ = _ruta(v, "decisiones")
    assert sorted(r.name for r in dir_.glob("*-excepcion-r16.md")) == [
        "2026-11-13-1-excepcion-r16.md", "2026-11-13-excepcion-r16.md", "2026-11-14-excepcion-r16.md"]
    assert frontmatter.leer(dir_ / "2026-11-13-1-excepcion-r16.md")[0]["cita"] == "a"
    assert d13a == dir_ / "2026-11-13-excepcion-r16.md"
    # el día manda; dentro del día, la hora de registro (no el nombre)
    assert excepcion_vigente(v, P, datetime(2026, 11, 14, 9, 0, tzinfo=COT)) == d14
    hoy13 = datetime(2026, 11, 13, 20, 0, tzinfo=COT)
    assert frontmatter.leer(excepcion_vigente(v, P, hoy13))[0]["cita"] == "b"  # la del 14 aún es futura
    _excepcion(v, "2026-11-13-7-excepcion-r16.md", registrada="2026-11-13T19:30:00-05:00", cita="d")
    assert frontmatter.leer(excepcion_vigente(v, P, hoy13))[0]["cita"] == "d"


def test_oferta_aprobada(tmp_path):
    v = _vault(tmp_path)
    ok, motivo = oferta_aprobada(v, P)
    assert not ok and "presentada" in motivo
    cerrar(v, P, AHORA)
    assert oferta_aprobada(v, P) == (True, "oferta aprobada tácitamente")
    v2 = _vault(tmp_path / "b")
    aprobar(v2, P, "sí", AHORA)
    assert oferta_aprobada(v2, P) == (True, "oferta aprobada")
    v3 = _vault(tmp_path / "c")
    rechazar(v3, P, "no", AHORA)
    assert oferta_aprobada(v3, P) == (False, MOTIVO_RECHAZADA)
    _ruta(v3, "OFERTA.md").unlink()
    assert oferta_aprobada(v3, P) == (False, "falta OFERTA.md: /modelar")


def test_oferta_aprobada_de_otro_producto(tmp_path):
    v = _vault(tmp_path, aprobacion="aprobada")
    ruta = _ruta(v, "OFERTA.md")
    meta, cuerpo = frontmatter.leer(ruta)
    meta["producto"] = "p-0043-otro"
    frontmatter.escribir(ruta, meta, cuerpo)
    ok, motivo = oferta_aprobada(v, P)
    assert not ok and "p-0043-otro" in motivo and "rehaz /modelar" in motivo


def test_cerrar_rechazada_bloquea(tmp_path):
    v = _vault(tmp_path)
    rechazar(v, P, "no", AHORA)
    cierre = cerrar(v, P, AHORA)
    assert isinstance(cierre, Cierre)
    assert cierre == Cierre(MOTIVO_RECHAZADA, bloqueado=True)
    assert str(cierre) == "la oferta está rechazada: vuelve a /modelar"
    assert estado_pais(v, P, "XE") == "aprobado"


def test_cerrar_no_bloquea_en_lo_demas(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    cierre = cerrar(v, P, AHORA)
    assert not cierre.bloqueado and str(cierre) == cierre.linea
    v2 = _vault(tmp_path / "b")
    assert cerrar(v2, P, AHORA) == Cierre(f"Oferta de {P}: aprobada tácitamente; XE pasa a modelado", False)


@pytest.mark.parametrize("aprobacion", ["aprobada", "aprobada_tacita", "rechazada"])
def test_cerrar_repara_producto_tras_escritura_interrumpida(tmp_path, aprobacion):
    v = _vault(tmp_path, aprobacion=aprobacion)
    ruta = _ruta(v, "OFERTA.md")
    meta, cuerpo = frontmatter.leer(ruta)
    cita_vieja = "vale" if aprobacion == "aprobada" else None
    meta.update(aprobacion_fecha="2026-11-13T17:00:00-05:00", aprobacion_cita=cita_vieja)
    frontmatter.escribir(ruta, meta, cuerpo)
    oferta = ruta.read_bytes()
    assert _producto(v)["oferta"]["aprobacion"] == "presentada"  # quedó a medias
    cerrar(v, P, AHORA)
    assert ruta.read_bytes() == oferta
    copia = _producto(v)["oferta"]
    assert (copia["aprobacion"], copia["aprobacion_fecha"], copia["aprobacion_cita"]) == (
        aprobacion, "2026-11-13T17:00:00-05:00", meta["aprobacion_cita"])
    assert copia["fecha"] == "2026-11-13"  # fusiona, no borra
    # ya igual: no escribe ni anota nada
    antes = _foto(v)
    cerrar(v, P, AHORA)
    assert _foto(v) == antes


def test_aprobar_repara_producto_tras_escritura_interrumpida(tmp_path):
    v = _vault(tmp_path, aprobacion="aprobada", estado="modelado")
    ruta = _ruta(v, "OFERTA.md")
    meta, cuerpo = frontmatter.leer(ruta)
    meta.update(aprobacion_fecha="2026-11-13T17:00:00-05:00", aprobacion_cita="vale")
    frontmatter.escribir(ruta, meta, cuerpo)
    aprobar(v, P, "otra vez sí", AHORA)
    copia = _producto(v)["oferta"]
    assert (copia["aprobacion"], copia["aprobacion_cita"]) == ("aprobada", "vale")  # la cita no cambia
    antes = _foto(v)
    aprobar(v, P, "otra vez sí", AHORA)
    assert _foto(v) == antes


def test_excepcion_con_oferta_rechazada_falla(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    rechazar(v, P, "no", AHORA)
    antes = _foto(v)
    with pytest.raises(ValueError, match="^la oferta está rechazada: vuelve a /modelar$"):
        registrar_excepcion(v, P, "XE", "sigue", AHORA)
    assert _foto(v) == antes


def test_excepcion_con_oferta_de_otro_producto_falla(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    ruta = _ruta(v, "OFERTA.md")
    meta, cuerpo = frontmatter.leer(ruta)
    meta["producto"] = "p-0043-otro"
    frontmatter.escribir(ruta, meta, cuerpo)
    antes = _foto(v)
    with pytest.raises(ValueError, match="p-0043-otro.*rehaz /modelar"):
        registrar_excepcion(v, P, "XE", "sigue", AHORA)
    assert _foto(v) == antes


def test_log_de_aprobar(tmp_path):
    v = _vault(tmp_path)
    aprobar(v, P, "sí", AHORA)
    assert _lineas_log(v) == [
        (f"- 2026-11-13 18:00 COT · modelar · {P}: oferta aprobada por el usuario · productos/{P}/OFERTA.md"
        " · — tokens"),
        f"- 2026-11-13 18:00 COT · modelar · {P}: actualiza oferta · productos/{P}/PRODUCTO.md · — tokens",
        f"- 2026-11-13 18:00 COT · modelar · {P} XE: aprobado → modelado · productos/{P}/PRODUCTO.md · — tokens",
    ]


def test_log_de_rechazar(tmp_path):
    v = _vault(tmp_path)
    rechazar(v, P, "no", AHORA)
    assert _lineas_log(v) == [
        (f"- 2026-11-13 18:00 COT · modelar · {P}: oferta rechazada por el usuario · productos/{P}/OFERTA.md, "
        f"productos/{P}/decisiones/2026-11-13-oferta-rechazada.md · — tokens"),
        f"- 2026-11-13 18:00 COT · modelar · {P}: actualiza oferta · productos/{P}/PRODUCTO.md · — tokens",
    ]


def test_log_de_registrar_excepcion(tmp_path):
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    cerrar(v, P, AHORA)
    n = len(_lineas_log(v))
    registrar_excepcion(v, P, "XE", "sigue", datetime(2026, 11, 13, 18, 5, tzinfo=COT))
    assert _lineas_log(v)[n:] == [
        (f"- 2026-11-13 18:05 COT · modelar · {P} XE: excepción de R16 (se puede mejorar) con las palabras del "
        f"usuario · productos/{P}/decisiones/2026-11-13-excepcion-r16.md · — tokens"),
        f"- 2026-11-13 18:05 COT · modelar · {P} XE: aprobado → modelado · productos/{P}/PRODUCTO.md · — tokens",
    ]


@pytest.mark.parametrize("cita", ["", "  ", "vale\x85sigue", "vale, mi clave es " + "sk" + "-" + "q" * 24])
def test_cita_invalida_es_su_propio_error(tmp_path, cita):
    """R-T9c: la cita vacía, con C1 o con un secreto es error de entrada (CitaInvalida, un ValueError)."""
    from trovefy.modelar.aprobacion import CitaInvalida

    assert issubclass(CitaInvalida, ValueError)
    v = _vault(tmp_path, senal=False, motivo=MOTIVO_FLOJO)
    antes = _foto(v)
    for llamada in (lambda: aprobar(v, P, cita, AHORA), lambda: rechazar(v, P, cita, AHORA),
                    lambda: registrar_excepcion(v, P, "XE", cita, AHORA)):
        with pytest.raises(CitaInvalida):
            llamada()
    assert _foto(v) == antes


def test_gate_no_es_cita_invalida(tmp_path):
    from trovefy.modelar.aprobacion import CitaInvalida

    v = _vault(tmp_path, aprobacion="rechazada")
    with pytest.raises(ValueError, match="rechazada") as exc:
        registrar_excepcion(v, P, "XE", "sigue", AHORA)
    assert not isinstance(exc.value, CitaInvalida)
