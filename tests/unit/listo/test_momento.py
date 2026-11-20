"""Plan 20, Tarea 3: gates del instante (landing en móvil, caja, ejecutor y STOP)."""

import urllib.error
from datetime import date, timedelta

from trovefy.listo.momento import (
    UA_MOVIL,
    OtroSitio,
    gate_caja,
    gate_ejecutor,
    gate_landing_movil,
    gate_stop,
)

from .conftest import (
    AHORA,
    abrir_landing_falso,
    romper,
    spool_con,
    trm_fijo,
    vault_con_caja,
)

HOY = date(2026, 11, 21)


def test_landing_200_movil_ok(ficha_verde):
    abrir = abrir_landing_falso(200, b"<html>ok</html>")
    g = gate_landing_movil(ficha_verde[1], abrir=abrir)
    assert g.estado == "ok" and g.evidencia[0].startswith("HTTP 200 · https://tienda-prueba.example/zz/")
    req, _ = abrir.peticiones[-1]
    assert req.get_header("User-agent") == UA_MOVIL


def test_landing_404_falla(ficha_verde):
    g = gate_landing_movil(ficha_verde[1], abrir=abrir_landing_falso(404))
    assert g.estado == "falla" and "404" in g.texto


def test_landing_sin_red_no_medido(ficha_verde):
    g = gate_landing_movil(ficha_verde[1], abrir=abrir_landing_falso(error=urllib.error.URLError("x")))
    assert g.estado == "no_medido" and g.texto == "no medido: sin red"


def test_landing_redirige_a_otro_host_falla(ficha_verde):
    g = gate_landing_movil(ficha_verde[1], abrir=abrir_landing_falso(final="https://prueba.pages.dev/"))
    assert g.estado == "falla" and "redirige a otro sitio" in g.texto
    g = gate_landing_movil(ficha_verde[1], abrir=abrir_landing_falso(error=OtroSitio("malo.example")))
    assert g.estado == "falla" and "malo.example" in g.texto


def test_landing_no_html_falla(ficha_verde):
    assert gate_landing_movil(ficha_verde[1], abrir=abrir_landing_falso(tipo="application/json")).estado == "falla"


def test_landing_sin_qa_390_no_medido(ficha_verde):
    abrir = abrir_landing_falso()
    g = gate_landing_movil(romper(ficha_verde[1], "landing.qa.movil_390", None), abrir=abrir)
    assert g.estado == "no_medido" and abrir.peticiones == []


def test_landing_pixel_pendiente_falla(ficha_verde):
    _, f = ficha_verde
    (f.carpeta / "landing/ZZ/landing.yaml").write_text("pixel: pendiente\n")
    assert gate_landing_movil(f, abrir=abrir_landing_falso()).estado == "falla"


def test_redireccion_real_a_otro_host_se_corta():
    from trovefy.listo.momento import _SoloMismoHost

    h = _SoloMismoHost("tienda-prueba.example")
    try:
        h.redirect_request(None, None, 302, "x", {}, "https://otro.example/")
    except OtroSitio as exc:
        assert exc.host == "otro.example"
    else:
        raise AssertionError("no cortó la redirección")


# --- caja -----------------------------------------------------------------------------------------------------------


def test_caja_con_huecos_ok(tmp_path):
    assert gate_caja(vault_con_caja(tmp_path), HOY, trm_fijo).estado == "ok"


def _con_tests(vault, tests: str):
    ruta = vault / "config" / "caja.yaml"
    ruta.write_text(ruta.read_text().replace("tests: []", f"tests: {tests}"))


def test_caja_sin_huecos_falla(tmp_path):
    vault = vault_con_caja(tmp_path)
    ruta = vault / "config" / "caja.yaml"
    ruta.write_text(ruta.read_text().replace("{herramientas: 20, tests: 280, reserva: 200}",
                                             "{herramientas: 20, tests: 20, reserva: 460}"))
    g = gate_caja(vault, HOY, trm_fijo)
    assert g.estado == "falla" and "0 huecos de test" in g.texto


def test_caja_dos_tests_vivos_no_caben(tmp_path):
    vault = vault_con_caja(tmp_path)
    caja = vault / "config" / "caja.yaml"  # techo pequeño: aquí se prueba el tope diario, no los huecos
    caja.write_text(caja.read_text().replace("techo_usd: 100, prorroga_hasta_usd: 100",
                                             "techo_usd: 30, prorroga_hasta_usd: 55"))
    ledger = vault / "ledger" / "gasto"
    ledger.mkdir(parents=True)
    (ledger / "2026-11.csv").write_text("fecha,cuenta,campana,gasto,moneda\n"
                                        "2026-11-20,act_0000000000000000,c1,1.00,USD\n"
                                        "2026-11-20,act_0000000000000000,c2,1.00,USD\n")
    _con_tests(vault, "[{producto: p1, pais: ZZ, campana_id: c1, estado: vivo, prorroga: false, ventas: null, "
                      "diario_usd: 25}, {producto: p2, pais: ZZ, campana_id: c2, estado: vivo, prorroga: false, "
                      "ventas: null, diario_usd: 25}]")
    g = gate_caja(vault, HOY, trm_fijo)
    assert g.estado == "falla" and "no cabe" in g.texto


def test_caja_sin_archivo_no_medido(tmp_path):
    g = gate_caja(tmp_path, HOY, trm_fijo)
    assert g.estado == "no_medido" and g.arreglo == "trovefy caja iniciar"


def test_caja_corrupta_no_medido(tmp_path):
    vault = vault_con_caja(tmp_path)
    (vault / "config" / "caja.yaml").write_text("capital_usd: [\n")
    assert gate_caja(vault, HOY, trm_fijo).estado == "no_medido"


# --- ejecutor y STOP ------------------------------------------------------------------------------------------------


def test_latido_de_5_min_ok(tmp_path):
    spool = spool_con(tmp_path, {"latido": {"fecha": (AHORA - timedelta(minutes=5)).isoformat()}})
    assert gate_ejecutor(AHORA, spool).estado == "ok"


def test_latido_de_11_min_falla(tmp_path):
    spool = spool_con(tmp_path, {"latido": {"fecha": (AHORA - timedelta(minutes=11)).isoformat()}})
    assert gate_ejecutor(AHORA, spool).estado == "falla"


def test_sin_ejecutor_instalado_no_medido(tmp_path):
    assert gate_ejecutor(AHORA, tmp_path / "spool").estado == "no_medido"
    assert gate_stop(tmp_path, tmp_path / "spool").estado == "no_medido"


def test_stop_del_cerebro_falla(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".trovefy").mkdir(parents=True)
    (vault / ".trovefy" / "STOP").write_text("")
    g = gate_stop(vault, spool_con(tmp_path, {"stop": {"activo": False}}))
    assert g.estado == "falla" and "STOP del cerebro" in g.texto


def test_stop_del_ejecutor_falla(tmp_path):
    g = gate_stop(tmp_path / "vault", spool_con(tmp_path, {"stop": {"activo": True}}))
    assert g.estado == "falla" and "STOP del ejecutor" in g.texto


def test_sin_stop_ok(tmp_path):
    assert gate_stop(tmp_path / "vault", spool_con(tmp_path, {"stop": {"activo": False}})).estado == "ok"
