"""Tarea 7 del plan 18: texto visible para el agente `nativo` y su veredicto ligado a la versión.

Resolución 17: el veredicto es ``ok|corregir`` y se lee de la respuesta del agente con
``trovefy.producto.qc_registro.parsear_veredicto`` (líneas ``- `` bloquean; ``~ `` son sugerencias).
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from trovefy import cli, landing_cli
from trovefy.landing.entrada import EntradaInvalida, ruta_landing
from trovefy.landing.nativo import (
    registrar_veredicto,
    texto_landing,
    texto_visible,
    veredicto_vigente,
)
from trovefy.landing.plantilla import guardar, version_de
from trovefy.landing.qa import Clic, evaluar
from trovefy.landing.validar import Resultado
from trovefy.vault import frontmatter

from .conftest import Ejecutar, P, cargar
from .test_validar import BUENA, montar

AHORA = datetime(2026, 11, 17, 11, 0, tzinfo=ZoneInfo("America/Bogota"))
OK = "Revisado el texto entero.\n~ «Това е напълно наред» → «Няма нищо лошо в това»\nVEREDICTO: ok\n"
CORREGIR = "- Sección 3: «д» suelta al final de la línea.\nVEREDICTO: corregir\n"
SECRETO = "EAAB" + "x7Kq2" * 8


@pytest.fixture
def v(tmp_path, monkeypatch):
    v = montar(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    return v


def _html(v) -> str:
    return (ruta_landing(v, P, "ZZ") / "index.html").read_text(encoding="utf-8")


def test_texto_visible_sin_scripts(v):
    html = _html(v).replace("</main>", "<script>var x = 'codigo-secreto-de-utm';</script>"
                            "<style>.a{color:red}</style></main>")
    t = texto_visible(html)
    utm = (ruta_landing(v, P, "ZZ") / "assets" / "utm.js").read_text(encoding="utf-8")
    assert "codigo-secreto-de-utm" not in t and "color:red" not in t
    assert not any(linea.strip() and linea.strip() in t for linea in utm.splitlines() if len(linea.strip()) > 12)
    cabeceras = [x for x in t.splitlines() if x.startswith("## Sección ")]
    assert len(cabeceras) == 15
    assert cabeceras[0] == "## Sección 1 (hero)" and cabeceras[6] == "## Sección 7 (vista_previa)"
    assert "Първа страница на наръчника" in t  # alt de la vista previa
    assert t.startswith("# Somatix · Спокойно тяло за 14 дни")
    assert "Кратки вечерни упражнения за отпускане" in t  # meta description
    assert "Спокойно тяло за 14 дни" in t.split("## Sección 1 (hero)")[1]


def test_texto_visible_separa_bloques():
    t = texto_visible('<html><body><section data-tf-seccion="1" data-tf-tipo="hero"><h1>Уно</h1><p>Две '
                      'думи</p><img alt="снимка"></section></body></html>')
    assert t.splitlines()[-5:] == ["## Sección 1 (hero)", "", "Уно", "Две думи", "[imagen: снимка]"]


def test_registrar_y_leer_veredicto(v):
    ruta = registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    assert ruta == ruta_landing(v, P, "ZZ") / "nativo.md"
    assert veredicto_vigente(v, P, "ZZ") == ("ok", version_de(_html(v)))
    meta, cuerpo = frontmatter.leer(ruta)
    assert meta == {"tipo": "qa_idioma", "agente": "nativo", "veredicto": "ok", "version": version_de(_html(v)),
                    "texto_sha256": texto_landing(v, P, "ZZ").sha256, "fecha": "2026-11-17T11:00:00-05:00"}
    assert cuerpo == OK
    assert "nativo" in (v / "log.md").read_text(encoding="utf-8")


def test_registrar_corregir(v):
    registrar_veredicto(v, P, "ZZ", "corregir", CORREGIR, AHORA)
    assert veredicto_vigente(v, P, "ZZ")[0] == "corregir"


def test_sin_veredicto_es_none(v):
    assert veredicto_vigente(v, P, "ZZ") is None


def test_veredicto_que_no_cuadra_con_las_notas(v):
    with pytest.raises(EntradaInvalida, match="VEREDICTO"):
        registrar_veredicto(v, P, "ZZ", "ok", CORREGIR, AHORA)
    with pytest.raises(EntradaInvalida, match="VEREDICTO"):
        registrar_veredicto(v, P, "ZZ", "ok", "Todo bien, sin línea final.\n", AHORA)
    with pytest.raises(EntradaInvalida, match="VEREDICTO"):  # ok con un error que bloquea: se contradice
        registrar_veredicto(v, P, "ZZ", "ok", "- falta una tilde\nVEREDICTO: ok\n", AHORA)
    assert veredicto_vigente(v, P, "ZZ") is None


def test_nativo_md_manipulado_no_vale(v):
    ruta = registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    meta, _ = frontmatter.leer(ruta)
    frontmatter.escribir(ruta, meta, CORREGIR)  # el frontmatter dice ok y la respuesta dice corregir
    assert veredicto_vigente(v, P, "ZZ") is None
    frontmatter.escribir(ruta, {**meta, "veredicto": "aprobado"}, OK)
    assert veredicto_vigente(v, P, "ZZ") is None


def test_veredicto_queda_viejo_tras_editar(v, tmp_path):
    registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    vieja = version_de(_html(v))
    borrador = tmp_path / "borrador"
    (borrador / "index.html").write_text(BUENA.read_text(encoding="utf-8").replace("Искам наръчника",
                                                                                    "Вземи наръчника"),
                                         encoding="utf-8")
    nueva = guardar(v, cargar(v), borrador)
    assert nueva != vieja
    assert veredicto_vigente(v, P, "ZZ") is None  # el texto que leyó el nativo ya no es el de la landing
    r = evaluar(Resultado(True, (), ()), [], Clic(None, "x"), [], veredicto_vigente(v, P, "ZZ"), nueva, False)
    fila = next(f for f in r.filas if f[0].startswith("Idioma"))
    assert fila[1] == "NO MEDIDO"


def test_veredicto_de_otra_version_con_el_mismo_texto(v, tmp_path):
    """Un cambio que no toca el texto (una clase) cambia la versión: el veredicto queda de la versión vieja."""
    registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    vieja = version_de(_html(v))
    borrador = tmp_path / "borrador"
    (borrador / "index.html").write_text(BUENA.read_text(encoding="utf-8").replace("<body>", '<body class="x">', 1),
                                         encoding="utf-8")
    nueva = guardar(v, cargar(v), borrador)
    assert nueva != vieja
    assert veredicto_vigente(v, P, "ZZ") == ("ok", vieja)
    r = evaluar(Resultado(True, (), ()), [], Clic(None, "x"), [], veredicto_vigente(v, P, "ZZ"), nueva, False)
    fila = next(f for f in r.filas if f[0].startswith("Idioma"))
    assert fila[1] == "NO MEDIDO" and vieja in fila[2]


def test_veredicto_caduca_si_cambia_el_content_del_css(v):
    """I4: el CSS no entra en la versión, pero su ``content:`` sí es texto que lee el comprador."""
    registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    css = ruta_landing(v, P, "ZZ") / "assets" / "estilo.css"
    css.write_text(css.read_text(encoding="utf-8") + '\n.precio::after{content:"само днес"}\n', encoding="utf-8")
    assert veredicto_vigente(v, P, "ZZ") is None


def test_veredicto_con_nativo_md_sin_hash_no_vale(v):
    ruta = registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    meta, cuerpo = frontmatter.leer(ruta)
    frontmatter.escribir(ruta, {k: x for k, x in meta.items() if k != "texto_sha256"}, cuerpo)
    assert veredicto_vigente(v, P, "ZZ") is None


def test_registrar_exige_la_version_y_el_texto_actuales(v):
    actual = texto_landing(v, P, "ZZ")
    with pytest.raises(EntradaInvalida, match="versión"):
        registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA, version="000000000000")
    with pytest.raises(EntradaInvalida, match="sha256"):
        registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA, version=actual.version, texto_sha256="0" * 64)
    registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA, version=actual.version, texto_sha256=actual.sha256)
    assert veredicto_vigente(v, P, "ZZ") == ("ok", actual.version)


def test_index_editado_a_mano_no_da_texto(v):
    ruta = ruta_landing(v, P, "ZZ") / "index.html"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace("Искам наръчника", "Вземи го"), encoding="utf-8")
    with pytest.raises(EntradaInvalida, match="guardar"):
        texto_landing(v, P, "ZZ")
    with pytest.raises(EntradaInvalida, match="guardar"):
        registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)


def test_texto_visible_sin_secciones_es_error():
    with pytest.raises(EntradaInvalida, match="secci"):
        texto_visible("<html><body><main><p>Само текст</p></main></body></html>")


def test_texto_visible_con_otro_numero_de_secciones_es_error(v):
    with pytest.raises(EntradaInvalida, match="wireframe"):
        texto_visible(_html(v), esperadas=16)
    assert texto_visible(_html(v), esperadas=15).count("## Sección ") == 15


def test_texto_visible_anade_el_content_del_css():
    html = ('<html><head><style>.a::before{content:"Само днес"}</style></head><body>'
            '<section data-tf-seccion="1" data-tf-tipo="hero"><p>Уно</p></section></body></html>')
    t = texto_visible(html, css='.b::after{content:"\\2014  внимание"} .c{content:attr(title)}')
    assert "Само днес" in t and "— внимание" in t
    assert t.index("Само днес") > t.index("Уно")


def test_veredicto_invalido(v, tmp_path):
    notas = tmp_path / "notas.txt"
    notas.write_text(OK, encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["landing", "nativo", "--producto", P, "--pais", "ZZ", "--veredicto", "aprobado",
                  "--notas-archivo", str(notas), "--version", version_de(_html(v))])
    assert e.value.code == 2
    with pytest.raises(ValueError):
        registrar_veredicto(v, P, "ZZ", "aprobado", OK, AHORA)  # type: ignore[arg-type]


def test_notas_con_secreto_rechazadas(v, tmp_path):
    with pytest.raises(EntradaInvalida, match="secreto"):
        registrar_veredicto(v, P, "ZZ", "ok", f"token {SECRETO}\nVEREDICTO: ok\n", AHORA)
    assert not (ruta_landing(v, P, "ZZ") / "nativo.md").exists()
    notas = tmp_path / "notas.txt"
    notas.write_text(f"token {SECRETO}\nVEREDICTO: ok\n", encoding="utf-8")
    assert cli.main(["landing", "nativo", "--producto", P, "--pais", "ZZ", "--veredicto", "ok",
                     "--notas-archivo", str(notas), "--version", version_de(_html(v))]) == 2


def test_sin_landing_guardada_es_error(tmp_path):
    from .conftest import vault_demo

    v = vault_demo(tmp_path)
    with pytest.raises(EntradaInvalida, match="guardar"):
        registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)


def test_cli_texto_y_nativo(v, tmp_path, capsys):
    assert cli.main(["landing", "texto", "--producto", P, "--pais", "ZZ"]) == 0
    out = capsys.readouterr().out
    actual = texto_landing(v, P, "ZZ")
    assert out.splitlines()[:2] == [f"Versión: {actual.version}", f"Texto-sha256: {actual.sha256}"]
    assert out.count("## Sección ") == 15 and "Спокойно тяло" in out
    notas = tmp_path / "notas.txt"
    notas.write_text(OK, encoding="utf-8")
    args = ["landing", "nativo", "--producto", P, "--pais", "ZZ", "--notas-archivo", str(notas),
            "--version", actual.version]
    assert cli.main([*args, "--veredicto", "corregir"]) == 2  # no cuadra con la respuesta del agente
    assert cli.main([*args, "--veredicto", "ok"]) == 0
    assert veredicto_vigente(v, P, "ZZ") == ("ok", version_de(_html(v)))
    assert cli.main(args) == 0  # sin --veredicto, el de la respuesta
    assert cli.main([*args, "--texto-sha256", actual.sha256]) == 0
    assert cli.main([*args, "--texto-sha256", "0" * 64]) == 2
    assert cli.main([*args[:-1], "000000000000"]) == 2  # el texto que leyó el nativo era de otra versión
    no_existe = [*args]
    no_existe[no_existe.index(str(notas))] = str(tmp_path / "no-existe.txt")
    assert cli.main(no_existe) == 2


def test_cli_nativo_exige_version(v, tmp_path):
    notas = tmp_path / "notas.txt"
    notas.write_text(OK, encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["landing", "nativo", "--producto", P, "--pais", "ZZ", "--notas-archivo", str(notas)])
    assert e.value.code == 2


def test_cli_nativo_guarda_la_respuesta_tal_cual_con_crlf(v, tmp_path):
    notas = tmp_path / "notas.txt"
    notas.write_bytes(OK.replace("\n", "\r\n").encode("utf-8"))
    version = texto_landing(v, P, "ZZ").version
    assert cli.main(["landing", "nativo", "--producto", P, "--pais", "ZZ", "--notas-archivo", str(notas),
                     "--version", version]) == 0
    guardado = (ruta_landing(v, P, "ZZ") / "nativo.md").read_bytes()
    assert guardado.endswith(OK.replace("\n", "\r\n").encode("utf-8"))
    assert veredicto_vigente(v, P, "ZZ") == ("ok", version)


def test_qa_con_nativo_vigente_es_apta(v, tmp_path, monkeypatch, capsys):
    """La QA (Tarea 6) lee el veredicto de aquí: con uno vigente y lo demás verde, sale 0."""
    from trovefy.landing import qa

    from .test_qa_evaluar import Falso

    falso = Falso()
    falso.hitos = {s["orden"]: s["y_rel"] + 0.001 for s in qa.leer_hitos_esperados(v, cargar(v))}
    falso.version = qa.version_guardada(v, cargar(v))
    monkeypatch.setattr(qa, "medir", falso.medir)
    monkeypatch.setattr(qa, "probar_clic", falso.clic)
    args = ["landing", "qa", "--producto", P, "--pais", "ZZ"]
    assert cli.main(args) == 1
    registrar_veredicto(v, P, "ZZ", "ok", OK, AHORA)
    assert cli.main(args) == 0, capsys.readouterr().out
