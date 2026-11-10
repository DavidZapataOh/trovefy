from trovify.arranque.estado import marcar_hecho
from trovify.arranque.verificadores.base import Confirmacion
from trovify.arranque.verificadores.dominio import (
    evaluar_ns,
    evaluar_txt,
    verificar_dominio,
    verificar_verificacion_meta,
)
from trovify.cli import main
from trovify.dns import SinRed
from trovify.navegador import Captura, NavegadorError

CONF = Confirmacion(fecha="2026-11-11", fuente="prueba")
SIN_CONF = Confirmacion(fecha=None, fuente="prueba")
PNG = b"\x89PNG\r\n\x1a\nfake"
TXT_OK = ['"facebook-domain-verification=abc123"']


def test_ns_de_cloudflare():
    assert evaluar_ns(["ada.ns.cloudflare.com."]).ok is True
    assert evaluar_ns(["ada.NS.cloudflare.com"]).ok is True
    assert evaluar_ns(["ns1.otro.com."]).ok is False
    assert evaluar_ns(["ns1.evil-ns.cloudflare.com.attacker.com."]).ok is False
    assert evaluar_ns([]).ok is False


def test_txt_de_meta():
    assert evaluar_txt(TXT_OK).ok is True
    assert evaluar_txt(['"v=spf1 -all"']).ok is False
    assert evaluar_txt([]).ok is False


def dns_falso(respuestas):
    def consultar(nombre, tipo):
        r = respuestas[tipo]
        if isinstance(r, Exception):
            raise r
        return r

    return consultar


def paso(tmp_path, dominio="Kits-Docentes.com"):
    marcar_hecho(tmp_path, "07", None, {"dominio": dominio})


def test_07_sin_dominio_no_medido(tmp_path):
    r = verificar_dominio(tmp_path, consultar=dns_falso({}))
    assert r.ok is None and "dominio" in r.motivo


def test_07_ok_y_evidencia(tmp_path):
    paso(tmp_path)
    r = verificar_dominio(tmp_path, consultar=dns_falso({"NS": ["ada.ns.cloudflare.com.", "bob.ns.cloudflare.com."]}))
    assert r.ok is True and r.datos == {"dominio": "kits-docentes.com"}
    assert len(r.evidencia) == 1 and (tmp_path / r.evidencia[0]).is_file()
    assert "ada.ns.cloudflare.com." in (tmp_path / r.evidencia[0]).read_text()


def test_07_ns_ajenos_falla_con_arreglo(tmp_path):
    paso(tmp_path)
    r = verificar_dominio(tmp_path, consultar=dns_falso({"NS": ["ns1.otro.com."]}))
    assert r.ok is False and r.arreglos


def test_07_sin_red(tmp_path):
    paso(tmp_path)
    r = verificar_dominio(tmp_path, consultar=dns_falso({"NS": SinRed()}))
    assert r.ok is None and "sin red" in r.motivo


def falso(texto="kits-docentes.com Verificado", url_final="https://business.facebook.com/settings/owned-domains", png=PNG, error=None):
    llamadas = []

    def capturar(servicio, url, esperar_ms=3000, visible=True, captura_png=None):
        llamadas.append((servicio, url))
        if error:
            raise error
        if captura_png is not None and png is not None:
            captura_png.write_bytes(png)
        return Captura(url_final, "", texto, captura_png)

    capturar.llamadas = llamadas
    return capturar


def test_08_sin_txt_falla_sin_abrir_navegador(tmp_path):
    paso(tmp_path)
    cap = falso()
    r = verificar_verificacion_meta(tmp_path, capturar=cap, consultar=dns_falso({"TXT": ['"v=spf1 -all"']}), confirmacion=CONF)
    assert r.ok is False and r.arreglos and not cap.llamadas


def test_08_sin_dominio(tmp_path):
    r = verificar_verificacion_meta(tmp_path, capturar=falso(), consultar=dns_falso({}), confirmacion=CONF)
    assert r.ok is None and "dominio" in r.motivo


def test_08_sin_red(tmp_path):
    paso(tmp_path)
    r = verificar_verificacion_meta(tmp_path, capturar=falso(), consultar=dns_falso({"TXT": SinRed()}), confirmacion=CONF)
    assert r.ok is None and "sin red" in r.motivo


def test_08_sin_confirmar_no_certifica_aunque_haya_txt(tmp_path):
    paso(tmp_path)
    r = verificar_verificacion_meta(tmp_path, capturar=falso(), consultar=dns_falso({"TXT": TXT_OK}), confirmacion=SIN_CONF)
    assert r.ok is None and not r.datos and not r.evidencia
    assert "TXT de Meta encontrado" in r.motivo and "Business Settings" in r.motivo
    assert any(f.suffix == ".png" for f in (tmp_path / "config/evidencia/provisional").iterdir())


def test_08_confirmado_verificado(tmp_path):
    paso(tmp_path)
    cap = falso()
    r = verificar_verificacion_meta(tmp_path, capturar=cap, consultar=dns_falso({"TXT": TXT_OK}), confirmacion=CONF)
    assert r.ok is True and r.datos == {"dominio": "kits-docentes.com"}
    assert cap.llamadas == [("meta", "https://business.facebook.com/settings/owned-domains")]
    assert len(r.evidencia) == 2


def test_08_confirmado_no_verificado_o_ausente(tmp_path):
    paso(tmp_path)
    for texto in ("kits-docentes.com No verificado", "kits-docentes.com Not verified", "otro.com Verificado", ""):
        r = verificar_verificacion_meta(tmp_path, capturar=falso(texto), consultar=dns_falso({"TXT": TXT_OK}), confirmacion=CONF)
        assert r.ok is False and r.arreglos, texto


def test_08_navegador_y_sesion(tmp_path):
    paso(tmp_path)
    r = verificar_verificacion_meta(tmp_path, capturar=falso(error=NavegadorError("sin navegador")), consultar=dns_falso({"TXT": TXT_OK}), confirmacion=CONF)
    assert r.ok is None and "sin navegador" in r.motivo
    r = verificar_verificacion_meta(tmp_path, capturar=falso(url_final="https://www.facebook.com/login/?next=x"), consultar=dns_falso({"TXT": TXT_OK}), confirmacion=CONF)
    assert r.ok is None and "inicia sesión" in r.motivo


def test_dato_dominio_se_normaliza_y_valida(tmp_path):
    v = ["--vault", str(tmp_path)]
    assert main(["arranque", "hecho", "07", *v, "--dato", "dominio=https://www.Kits-Docentes.com/x"]) == 0
    from trovify.arranque.estado import cargar

    assert next(p for p in cargar(tmp_path) if p.id == "07").datos["dominio"] == "kits-docentes.com"
    assert main(["arranque", "hecho", "07", *v, "--dato", "dominio=192.168.0.1"]) != 0


def test_dominio_se_busca_con_limites():
    from trovify.arranque.verificadores.dominio import _estado_verificado

    assert not _estado_verificado("mikits.com Verificado\nkits.com No verificado", "kits.com")
    assert not _estado_verificado("mikits.com Verificado", "kits.com")
    assert not _estado_verificado("shop.kits.com Verificado", "kits.com")
    assert _estado_verificado("mikits.com No verificado\nkits.com Verificado", "kits.com")
    assert _estado_verificado("Dominio: kits.com — Verificado", "kits.com")


def test_07_fallo_guarda_la_medida_como_provisional(tmp_path):
    paso(tmp_path)
    r = verificar_dominio(tmp_path, consultar=dns_falso({"NS": ["ns1.otro.com."]}))
    assert r.ok is False and not r.evidencia
    assert not list((tmp_path / "config/evidencia").glob("07-ns-*.json"))
    assert list((tmp_path / "config/evidencia/provisional").glob("07-ns-*.json"))
