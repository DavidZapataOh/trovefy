"""`trovify arranque confirmar`: el usuario confirma un patrón con su pantalla real (I-2)."""

import pathlib
import shutil

import pytest
import yaml
from trovify.arranque.verificadores.base import (
    fecha_confirmada,
    ultimo_texto_provisional,
)
from trovify.arranque.verificadores.cuenta import verificar_cuenta
from trovify.arranque.verificadores.impultienda import verificar_impultienda
from trovify.arranque.verificadores.meta_ids import verificar_business
from trovify.cli import main
from trovify.mapa import cargar
from trovify.navegador import Captura

RAIZ = pathlib.Path(__file__).resolve().parents[3]
FIX = RAIZ / "tests/fixtures/arranque"
PNG = b"\x89PNG\r\n\x1a\nfake"
ACT = "https://www.facebook.com/ads/manager/account_settings/account_billing/?act=987654321"


def _vault(tmp_path):
    cfg = tmp_path / "config"
    cfg.mkdir()
    for n in ("umbrales.yaml", "mercados.yaml"):
        shutil.copy(RAIZ / "templates/cerebro/config" / n, cfg / n)
    d = tmp_path / "productos/a/decisiones"
    d.mkdir(parents=True)
    (d / "2026-11-12-eleccion.md").write_text("---\npais: RO\n---\ncuerpo\n", encoding="utf-8")
    return tmp_path


def falso(texto, url_final=ACT):
    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        if captura_png is not None:
            captura_png.write_bytes(PNG)
        return Captura(url_final, "", texto, captura_png)

    return capturar


def _confirmaciones(v):
    ruta = v / "config/confirmaciones.yaml"
    return yaml.safe_load(ruta.read_text()) if ruta.exists() else None


def test_sin_texto_provisional_se_niega(tmp_path, capsys):
    assert main(["arranque", "confirmar", "06", "--respuesta", "si", "--vault", str(tmp_path)]) == 2
    assert "verificar 06" in capsys.readouterr().err
    assert _confirmaciones(tmp_path) is None


def test_paso_sin_patron_se_niega(tmp_path):
    assert main(["arranque", "confirmar", "07", "--respuesta", "si", "--vault", str(tmp_path)]) == 2


def test_patron_que_no_casa_se_niega(tmp_path, capsys):
    v = _vault(tmp_path)
    assert verificar_cuenta(v, capturar=falso("Configuración de pagos\nDivisa USD")).ok is None
    assert main(["arranque", "confirmar", "06", "--respuesta", "si", "--vault", str(v)]) == 2
    err = capsys.readouterr().err
    assert "no casa con tu pantalla real" in err and "repo" in err
    assert _confirmaciones(v) is None


@pytest.mark.parametrize("respuesta", ["si", "sí", "SI", "Sí"])
def test_confirmar_con_si_escribe_en_el_vault(tmp_path, capsys, respuesta):
    v = _vault(tmp_path)
    verificar_cuenta(v, capturar=falso((FIX / "ajustes_cuenta.txt").read_text()))
    capsys.readouterr()
    assert main(["arranque", "confirmar", "06", "--vault", str(v)]) == 0  # sin respuesta: solo muestra
    out = capsys.readouterr().out
    assert "moneda: USD" in out and "zona: Europe/Bucharest" in out
    assert _confirmaciones(v) is None
    assert main(["arranque", "confirmar", "06", "--respuesta", respuesta, "--vault", str(v)]) == 0
    c = _confirmaciones(v)["06"]
    archivo = ultimo_texto_provisional(v, "06")
    import hashlib

    assert c["texto_sha256"] == hashlib.sha256(archivo.read_bytes()).hexdigest()
    assert c["archivo"] == archivo.relative_to(v).as_posix() and len(str(c["fecha"])) == 10
    assert fecha_confirmada(v, "06") == str(c["fecha"])


def test_confirmar_con_no_no_escribe(tmp_path, capsys):
    v = _vault(tmp_path)
    verificar_cuenta(v, capturar=falso((FIX / "ajustes_cuenta.txt").read_text()))
    assert main(["arranque", "confirmar", "06", "--respuesta", "no", "--vault", str(v)]) == 1
    assert _confirmaciones(v) is None
    assert "no se guarda nada" in capsys.readouterr().out.lower()


def test_respuesta_invalida(tmp_path):
    v = _vault(tmp_path)
    verificar_cuenta(v, capturar=falso((FIX / "ajustes_cuenta.txt").read_text()))
    assert main(["arranque", "confirmar", "06", "--respuesta", "quizá", "--vault", str(v)]) == 2
    assert _confirmaciones(v) is None


def test_tras_confirmar_el_verificador_mide(tmp_path):
    v = _vault(tmp_path)
    bien = (FIX / "ajustes_cuenta.txt").read_text()
    assert verificar_cuenta(v, capturar=falso(bien)).ok is None
    assert main(["arranque", "confirmar", "06", "--respuesta", "si", "--vault", str(v)]) == 0
    r = verificar_cuenta(v, capturar=falso(bien))
    assert r.ok is True and r.evidencia
    assert verificar_cuenta(v, capturar=falso(bien.replace("Currency: USD", "Currency: COP"))).ok is False


def test_confirmacion_editada_a_mano_no_certifica(tmp_path):
    v = _vault(tmp_path)
    bien = (FIX / "ajustes_cuenta.txt").read_text()
    verificar_cuenta(v, capturar=falso(bien))
    (v / "config/confirmaciones.yaml").write_text(
        yaml.safe_dump({"06": {"fecha": "2026-11-10", "texto_sha256": "0" * 64, "archivo": "x"}})
    )
    assert fecha_confirmada(v, "06") is None
    assert verificar_cuenta(v, capturar=falso(bien)).ok is None


def test_confirmacion_del_04(tmp_path, capsys):
    url = "https://business.facebook.com/latest/settings?business_id=1234567890123&token=x"
    assert verificar_business(tmp_path, capturar=falso("", url)).ok is None
    assert main(["arranque", "confirmar", "04", "--vault", str(tmp_path)]) == 0
    assert "business_id: 1234567890123" in capsys.readouterr().out
    assert main(["arranque", "confirmar", "04", "--respuesta", "si", "--vault", str(tmp_path)]) == 0
    r = verificar_business(tmp_path, capturar=falso("", url))
    assert r.ok is True and r.datos == {"business_id": "1234567890123"}
    assert verificar_business(tmp_path, capturar=falso("", "https://business.facebook.com/overview")).ok is False


def _falso_impultienda(mapa, textos):
    por_url = {mapa["pantallas"][n]["url"]: t for n, t in textos.items()}

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        captura_png.write_bytes(PNG)
        return Captura(url, "", por_url[url], captura_png)

    return capturar


def test_confirmacion_de_un_mapa(tmp_path, capsys):
    mapa = cargar(RAIZ / "templates/impultienda/mapa.yaml")
    textos = {n: (FIX / f"impultienda_{n}.html").read_text() for n in ("plan", "tiendas", "pasarelas")}
    assert verificar_impultienda(tmp_path, capturar=_falso_impultienda(mapa, textos), mapa=mapa).ok is None
    assert main(["arranque", "confirmar", "09", "--respuesta", "sí", "--vault", str(tmp_path)]) == 0
    assert "plan.plan:" in capsys.readouterr().out
    r = verificar_impultienda(tmp_path, capturar=_falso_impultienda(mapa, textos), mapa=mapa)
    assert r.ok is True and r.evidencia
    sin_tiendas = {**textos, "tiendas": textos["tiendas"].replace("3 Tiendas activas", "0 Tiendas activas")}
    assert "0 Tiendas activas" in sin_tiendas["tiendas"]
    assert verificar_impultienda(tmp_path, capturar=_falso_impultienda(mapa, sin_tiendas), mapa=mapa).ok is False


def test_mapa_que_no_casa_no_se_confirma(tmp_path, capsys):
    mapa = cargar(RAIZ / "templates/impultienda/mapa.yaml")
    textos = {n: "otra pantalla" for n in ("plan", "tiendas", "pasarelas")}
    verificar_impultienda(tmp_path, capturar=_falso_impultienda(mapa, textos), mapa=mapa)
    assert main(["arranque", "confirmar", "09", "--respuesta", "si", "--vault", str(tmp_path)]) == 2
    assert _confirmaciones(tmp_path) is None


def test_checklist_acepta_si_con_tilde(tmp_path):
    from trovify.arranque.verificadores.checklist import CHECKLISTS

    claves = list(CHECKLISTS["03"])
    args = ["arranque", "checklist", "03", "--vault", str(tmp_path)]
    for c in claves:
        args += ["--respuesta", f"{c}=Sí"]
    assert main(args) == 0


def test_confirmaciones_corruptas_no_se_pisan(tmp_path, capsys):
    v = _vault(tmp_path)
    verificar_cuenta(v, capturar=falso((FIX / "ajustes_cuenta.txt").read_text()))
    ruta = v / "config/confirmaciones.yaml"
    ruta.write_text("[esto: no es: un mapa")
    assert main(["arranque", "confirmar", "06", "--respuesta", "si", "--vault", str(v)]) == 2
    assert ruta.read_text() == "[esto: no es: un mapa"
    assert fecha_confirmada(v, "06") is None


def test_confirmar_06_exige_el_limite(tmp_path, capsys):
    v = _vault(tmp_path)
    sin = "Currency: USD\nTime zone: Europe/Bucharest\nAccount spending limit\nSet limit\n"
    verificar_cuenta(v, capturar=falso(sin))
    assert main(["arranque", "confirmar", "06", "--respuesta", "si", "--vault", str(v)]) == 2
    assert "pon primero el límite de gasto (paso 5 de la guía) y vuelve a capturar" in capsys.readouterr().err
    assert _confirmaciones(v) is None
