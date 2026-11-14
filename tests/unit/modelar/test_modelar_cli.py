"""CLI `trovefy modelar` (plan 16, Tarea 9, y resolución 10: `recalcular`)."""

import pathlib
import shutil
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy import cli, fx, modelar_cli
from trovefy.economia.config import PLANTILLA
from trovefy.vault import frontmatter
from trovefy.vault.producto import estado_pais

P = "p-0042-kit-demo"
HOY = date(2026, 11, 13)
AHORA = datetime(2026, 11, 13, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
CAMBIO = fx.Cambio({"USD": 1.08, "RON": 4.977}, "2026-11-12")
RAIZ = pathlib.Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "fixtures/modelar/modelar-demo.yaml"
MERCADOS = """\
XE: {idioma: bg, moneda: EUR, zona: Zona demo, banda_eur: [11.90, 15.90], estado: activo}
XR: {idioma: ro, moneda: RON, zona: Zona demo, banda_eur: [11.90, 15.90], estado: activo}
"""


def _economia(v, comisiones=True):
    datos = yaml.safe_load(PLANTILLA.read_text(encoding="utf-8"))
    if comisiones:
        datos["ruta_activa"]["valor"] = "impultienda_whop"
        for campo in ("comision_pct", "comision_fija_usd", "impuestos_pct"):
            datos["plataformas"]["impultienda"][campo]["valor"] = 0
            datos["plataformas"]["whop"][campo]["valor"] = 0
        datos["plataformas"]["whop"]["comision_pct"]["valor"] = 0.10
    (v / "config/economia.yaml").write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    (v / "config/mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    frontmatter.escribir(v / "wiki/ofertas/o-demo.md",
                         {"tipo": "oferta", "id": "o-demo", "dominio": "oferta-demo.test", "precio": 9.0,
                          "moneda": None}, "# Oferta demo\n")
    carpeta = v / "productos" / P
    frontmatter.escribir(carpeta / "PRODUCTO.md",
                         {"tipo": "producto", "oferta_id": "o-demo",
                          "paises": {"XE": {"estado": "aprobado"}, "XR": {"estado": "auditado"}}},
                         f"# Producto {P}\n")
    frontmatter.escribir(carpeta / "decisiones/2026-11-12-eleccion.md",
                         {"tipo": "decision", "pais": "XE", "reserva": "XR"}, "Elección.\n")
    frontmatter.escribir(carpeta / "AUDITORIA.md", {"tipo": "auditoria", "producto": P}, "# Auditoría\n")
    _economia(v)
    shutil.copy(FIXTURE, carpeta / "modelar.yaml")
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(fx, "cambio_del_dia", lambda vault, hoy, *a, **k: CAMBIO)
    monkeypatch.setattr(modelar_cli, "_ahora", lambda: AHORA)
    return v


def _carpeta(v):
    return v / "productos" / P


def _main(*args):
    return cli.main(["modelar", *args])


# --- preparar ---------------------------------------------------------------------------------------


def test_preparar_lista_lo_que_falta(vault, capsys):
    _economia(vault, comisiones=False)
    assert _main("preparar", "--producto", P) == 0
    out = capsys.readouterr().out
    assert "falta referencia/anuncios.md: ejecuta antes /ver-anuncios (plan 15)" in out
    assert "no medido: falta ruta_activa" in out
    assert "el teardown lo haces tú en este paso" in out
    assert "idioma bg" in out and "moneda EUR" in out and "11,90–15,90 €" in out
    assert "9,00, moneda no medida" in out
    assert "https://oferta-demo.test/" in out
    assert "skills/modelar/references/modelar-ejemplo.yaml" in out
    assert not (_carpeta(vault) / "OFERTA.md").exists()

    for f in (_carpeta(vault) / "decisiones").iterdir():
        f.unlink()
    assert _main("preparar", "--producto", P) == 1
    assert "elección" in capsys.readouterr().out


def test_preparar_sin_economia_ni_auditoria_bloquea(vault, capsys):
    (vault / "config/economia.yaml").unlink()
    (_carpeta(vault) / "AUDITORIA.md").unlink()
    assert _main("preparar", "--producto", P) == 1
    out = capsys.readouterr().out
    assert "trovefy economia iniciar" in out and "AUDITORIA.md" in out


def test_preparar_con_teardown_y_anuncios(vault, capsys):
    frontmatter.escribir(_carpeta(vault) / "AUDITORIA.md", {"tipo": "auditoria", "teardown": {"url": "x"}}, "")
    frontmatter.escribir(_carpeta(vault) / "referencia/anuncios.md", {"fecha": "2026-11-12", "pais": "XE"}, "")
    assert _main("preparar", "--producto", P) == 0
    out = capsys.readouterr().out
    assert "falta referencia/anuncios.md" not in out and "teardown lo haces tú" not in out
    assert "Aviso:" not in out  # comisiones de demo rellenas: nada que avisar
    assert "teardown: lo trae AUDITORIA.md" in out


def test_preparar_estado_no_valido(vault, capsys):
    frontmatter.escribir(_carpeta(vault) / "PRODUCTO.md",
                         {"tipo": "producto", "oferta_id": "o-demo", "paises": {"XE": {"estado": "producido"}}}, "")
    assert _main("preparar", "--producto", P) == 1
    assert "producido" in capsys.readouterr().out


def test_producto_invalido(vault, capsys):
    assert _main("preparar", "--producto", "../x") == 2
    assert capsys.readouterr().err.startswith("Error: ")


# --- escribir ---------------------------------------------------------------------------------------


def test_escribir_ok(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    out = capsys.readouterr().out
    for nombre in ("OFERTA", "ESCALERA", "BRANDBOOK", "comparativa"):
        assert (_carpeta(vault) / f"{nombre}.md").is_file()
        assert f"productos/{P}/{nombre}.md" in out
    assert "13,90 EUR" in out
    assert "BE 14,58 USD" in out
    assert "se puede mejorar: sí" in out
    assert "Si no la rechazas en esta sesión, queda aprobada." in out
    assert estado_pais(vault, P, "XE") == "aprobado"


def test_escribir_yaml_invalido(vault, capsys):
    (_carpeta(vault) / "modelar.yaml").write_text("producto: p-0042-kit-demo\npais: XE\n", encoding="utf-8")
    assert _main("escribir", "--producto", P) == 2
    err = capsys.readouterr().err
    lineas = [x for x in err.splitlines() if x.startswith("- ")]
    assert len(lineas) >= 2
    assert not (_carpeta(vault) / "OFERTA.md").exists()


def test_escribir_sin_modelar_yaml(vault, capsys):
    (_carpeta(vault) / "modelar.yaml").unlink()
    assert _main("escribir", "--producto", P) == 2
    assert "modelar.yaml" in capsys.readouterr().err


def test_precio_front_manual(vault, capsys):
    assert _main("escribir", "--producto", P, "--precio-front", "XR:65") == 0
    escalera = frontmatter.leer(_carpeta(vault) / "ESCALERA.md")[0]
    assert escalera["paises"]["XR"]["fuente_precio"] == "usuario"
    assert escalera["paises"]["XR"]["pasos"]["front"]["precio"] == "65"
    assert escalera["paises"]["XE"]["fuente_precio"] == "banda del país"


@pytest.mark.parametrize("valor", ["XR:abc", "XR", "XRR:65", "XR:-3", "XR:0", "XR:nan"])
def test_precio_front_mal_formado(vault, capsys, valor):
    assert _main("escribir", "--producto", P, "--precio-front", valor) == 2
    assert capsys.readouterr().err.startswith("Error: ")
    assert not (_carpeta(vault) / "OFERTA.md").exists()


def test_sin_cambio_del_bce(vault, capsys, monkeypatch):
    monkeypatch.setattr(fx, "cambio_del_dia", lambda vault, hoy, *a, **k: None)
    assert _main("escribir", "--producto", P) == 0
    out = capsys.readouterr().out
    assert "13,90 EUR" in out
    assert "no medido: sin cambio de referencia para USD" in out
    escalera = frontmatter.leer(_carpeta(vault) / "ESCALERA.md")[0]
    assert escalera["paises"]["XE"]["pasos"]["front"]["precio"] == "13.90"
    assert escalera["paises"]["XE"]["be_usd"] is None


def test_escribir_estado_producido(vault, capsys):
    frontmatter.escribir(_carpeta(vault) / "PRODUCTO.md",
                         {"tipo": "producto", "oferta_id": "o-demo",
                          "paises": {"XE": {"estado": "producido"}, "XR": {"estado": "auditado"}}}, "")
    assert _main("escribir", "--producto", P) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and "producido" in err and "Traceback" not in err


# --- aprobación ---------------------------------------------------------------------------------------


def test_cerrar_cli(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    capsys.readouterr()
    assert _main("cerrar", "--producto", P) == 0
    assert f"Oferta de {P}: aprobada tácitamente; XE pasa a modelado" in capsys.readouterr().out
    assert estado_pais(vault, P, "XE") == "modelado"
    assert _main("cerrar", "--producto", P) == 0  # idempotente
    assert "XE ya está en modelado" in capsys.readouterr().out


def test_aprobar_cli_cita_literal(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    cita = "¡Vale! sí, sigue — 'así'"
    assert _main("aprobar", "--producto", P, "--cita", cita) == 0
    assert "aprobada" in capsys.readouterr().out
    assert frontmatter.leer(_carpeta(vault) / "OFERTA.md")[0]["aprobacion_cita"] == cita


def test_rechazar_cli(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    cita = "no me convence el precio"
    assert _main("rechazar", "--producto", P, "--cita", cita) == 0
    out = capsys.readouterr().out
    assert "decisiones/" in out
    decisiones = list((_carpeta(vault) / "decisiones").glob("*-oferta-rechazada.md"))
    assert len(decisiones) == 1 and cita in decisiones[0].read_text(encoding="utf-8")
    assert _main("rechazar", "--producto", P, "--cita", "otra") == 2  # ya rechazada
    capsys.readouterr()
    assert _main("cerrar", "--producto", P) == 1  # rechazada: bloquea
    assert "rechazada" in capsys.readouterr().out
    assert _main("aprobar", "--producto", P, "--cita", "sí") == 1
    assert _main("excepcion", "--producto", P, "--pais", "XE", "--cita", "sigue") == 1
    assert "rechazada" in capsys.readouterr().err
    assert not list((_carpeta(vault) / "decisiones").glob("*-excepcion-r16.md"))
    assert estado_pais(vault, P, "XE") == "aprobado"


def test_excepcion_innecesaria_no_pasa(vault, capsys):
    assert _main("escribir", "--producto", P) == 0  # se_puede_mejorar: true → no hace falta excepción
    assert _main("excepcion", "--producto", P, "--pais", "XE", "--cita", "sigue") == 1
    assert capsys.readouterr().err.startswith("Error: ")


def test_aprobar_sin_cita(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    assert _main("aprobar", "--producto", P, "--cita", "  ") == 2


def test_excepcion_cli_cita_literal(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    ruta = _carpeta(vault) / "OFERTA.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta["se_puede_mejorar"], meta["se_puede_mejorar_motivo"] = False, "no: +2,0 puntos sobre el original"
    frontmatter.escribir(ruta, meta, cuerpo)
    capsys.readouterr()
    cita = "Sigue igual, asumo el riesgo: 'lo pruebo'"
    assert _main("excepcion", "--producto", P, "--pais", "XE", "--cita", cita) == 0
    out = capsys.readouterr().out
    decisiones = list((_carpeta(vault) / "decisiones").glob("*-excepcion-r16.md"))
    assert len(decisiones) == 1
    assert frontmatter.leer(decisiones[0])[0]["cita"] == cita
    assert "decisiones/" in out
    assert f"Oferta de {P}: aprobada tácitamente; XE pasa a modelado" in out
    assert estado_pais(vault, P, "XE") == "modelado"


# --- ver y recalcular ----------------------------------------------------------------------------------


def test_ver(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    capsys.readouterr()
    assert _main("ver", "--producto", P) == 0
    out = capsys.readouterr().out
    assert "presentada" in out and "aprobado" in out and "13,90 EUR" in out


def test_ver_sin_oferta(vault, capsys):
    assert _main("ver", "--producto", P) == 2
    assert "falta OFERTA.md" in capsys.readouterr().err


def _fijar_comision(vault, valor):
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", valor,
                     "--fuente", "https://precios.whop.test/"]) == 0


def test_recalcular_solo_economia(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    assert _main("cerrar", "--producto", P) == 0
    c = _carpeta(vault)
    oferta_antes = (c / "OFERTA.md").read_text(encoding="utf-8")
    producto_antes = (c / "PRODUCTO.md").read_text(encoding="utf-8")
    antes = frontmatter.leer(c / "ESCALERA.md")[0]
    _fijar_comision(vault, "0.20")
    capsys.readouterr()

    assert _main("recalcular", "--producto", P) == 0
    out = capsys.readouterr().out
    despues = frontmatter.leer(c / "ESCALERA.md")[0]
    for pais in ("XE", "XR"):
        assert despues["paises"][pais]["pasos"] == antes["paises"][pais]["pasos"]
        assert despues["paises"][pais]["fuente_precio"] == antes["paises"][pais]["fuente_precio"]
    assert despues["paises"]["XE"]["be_usd"] != antes["paises"]["XE"]["be_usd"]
    assert despues["fecha"] == antes["fecha"]
    assert despues["economia_fecha"] == HOY.isoformat()
    assert (c / "versiones" / f"ESCALERA-{HOY.isoformat()}.md").is_file()
    assert (c / "OFERTA.md").read_text(encoding="utf-8") == oferta_antes
    assert (c / "PRODUCTO.md").read_text(encoding="utf-8") == producto_antes
    assert estado_pais(vault, P, "XE") == "modelado"
    assert f"productos/{P}/ESCALERA.md" in out and "BE" in out


def test_recalcular_sin_cambios_conserva_todo(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    assert _main("cerrar", "--producto", P) == 0
    c = _carpeta(vault)
    antes = (c / "ESCALERA.md").read_bytes()
    assert _main("recalcular", "--producto", P) == 0  # misma config: la reconstrucción da el mismo texto
    assert (c / "ESCALERA.md").read_bytes() == antes


def test_recalcular_en_aprobado_se_niega(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    antes = (_carpeta(vault) / "ESCALERA.md").read_text(encoding="utf-8")
    capsys.readouterr()
    assert _main("recalcular", "--producto", P) == 2
    assert "aprobado" in capsys.readouterr().err
    assert (_carpeta(vault) / "ESCALERA.md").read_text(encoding="utf-8") == antes


def test_recalcular_sin_cambio_del_bce_no_escribe(vault, capsys, monkeypatch):
    assert _main("escribir", "--producto", P) == 0
    assert _main("cerrar", "--producto", P) == 0
    antes = (_carpeta(vault) / "ESCALERA.md").read_text(encoding="utf-8")
    monkeypatch.setattr(fx, "cambio_del_dia", lambda vault, hoy, *a, **k: None)
    assert _main("recalcular", "--producto", P) == 1
    assert (_carpeta(vault) / "ESCALERA.md").read_text(encoding="utf-8") == antes


def test_recalcular_sin_escalera(vault, capsys):
    frontmatter.escribir(_carpeta(vault) / "PRODUCTO.md",
                         {"tipo": "producto", "oferta_id": "o-demo",
                          "paises": {"XE": {"estado": "modelado"}, "XR": {"estado": "auditado"}}}, "")
    assert _main("recalcular", "--producto", P) == 2
    assert "falta ESCALERA.md" in capsys.readouterr().err


def test_subcomandos_registrados(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--help"])
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert "modelar" in out and "economia" in out


# --- ronda de revisión de la Tarea 9 ----------------------------------------------------------------

SECRETO = "sk" + "-" + "q" * 24


def _foto(v):
    """Todo el producto y el log, para comprobar que no se escribe nada."""
    carpeta = _carpeta(v)
    archivos = {r.relative_to(carpeta).as_posix(): r.read_bytes() for r in carpeta.rglob("*") if r.is_file()}
    log = v / "log.md"
    return archivos, log.read_bytes() if log.is_file() else b""


def _sin_tercera_senal(vault):
    ruta = _carpeta(vault) / "OFERTA.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta["se_puede_mejorar"], meta["se_puede_mejorar_motivo"] = False, "no: +2,0 puntos sobre el original"
    frontmatter.escribir(ruta, meta, cuerpo)


@pytest.mark.parametrize("accion", ["excepcion", "aprobar", "rechazar"])
@pytest.mark.parametrize("cita", ["", "   ", "vale\x85sigue", f"sigue, mi clave es {SECRETO}"])
def test_cita_invalida_sale_2_sin_escribir(vault, capsys, accion, cita):
    """R-T9c: la cita vacía, con un carácter C1 o con un secreto es error de entrada → 2, nada escrito."""
    assert _main("escribir", "--producto", P) == 0
    _sin_tercera_senal(vault)
    antes = _foto(vault)
    capsys.readouterr()
    extra = ["--pais", "XE"] if accion == "excepcion" else []
    assert _main(accion, "--producto", P, *extra, "--cita", cita) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and SECRETO not in err
    assert _foto(vault) == antes


def test_excepcion_oferta_rechazada_sale_1(vault, capsys):
    assert _main("escribir", "--producto", P) == 0
    assert _main("rechazar", "--producto", P, "--cita", "no") == 0
    capsys.readouterr()
    assert _main("excepcion", "--producto", P, "--pais", "XE", "--cita", "sigue") == 1
    assert "rechazada" in capsys.readouterr().err


def test_excepcion_escrita_y_avance_fallido_lo_dice(vault, capsys, monkeypatch):
    """L-6: si la decisión ya se escribió y el avance falla, el mensaje lo dice (nunca «nada escrito»)."""
    from trovefy.modelar import aprobacion

    assert _main("escribir", "--producto", P) == 0
    _sin_tercera_senal(vault)
    capsys.readouterr()

    def _falla(*a, **k):
        raise ValueError("PRODUCTO.md: estado inesperado de prueba")

    monkeypatch.setattr(aprobacion, "_avanzar", _falla)
    assert _main("excepcion", "--producto", P, "--pais", "XE", "--cita", "sigue igual") == 1
    salida = capsys.readouterr()
    texto = salida.out + salida.err
    assert len(list((_carpeta(vault) / "decisiones").glob("*-excepcion-r16.md"))) == 1
    assert "registrada" in texto and "decisiones/" in texto
    assert "estado inesperado de prueba" in texto
    assert "nada escrito" not in texto.lower()
    assert estado_pais(vault, P, "XE") == "aprobado"


def _a_modelado(vault):
    assert _main("escribir", "--producto", P) == 0
    assert _main("cerrar", "--producto", P) == 0


def _poner_estado(vault, estado):
    ruta = _carpeta(vault) / "PRODUCTO.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta["paises"]["XE"]["estado"] = estado
    frontmatter.escribir(ruta, meta, cuerpo)


@pytest.mark.parametrize("estado", ["producido", "con_landing", "listo"])
def test_recalcular_en_estados_avanzados(vault, capsys, estado):
    _a_modelado(vault)
    _poner_estado(vault, estado)
    c = _carpeta(vault)
    oferta = (c / "OFERTA.md").read_bytes()
    producto = (c / "PRODUCTO.md").read_bytes()
    _fijar_comision(vault, "0.20")
    capsys.readouterr()
    assert _main("recalcular", "--producto", P) == 0
    assert (c / "OFERTA.md").read_bytes() == oferta
    assert (c / "PRODUCTO.md").read_bytes() == producto
    assert estado_pais(vault, P, "XE") == estado
    assert frontmatter.leer(c / "ESCALERA.md")[0]["economia_fecha"] == HOY.isoformat()


def test_recalcular_be_pasa_de_no_medido_a_medido(vault, capsys, monkeypatch):
    monkeypatch.setattr(fx, "cambio_del_dia", lambda vault, hoy, *a, **k: None)
    _a_modelado(vault)
    c = _carpeta(vault)
    assert frontmatter.leer(c / "ESCALERA.md")[0]["paises"]["XE"]["be_usd"] is None
    monkeypatch.setattr(fx, "cambio_del_dia", lambda vault, hoy, *a, **k: CAMBIO)
    capsys.readouterr()
    assert _main("recalcular", "--producto", P) == 0
    xe = frontmatter.leer(c / "ESCALERA.md")[0]["paises"]["XE"]
    assert xe["be_usd"] is not None
    assert "BE 14,58 USD" in capsys.readouterr().out


def test_recalcular_aviso_be_bajo_aparece_y_se_va(vault, capsys):
    from trovefy.economia.calculo import AVISO_BE_BAJO

    _a_modelado(vault)
    c = _carpeta(vault)

    def avisos():
        return frontmatter.leer(c / "ESCALERA.md")[0]["paises"]["XE"].get("avisos") or []

    assert AVISO_BE_BAJO not in avisos()
    _fijar_comision(vault, "0.50")
    assert _main("recalcular", "--producto", P) == 0
    assert avisos().count(AVISO_BE_BAJO) == 1
    assert _main("recalcular", "--producto", P) == 0  # sin cambios: sigue una sola vez
    assert avisos().count(AVISO_BE_BAJO) == 1
    _fijar_comision(vault, "0.10")
    assert _main("recalcular", "--producto", P) == 0
    assert AVISO_BE_BAJO not in avisos()


def test_recalcular_sin_cambios_no_escribe(vault, capsys):
    """L-3: con la misma economía, «sin cambios», salida 0, sin versión ni línea de log."""
    _a_modelado(vault)
    antes = _foto(vault)
    capsys.readouterr()
    assert _main("recalcular", "--producto", P) == 0
    assert "sin cambios" in capsys.readouterr().out
    assert _foto(vault) == antes
    assert not (_carpeta(vault) / "versiones").exists() or not list(
        (_carpeta(vault) / "versiones").glob("ESCALERA-*.md"))


def test_recalcular_avisa_si_cambiarian_los_activos(vault, capsys):
    """L-4: con otra config de upsells, avisa y no toca `activo`."""
    _a_modelado(vault)
    c = _carpeta(vault)
    pasos = {p: b["pasos"] for p, b in frontmatter.leer(c / "ESCALERA.md")[0]["paises"].items()}
    assert cli.main(["economia", "fijar", "--clave", "plataformas.impultienda.upsells_por_plan", "--valor", "3",
                     "--fuente", "https://planes.impultienda.test/"]) == 0
    capsys.readouterr()
    assert _main("recalcular", "--producto", P) == 0
    out = capsys.readouterr().out
    assert ("con la config actual cambiaría qué pasos van activos: rehaz /modelar si el país sigue en "
            "modelado") in out
    despues = {p: b["pasos"] for p, b in frontmatter.leer(c / "ESCALERA.md")[0]["paises"].items()}
    assert despues == pasos


def test_recalcular_sin_aviso_de_activos_con_la_misma_config(vault, capsys):
    _a_modelado(vault)
    _fijar_comision(vault, "0.20")
    capsys.readouterr()
    assert _main("recalcular", "--producto", P) == 0
    assert "cambiaría qué pasos van activos" not in capsys.readouterr().out


@pytest.mark.parametrize("valor", ["XR:6_5", "XR:1e3", "XR:65,", "XR:,5", "XR:1.2.3"])
def test_precio_front_solo_digitos(vault, capsys, valor):
    assert _main("escribir", "--producto", P, "--precio-front", valor) == 2
    assert capsys.readouterr().err.startswith("Error: ")
    assert not (_carpeta(vault) / "OFERTA.md").exists()


def test_precio_front_con_coma(vault, capsys):
    assert modelar_cli.precios_front(["XR:65,50", "xe:14"]) == {"XR": modelar_cli.Decimal("65.50"),
                                                                 "XE": modelar_cli.Decimal("14")}


@pytest.mark.parametrize("dominio", ["https://oferta-demo.test", "http://oferta-demo.test/", "oferta-demo.test"])
def test_landing_original_sin_doble_esquema(dominio):
    landing = modelar_cli._landing_original({"dominio": dominio})
    assert landing.count("://") == 1 and landing.endswith("oferta-demo.test/")
