"""Plan 18b: publicar en Impultienda con pegado manual (el usuario pega en su navegador; trovefy no entra al panel)."""

import io
import os
import stat
from pathlib import Path

import pytest
import yaml
from trovefy import cli
from trovefy.landing import manual
from trovefy.landing.entrada import ruta_landing
from trovefy.landing.hosting import empaquetar_en_linea
from trovefy.landing.plantilla import leer_landing_yaml
from trovefy.landing.publicar import NoPublicable

from .conftest import DOMINIO, MERCADOS, TIENDA, Ejecutar, P, cargar
from .test_hosting import montar as montar_landing
from .test_publicar import (
    AHORA,
    LCP_ALTO,
    QAFalsa,
    _abrir,
    escribir_qa,
    nativo_ok,
    producto,
    version,
)

SECRETO = "<p>EAAB" + "x7Kq2" * 8 + "</p>"


@pytest.fixture(autouse=True)
def _sin_panel(monkeypatch):
    """El pegado manual nunca abre un navegador ni el panel: cualquier intento falla el test."""
    from trovefy import navegador
    from trovefy.landing import panel, publicar

    def nunca(*_a, **_k):
        raise AssertionError("el pegado manual no abre el navegador")

    for mod in (navegador, panel, publicar):
        monkeypatch.setattr(mod, "sesion", nunca)
    monkeypatch.setattr(publicar, "publicar_impultienda", nunca)


def lista_sin_sonda(tmp_path, hosting="impultienda") -> Path:
    """Landing guardada, QA local verde y nativo ok, **sin** evidencia de la sonda (p05-impultienda-*.json)."""
    v = montar_landing(tmp_path, hosting)
    escribir_qa(v)
    nativo_ok(v)
    assert not list((v / "config").glob("evidencia/p05-impultienda-*.json"))
    return v


def servida(v: Path, sin_script: bool = False) -> bytes:
    """La página de la tienda con el paquete pegado dentro (como la serviría Impultienda)."""
    paquete = empaquetar_en_linea(ruta_landing(v, P, "ZZ"))
    if sin_script:
        import re

        paquete = re.sub(r"<script>.*?</script>", "", paquete, flags=re.DOTALL)
    return f"<!doctype html><html><head><meta charset=utf-8></head><body>{paquete}</body></html>".encode()


# --- primera llamada: el paquete y las instrucciones ----------------------------------------------


def test_pegado_escribe_el_paquete_en_linea_0640(tmp_path):
    v = lista_sin_sonda(tmp_path)
    ruta = manual.preparar_pegado(v, cargar(v))
    assert ruta == ruta_landing(v, P, "ZZ") / "publicar" / "impultienda.html"
    assert ruta.read_text(encoding="utf-8") == empaquetar_en_linea(ruta_landing(v, P, "ZZ"))
    assert stat.S_IMODE(ruta.stat().st_mode) == 0o640


def test_pegado_con_las_puertas_de_siempre(tmp_path):
    v = lista_sin_sonda(tmp_path)
    (ruta_landing(v, P, "ZZ") / "QA.md").unlink()
    with pytest.raises(NoPublicable, match="trovefy landing qa"):
        manual.preparar_pegado(v, cargar(v))
    assert not (ruta_landing(v, P, "ZZ") / "publicar" / "impultienda.html").exists()


def test_pegado_solo_para_una_landing_de_impultienda(tmp_path):
    v = lista_sin_sonda(tmp_path, "cloudflare")
    with pytest.raises(NoPublicable, match="Cloudflare"):
        manual.preparar_pegado(v, cargar(v))


def test_pegado_con_algo_con_forma_de_secreto_no_se_escribe(tmp_path, monkeypatch):
    v = lista_sin_sonda(tmp_path)
    monkeypatch.setattr(manual, "empaquetar_en_linea", lambda _r: SECRETO)
    with pytest.raises(NoPublicable, match="secreto"):
        manual.preparar_pegado(v, cargar(v))
    assert not (ruta_landing(v, P, "ZZ") / "publicar" / "impultienda.html").exists()


def test_instrucciones_dicen_archivo_tamano_y_pasos(tmp_path):
    v = lista_sin_sonda(tmp_path)
    d = cargar(v)
    ruta = manual.preparar_pegado(v, d)
    texto = manual.instrucciones_pegado(v, d, ruta, AHORA)
    n = len(ruta.read_text(encoding="utf-8"))
    assert str(ruta) in texto and f"{n:,}".replace(",", ".") + " caracteres" in texto
    assert "Diseño de tienda → Contenido" in texto
    assert "respaldo/impultienda-2026-11-17T103000-manual.html" in texto
    assert f"trovefy landing respaldo --producto {P} --pais ZZ" in texto
    assert f"trovefy landing publicar --producto {P} --pais ZZ --manual --url https://" in texto
    assert f"https://{DOMINIO}/" in texto and f"{TIENDA}/" in texto
    assert "https://impultienda.ar/login" in texto
    pasos = [linea for linea in texto.splitlines() if linea[:3] in ("1. ", "2. ", "3. ", "4. ")]
    assert [p[:2] for p in pasos] == ["1.", "2.", "3.", "4."]


def test_instrucciones_en_wsl_dan_la_ruta_de_windows(tmp_path, monkeypatch):
    v = lista_sin_sonda(tmp_path)
    d = cargar(v)
    ruta = manual.preparar_pegado(v, d)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    texto = manual.instrucciones_pegado(v, d, ruta, AHORA)
    assert "\\\\wsl.localhost\\Ubuntu\\" in texto and "\\publicar\\impultienda.html" in texto


# --- respaldo -------------------------------------------------------------------------------------


def test_respaldo_manual_0640_sin_pisar(tmp_path):
    v = lista_sin_sonda(tmp_path)
    a = manual.guardar_respaldo(v, P, "ZZ", "<p>lo de antes</p>", AHORA)
    b = manual.guardar_respaldo(v, P, "ZZ", "<p>otra vez</p>", AHORA)
    carpeta = ruta_landing(v, P, "ZZ") / "respaldo"
    assert a == carpeta / "impultienda-2026-11-17T103000-manual.html"
    assert b == carpeta / "impultienda-2026-11-17T103000-manual-2.html"
    assert a.read_text(encoding="utf-8") == "<p>lo de antes</p>"
    assert stat.S_IMODE(a.stat().st_mode) == 0o640


def test_respaldo_manual_es_el_ultimo_respaldo(tmp_path):
    from trovefy.landing.panel import ultimo_respaldo

    v = lista_sin_sonda(tmp_path)
    a = manual.guardar_respaldo(v, P, "ZZ", "<p>lo de antes</p>", AHORA)
    assert ultimo_respaldo(v, "ZZ") == a


@pytest.mark.parametrize(("contenido", "error"), [(SECRETO, "secreto"), ("  \n", "vacío")])
def test_respaldo_manual_no_guarda_secretos_ni_vacios(tmp_path, contenido, error):
    v = lista_sin_sonda(tmp_path)
    with pytest.raises(ValueError, match=error):
        manual.guardar_respaldo(v, P, "ZZ", contenido, AHORA)
    assert not (ruta_landing(v, P, "ZZ") / "respaldo").exists()


# --- segunda llamada: verificar la tienda -----------------------------------------------------------


def _verificar(v, url, cuerpo=None, qa=None):
    return manual.verificar_manual(v, cargar(v), url, qa=qa or QAFalsa(), abrir=_abrir(cuerpo or servida(v)),
                                   ahora=AHORA)


@pytest.mark.parametrize("url", [f"https://{DOMINIO}/", f"{TIENDA}/"])
def test_verificar_en_verde_registra_con_landing_y_publicacion_manual(tmp_path, url):
    v = lista_sin_sonda(tmp_path)
    qa = QAFalsa()
    r = _verificar(v, url, qa=qa)
    assert r.url == url and r.estado == "con_landing" and qa.urls == [url]
    zz = producto(v)[0]["paises"]["ZZ"]
    assert zz["estado"] == "con_landing" and zz["landing"]["url"] == url
    assert zz["landing"]["hosting"] == "impultienda"
    ly = leer_landing_yaml(v, P, "ZZ")
    assert ly["publicacion"] == "manual" and ly["publicada"] and ly["version_publicada"] == version(v)


@pytest.mark.parametrize("url", ["https://otro.test/", f"http://{DOMINIO}/", "https://app.impultienda.ar/",
                                 "https://127.0.0.1/"])
def test_verificar_solo_tu_dominio_o_tu_tienda(tmp_path, url):
    v = lista_sin_sonda(tmp_path)

    def nunca(*_a, **_k):
        raise AssertionError("no debía abrir la URL")

    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable, match="tu dominio o tu tienda"):
        manual.verificar_manual(v, cargar(v), url, qa=nunca, abrir=nunca, ahora=AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


def test_verificar_otra_version_pregunta_si_guardaste(tmp_path):
    v = lista_sin_sonda(tmp_path)
    vieja = servida(v).replace(version(v).encode(), b"0123456789ab")

    def nunca(*_a, **_k):
        raise AssertionError("sin la versión actual no hay QA")

    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    with pytest.raises(NoPublicable, match="¿guardaste en el panel?"):
        manual.verificar_manual(v, cargar(v), f"https://{DOMINIO}/", qa=nunca, abrir=_abrir(vieja), ahora=AHORA)
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes


def test_verificar_con_redireccion_a_otro_host_no_vale(tmp_path):
    v = lista_sin_sonda(tmp_path)
    with pytest.raises(NoPublicable, match="¿guardaste en el panel?"):
        manual.verificar_manual(v, cargar(v), f"https://{DOMINIO}/", qa=QAFalsa(),
                                abrir=_abrir(servida(v), final="https://otro.test/"), ahora=AHORA)


def test_verificar_en_rojo_no_registra_y_nombra_el_respaldo(tmp_path):
    v = lista_sin_sonda(tmp_path)
    resp = manual.guardar_respaldo(v, P, "ZZ", "<p>lo de antes</p>", AHORA)
    antes = (v / "productos" / P / "PRODUCTO.md").read_bytes()
    ly_antes = leer_landing_yaml(v, P, "ZZ")
    with pytest.raises(NoPublicable) as e:
        _verificar(v, f"https://{DOMINIO}/", qa=QAFalsa(LCP_ALTO))
    msg = str(e.value)
    assert "QA-publicada.md" in msg and str(resp) in msg and "pega" in msg
    assert (v / "productos" / P / "PRODUCTO.md").read_bytes() == antes
    assert leer_landing_yaml(v, P, "ZZ") == ly_antes


def test_verificar_en_rojo_sin_respaldo_dice_el_tuyo(tmp_path):
    v = lista_sin_sonda(tmp_path)
    with pytest.raises(NoPublicable, match="copia que guardaste"):
        _verificar(v, f"https://{DOMINIO}/", qa=QAFalsa(LCP_ALTO))


def test_verificar_con_las_puertas_de_siempre(tmp_path):
    v = lista_sin_sonda(tmp_path)
    nativo = ruta_landing(v, P, "ZZ") / "nativo.md"
    nativo.unlink()
    with pytest.raises(NoPublicable, match="nativo"):
        _verificar(v, f"https://{DOMINIO}/")


def _sin_tienda(v: Path) -> None:
    (v / "config" / "mercados.yaml").write_text(MERCADOS.replace(f'tienda: "{TIENDA}"', "tienda: null"),
                                               encoding="utf-8")


def test_verificar_guarda_la_tienda_si_no_estaba(tmp_path):
    v = lista_sin_sonda(tmp_path)
    _sin_tienda(v)
    assert cargar(v).tienda is None
    qa = QAFalsa()
    r = _verificar(v, "https://mitienda.impultienda.ar/", qa=qa)
    assert r.tienda_guardada == "https://mitienda.impultienda.ar"
    assert yaml.safe_load((v / "config" / "mercados.yaml").read_text(encoding="utf-8"))["ZZ"]["tienda"] == \
        "https://mitienda.impultienda.ar"
    assert producto(v)[0]["paises"]["ZZ"]["estado"] == "con_landing"


def test_verificar_sin_tienda_no_acepta_cualquier_host(tmp_path):
    v = lista_sin_sonda(tmp_path)
    _sin_tienda(v)
    with pytest.raises(NoPublicable, match="tu dominio o tu tienda"):
        _verificar(v, "https://mitienda.otra-plataforma.test/")


def test_verificar_qa_roja_no_guarda_la_tienda(tmp_path):
    v = lista_sin_sonda(tmp_path)
    _sin_tienda(v)
    antes = (v / "config" / "mercados.yaml").read_bytes()
    with pytest.raises(NoPublicable, match="no he registrado nada"):
        _verificar(v, "https://mitienda.impultienda.ar/", qa=QAFalsa(LCP_ALTO))
    assert (v / "config" / "mercados.yaml").read_bytes() == antes


def test_verificar_con_tienda_invalida_para_limpio(tmp_path):
    v = lista_sin_sonda(tmp_path)
    (v / "config" / "mercados.yaml").write_text(
        MERCADOS.replace(f'tienda: "{TIENDA}"', 'tienda: "http://vieja.impultienda.ar"'), encoding="utf-8")
    antes = (v / "config" / "mercados.yaml").read_bytes()
    with pytest.raises(NoPublicable):
        _verificar(v, "https://mitienda.impultienda.ar/")
    assert (v / "config" / "mercados.yaml").read_bytes() == antes


def test_verificar_con_tienda_ya_guardada_no_la_toca(tmp_path):
    v = lista_sin_sonda(tmp_path)
    antes = (v / "config" / "mercados.yaml").read_bytes()
    r = _verificar(v, f"https://{DOMINIO}/")
    assert r.tienda_guardada is None
    assert (v / "config" / "mercados.yaml").read_bytes() == antes


# --- CLI ------------------------------------------------------------------------------------------


@pytest.fixture
def cli_lista(tmp_path, monkeypatch):
    from trovefy import landing_cli

    v = lista_sin_sonda(tmp_path)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", Ejecutar())
    return v


def test_cli_publicar_manual_sin_url_deja_el_paquete_y_las_instrucciones(cli_lista, capsys):
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ", "--manual"]) == 0
    out = capsys.readouterr().out
    assert "publicar/impultienda.html" in out and "Diseño de tienda → Contenido" in out
    assert (ruta_landing(cli_lista, P, "ZZ") / "publicar" / "impultienda.html").is_file()


def test_cli_publicar_manual_con_url_verifica(cli_lista, capsys, monkeypatch):
    from trovefy.landing import publicar as mod

    monkeypatch.setattr(mod, "_qa_publicada", QAFalsa())
    monkeypatch.setattr(manual, "_abrir_seguro", _abrir(servida(cli_lista)))
    url = f"https://{DOMINIO}/"
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ", "--manual", "--url", url]) == 0
    assert f"ZZ → con_landing: {url}" in capsys.readouterr().out


def test_cli_publicar_manual_y_campo_vacio_no_van_juntos(cli_lista, capsys):
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ", "--manual", "--campo-vacio"]) == 2


def test_cli_publicar_url_sin_manual_en_impultienda_sigue_siendo_error(cli_lista, capsys):
    url = f"https://{DOMINIO}/"
    assert cli.main(["landing", "publicar", "--producto", P, "--pais", "ZZ", "--url", url]) == 1


def test_cli_respaldo_desde_archivo(cli_lista, capsys, tmp_path):
    origen = tmp_path / "copia.html"
    origen.write_text("<p>mi tienda</p>\n", encoding="utf-8")
    assert cli.main(["landing", "respaldo", "--producto", P, "--pais", "ZZ", "--desde", str(origen)]) == 0
    hechos = list((ruta_landing(cli_lista, P, "ZZ") / "respaldo").glob("impultienda-*-manual.html"))
    assert len(hechos) == 1 and hechos[0].read_text(encoding="utf-8") == "<p>mi tienda</p>\n"
    assert str(hechos[0]) in capsys.readouterr().out


def test_cli_respaldo_desde_la_entrada(cli_lista, capsys, monkeypatch):
    class Entrada(io.TextIOWrapper):
        def isatty(self):
            return False

    monkeypatch.setattr("sys.stdin", Entrada(io.BytesIO(b"<p>pegado</p>")))
    assert cli.main(["landing", "respaldo", "--producto", P, "--pais", "ZZ"]) == 0
    hechos = list((ruta_landing(cli_lista, P, "ZZ") / "respaldo").glob("impultienda-*-manual.html"))
    assert [h.read_text(encoding="utf-8") for h in hechos] == ["<p>pegado</p>"]


def test_cli_respaldo_vacio_sale_2(cli_lista, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(b"")))
    assert cli.main(["landing", "respaldo", "--producto", P, "--pais", "ZZ"]) == 2
    assert not (ruta_landing(cli_lista, P, "ZZ") / "respaldo").exists()


def test_cli_estado_sin_sonda_ofrece_el_pegado_manual(cli_lista, capsys):
    assert cli.main(["landing", "estado", "--producto", P, "--pais", "ZZ"]) == 0
    linea = next(x for x in capsys.readouterr().out.splitlines() if x.startswith("Hosting:"))
    assert "impultienda (pegado manual)" in linea and "--manual" in linea


def test_mapa_avisa_de_las_urls_sin_verificar():
    from trovefy.landing.panel import MAPA_IMPULTIENDA

    texto = MAPA_IMPULTIENDA.read_text(encoding="utf-8")
    assert "No hay ninguna tienda acá" in texto and "https://impultienda.ar/login" in texto
    assert os.path.basename(MAPA_IMPULTIENDA) == "mapa.yaml"
