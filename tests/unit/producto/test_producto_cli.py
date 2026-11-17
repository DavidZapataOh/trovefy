"""CLI `trovefy producto` (plan 17, Tarea 13): subcomandos, códigos de salida y la clave nunca a la vista."""

import io
import shutil
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy import cli, producto_cli
from trovefy.apimart.gasto import FilaCoste, anotar_coste, leer_costes
from trovefy.producto.config import iniciar_config
from trovefy.vault import frontmatter

from .apimart_falso import CLAVE, APIMartFalso, escribir_env, publico

P = "p-0042-respira"
RAIZ = Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "fixtures" / "producto" / P
COT = ZoneInfo("America/Bogota")
AHORA = datetime(2026, 11, 16, 10, 0, tzinfo=COT)
MERCADOS = "ZZ: {idioma: es, moneda: EUR, zona: Europe/Madrid, banda_eur: [9, 19], estado: activo}\n"
IMAGENES = [{"id": "portada", "pieza": "principal", "prompt": "portada de un cuaderno de respiración, azul",
             "proporcion": "2:3", "resolucion": "1k"},
            {"id": "mockup", "pieza": "principal", "prompt": "mockup del cuaderno sobre una mesa",
             "proporcion": "3:2", "resolucion": "1k"},
            {"id": "il-01", "pieza": "principal", "prompt": "ilustración de una persona respirando",
             "proporcion": "1:1", "resolucion": "1k"}]


@pytest.fixture
def falso():
    return APIMartFalso()


@pytest.fixture
def vault(tmp_path, monkeypatch, falso):
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    (v / "config" / "mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    (v / ".trovefy").mkdir()
    iniciar_config(v)
    shutil.copytree(FIXTURE, v / "productos" / P)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("TROVEFY_SPOOL", str(tmp_path / "spool"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(producto_cli, "RUTA_ENV", escribir_env(tmp_path / "home" / ".config" / "trovefy"))
    monkeypatch.setattr(producto_cli, "_ahora", lambda: AHORA)
    monkeypatch.setattr(producto_cli, "_dormir", lambda s: None)
    monkeypatch.setattr(producto_cli, "_abrir", falso)
    monkeypatch.setattr(producto_cli, "_abrir_publico", publico)
    return v


def correr(capsys, *args, stdin: str | None = None, monkeypatch=None):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    codigo = cli.main(["producto", *args])
    salida = capsys.readouterr()
    return codigo, salida.out, salida.err


def _estado(v, estado):
    ruta = v / "productos" / P / "PRODUCTO.md"
    meta, cuerpo = frontmatter.leer(ruta)
    meta["paises"]["ZZ"]["estado"] = estado
    frontmatter.escribir(ruta, meta, cuerpo)


def _imagenes(v, lista=IMAGENES):
    ruta = v / "productos" / P / "entregable" / "imagenes.yaml"
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump(lista, allow_unicode=True), encoding="utf-8")


def _log(v) -> str:
    return (v / "log.md").read_text(encoding="utf-8") if (v / "log.md").is_file() else ""


# --- los del plan ------------------------------------------------------------------------------------


def test_cli_ficha_estado_aprobado(vault, capsys):
    _estado(vault, "aprobado")
    codigo, _out, err = correr(capsys, "ficha", P, "--pais", "ZZ", "--exigencia", "sanitario", "--tipo", "ebook")
    assert codigo == 1
    assert "primero /modelar" in err
    assert not (vault / "productos" / P / "entregable" / "FICHA.md").exists()


def test_cli_ficha_crea_y_anota(vault, capsys):
    codigo, out, _ = correr(capsys, "ficha", P, "--pais", "ZZ", "--exigencia", "sanitario", "--tipo", "ebook")
    assert codigo == 0
    assert (vault / "productos" / P / "entregable" / "FICHA.md").is_file()
    for pieza in ("principal", "bono-1", "bono-2", "bump", "u1"):
        assert pieza in out
    assert "ficha del entregable" in _log(vault)


def test_cli_imagenes_sin_precio(vault, capsys, monkeypatch):
    _imagenes(vault)
    monkeypatch.setattr(producto_cli, "_abrir", APIMartFalso(precio=False))
    codigo, out, err = correr(capsys, "imagenes", P)
    assert codigo == 1
    assert "no medido" in out + err
    assert leer_costes(vault, P) == []


def test_cli_imagenes_genera_y_dice_gasto_y_tope(vault, capsys, falso):
    _imagenes(vault)
    codigo, out, _ = correr(capsys, "imagenes", P)
    assert codigo == 0, out
    assert "generadas: portada, mockup, il-01" in out
    assert "gastado 0.0255 USD de un tope de 2.00 USD" in out
    assert "gpt-image-2" in out  # P-11: modelo y precio leídos
    assert [f.estado for f in leer_costes(vault, P)].count("completada") == 3
    assert all(a == "" for r, a in zip(falso.rutas, falso.autorizaciones, strict=True)
               if r.startswith("GET /api/pricing"))


def test_cli_imagenes_simular_no_envia(vault, capsys, falso):
    _imagenes(vault)
    codigo, out, _ = correr(capsys, "imagenes", P, "--simular")
    assert codigo == 0, out
    assert not any(r.startswith("POST") for r in falso.rutas)
    assert {f.estado for f in leer_costes(vault, P)} == {"simulada"}
    assert "simulación" in out


@pytest.mark.parametrize("env", ["no-existe", "sin-clave"])
def test_cli_imagenes_simular_sin_clave(vault, capsys, falso, monkeypatch, tmp_path, env):
    # Ruling de la revisión final: el precio es público; --simular no necesita claude.env.
    _imagenes(vault)
    ruta = tmp_path / "otro" / "claude.env"
    if env == "sin-clave":
        ruta.parent.mkdir()
        ruta.write_text("OTRA=1\n", encoding="utf-8")
        ruta.chmod(0o600)
    monkeypatch.setattr(producto_cli, "RUTA_ENV", ruta)
    codigo, out, err = correr(capsys, "imagenes", P, "--simular")
    assert codigo == 0, out + err
    assert "simulación" in out and "gpt-image-2" in out
    assert {f.estado for f in leer_costes(vault, P)} == {"simulada"}
    assert falso.rutas and all(r.startswith("GET /api/pricing") for r in falso.rutas)
    assert all(a == "" for a in falso.autorizaciones)
    # Sin --simular sigue haciendo falta la clave.
    codigo, _, err = correr(capsys, "imagenes", P)
    assert codigo == 2 and ("APIMART_API_KEY" in err or "no existe" in err)


def test_cli_imagenes_stop(vault, capsys, falso):
    _imagenes(vault)
    (vault / ".trovefy" / "STOP").write_text("", encoding="utf-8")
    codigo, out, err = correr(capsys, "imagenes", P)
    assert codigo == 1
    assert "STOP" in out + err
    assert not any(r.startswith("POST") for r in falso.rutas)


def test_cli_imagenes_descartar(vault, capsys):
    anotar_coste(vault, P, FilaCoste(fecha=AHORA, producto=P, pieza="principal", imagen="portada",
                                     intento="i-1", task_id="", modelo="gpt-image-2", resolucion="1k",
                                     proporcion="2:3", estado="enviando", coste_estimado_usd=None,
                                     coste_real_usd=None, fuente_precio="prueba", sha256="", archivo=""))
    codigo, out, _ = correr(capsys, "imagenes", P, "--descartar", "portada")
    assert codigo == 0, out
    assert leer_costes(vault, P)[-1].estado == "fallida"
    assert "descarta" in _log(vault)


def test_cli_tope_sin_cita(vault, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["producto", "tope", P, "--usd", "3"])
    assert e.value.code == 2
    codigo, _, err = correr(capsys, "tope", P, "--usd", "3", "--cita", "   ")
    assert codigo == 2
    assert "cita" in err


def test_cli_tope_con_cita_literal(vault, capsys):
    cita = "  sí, súbelo a 3 dólares — «solo esta vez»  "
    codigo, out, _ = correr(capsys, "tope", P, "--usd", "3", "--cita", cita)
    assert codigo == 0, out
    decision = next((vault / "productos" / P / "decisiones").glob("*-tope-apimart.md"))
    assert frontmatter.leer(decision)[0]["cita"] == cita
    assert frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")[0]["apimart_tope_usd"] == "3"


def test_cli_tope_importe_mal_escrito(vault, capsys):
    codigo, _, err = correr(capsys, "tope", P, "--usd", "tres", "--cita", "súbelo")
    assert codigo == 2 and "importe" in err


def test_cli_plan_dice_cuanto_falta(vault, capsys):
    correr(capsys, "ficha", P, "--pais", "ZZ", "--exigencia", "sanitario", "--tipo", "ebook")
    ruta = vault / "productos" / P / "entregable" / "PLAN.md"
    ruta.write_text("| sección | palabras | fichas |\n|---|---|---|\n| s-01 | 700 | 0 |\n", encoding="utf-8")
    codigo, out, _ = correr(capsys, "plan", P, "--pieza", "principal")
    assert codigo == 1 and "faltan" in out and "nunca rellenes" in out
    ruta.write_text("| sección | palabras | fichas |\n|---|---|---|\n| s-01 | 7000 | 0 |\n", encoding="utf-8")
    codigo, out, _ = correr(capsys, "plan", P, "--pieza", "principal")
    assert codigo == 0 and "el plan llega" in out


def test_cli_anotar_qc_stdin(vault, capsys, monkeypatch):
    """`VEREDICTO: ok` por stdin → QC.md, con su línea en log.md."""
    raiz = vault / "productos" / P / "entregable"
    _maqueta_falsa(vault, raiz)
    codigo, out, _ = correr(capsys, "anotar-qc", P, "--pieza", "principal", "--version", "1", "--agente", "revisor",
                            stdin="Todo en orden.\n\nVEREDICTO: ok\n", monkeypatch=monkeypatch)
    assert codigo == 0, out
    qc = (raiz / "QC.md").read_text(encoding="utf-8")
    assert "## v1 · revisor ·" in qc and "- veredicto: ok" in qc and "> Todo en orden." in qc
    assert "revisor" in _log(vault)


def test_cli_anotar_qc_sin_veredicto(vault, capsys, monkeypatch):
    raiz = vault / "productos" / P / "entregable"
    _maqueta_falsa(vault, raiz)
    codigo, out, err = correr(capsys, "anotar-qc", P, "--pieza", "principal", "--version", "1", "--agente",
                              "nativo", stdin="Me parece bien.\n", monkeypatch=monkeypatch)
    assert codigo == 1
    assert "no medido" in out + err
    assert "- veredicto: no medido" in (raiz / "QC.md").read_text(encoding="utf-8")


def test_cli_no_imprime_la_clave(vault, capsys, monkeypatch):
    """Ninguna salida de `imagenes`, `estado` ni de los errores trae la clave ni un task_id completo."""
    salidas = []
    _imagenes(vault)
    for args in (("imagenes", P, "--simular"), ("imagenes", P), ("estado", P), ("imagenes", P, "--reanudar"),
                 ("imagenes", "p-0000-noexiste"), ("estado", "../x"), ("tope", P, "--usd", "1", "--cita", "x")):
        _codigo, out, err = correr(capsys, *args)
        salidas.append(out + err)
    (vault / "productos" / P / "entregable" / "imagenes.yaml").write_text(f"- {{id: x, prompt: {CLAVE}}}\n",
                                                                       encoding="utf-8")
    salidas.append("".join(correr(capsys, "imagenes", P)[1:]))
    monkeypatch.setattr(producto_cli, "_abrir", lambda req, timeout=None: (_ for _ in ()).throw(
        OSError(f"fallo con {CLAVE}")))
    salidas.append("".join(correr(capsys, "imagenes", P)[1:]))
    texto = "\n".join(salidas)
    assert "sk-prueba" not in texto and CLAVE not in texto
    assert "task_abcdef000001" not in texto
    assert "claude.env" not in texto or "APIMART_API_KEY=" not in texto


def test_cli_sin_clave_es_error_de_configuracion(vault, capsys, monkeypatch, tmp_path):
    _imagenes(vault)
    monkeypatch.setattr(producto_cli, "RUTA_ENV", tmp_path / "no-existe.env")
    codigo, _, err = correr(capsys, "imagenes", P)
    assert codigo == 2
    assert "APIMART_API_KEY" in err or "no existe" in err


def test_cli_estado(vault, capsys):
    correr(capsys, "ficha", P, "--pais", "ZZ", "--exigencia", "sanitario", "--tipo", "ebook")
    codigo, out, _ = correr(capsys, "estado", P)
    assert codigo == 0
    assert "principal: sin PDF" in out
    assert "APIMart: gastado 0.0000 USD de un tope de 2.00 USD" in out


def test_cli_cerrar_sin_piezas_sale_1(vault, capsys):
    correr(capsys, "ficha", P, "--pais", "ZZ", "--exigencia", "sanitario", "--tipo", "ebook")
    codigo, out, err = correr(capsys, "cerrar", P, "--pais", "ZZ")
    assert codigo == 1
    assert "principal: sin PDF" in out + err


def test_cli_iniciar_ya_existe(vault, capsys):
    codigo, _, err = correr(capsys, "iniciar")
    assert codigo == 2 and "ya existe" in err


def test_cli_ayuda_sin_vista_previa(capsys):
    with pytest.raises(SystemExit):
        cli.main(["producto", "--help"])
    out = capsys.readouterr().out
    for sub in ("iniciar", "ficha", "plan", "imagenes", "tope", "gates", "maquetar", "qc", "anotar-qc", "estado",
                "cerrar"):
        assert sub in out
    assert "vista-previa" not in out  # resolución 16: el dueño es el plan 18


def _maqueta_falsa(vault, raiz):
    """Una v1 con PDF y su maqueta en QC.md, sin WeasyPrint (para probar `anotar-qc`)."""
    from trovefy.pdf.gates import Informe
    from trovefy.pdf.render import Producido
    from trovefy.producto.qc_registro import anotar_producido

    raiz.mkdir(parents=True, exist_ok=True)
    pdf = raiz / "respira-lento-es-v1.pdf"
    pdf.write_bytes(b"%PDF-1.7 prueba")
    r = Producido(1, raiz / "fuente" / "x-v1.html", pdf, Informe((), 100, True, 2000, 6), 6, 6, (), (), True)
    anotar_producido(raiz, r, AHORA)
