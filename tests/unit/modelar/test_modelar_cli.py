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
    antes_meta, antes_cuerpo = frontmatter.leer(c / "ESCALERA.md")
    assert _main("recalcular", "--producto", P) == 0
    meta, cuerpo = frontmatter.leer(c / "ESCALERA.md")
    assert cuerpo == antes_cuerpo
    meta.pop("economia_fecha")
    assert meta == antes_meta


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
