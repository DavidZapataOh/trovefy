import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from trovefy.pdf.gates import Informe
from trovefy.pdf.render import Producido, nombre_pdf
from trovefy.producto.cierre import EstadoPieza, cerrar, revisar
from trovefy.producto.config import iniciar_config
from trovefy.producto.ficha import crear_ficha, leer_ficha
from trovefy.producto.qc_registro import anotar_producido, anotar_qc
from trovefy.producto.rutas import pieza
from trovefy.vault import frontmatter

P = "p-0042-respira"
RAIZ = Path(__file__).resolve().parents[2]
FIXTURE = RAIZ / "fixtures" / "producto" / P
GOLDEN = RAIZ / "golden" / "producto" / "PRODUCTO-producido.md"
COT = ZoneInfo("America/Bogota")
FICHA_EN = datetime(2026, 11, 13, 9, 0, tzinfo=COT)
AHORA = datetime(2026, 11, 14, 10, 0, tzinfo=COT)
LUEGO = datetime(2026, 11, 15, 12, 0, tzinfo=COT)
MERCADOS = """\
ZZ: {idioma: es, moneda: EUR, zona: Europe/Madrid, banda_eur: [9, 19], estado: activo}
ZY: {idioma: bg, moneda: EUR, zona: Europe/Sofia, banda_eur: [9, 19], estado: activo}
ZX: {idioma: es, moneda: EUR, zona: Europe/Madrid, banda_eur: [9, 19], estado: activo}
"""
PIEZAS = ("principal", "bono-1", "bono-2", "bump", "u1")


def _editar(v, nombre, cambio):
    ruta = v / "productos" / P / f"{nombre}.md"
    meta, cuerpo = frontmatter.leer(ruta)
    cuerpo = cambio(meta) or cuerpo
    frontmatter.escribir(ruta, meta, cuerpo)


def _estado(v, estado, pais="ZZ"):
    _editar(v, "PRODUCTO", lambda m: m["paises"].setdefault(pais, {}).update(estado=estado))


def _vault(tmp_path) -> Path:
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    (v / "config" / "mercados.yaml").write_text(MERCADOS, encoding="utf-8")
    iniciar_config(v)
    shutil.copytree(FIXTURE, v / "productos" / P)
    crear_ficha(v, P, "ZZ", "sanitario", "ebook", FICHA_EN)
    return v


def _producir(v, pieza_id, version=1, *, desb=(), en_pdfinfo=24, revisor="ok", nativo="ok", pdf=True,
              ahora=AHORA):
    """Simula `producir_pdf` + `anotar_producido` + los dos agentes, sin WeasyPrint."""
    ficha = leer_ficha(v, P)
    raiz = pieza(v, P, pieza_id).raiz
    raiz.mkdir(parents=True, exist_ok=True)
    ruta = None
    if pdf:
        ruta = raiz / nombre_pdf(ficha, pieza_id, version)
        ruta.write_bytes(f"%PDF-1.7 {pieza_id} v{version}".encode())
    informe = Informe(hallazgos=(), puntuacion=92, pasa=True, palabras=8000, paginas_estimadas=24)
    apto = pdf and not desb and en_pdfinfo == 24
    r = Producido(version, raiz / "fuente" / f"x-v{version}.html", ruta, informe, 24 if pdf else None,
                  en_pdfinfo if pdf else None, tuple(desb), (), apto)
    anotar_producido(raiz, r, ahora)
    for agente, veredicto in (("revisor", revisor), ("nativo", nativo)):
        if veredicto != "falta":
            anotar_qc(raiz, version, agente, veredicto, f"VEREDICTO: {veredicto}", ahora)
    return raiz


def _todo_apto(v, sin=()):
    for pid in PIEZAS:
        if pid not in sin:
            _producir(v, pid)


def _producto(v) -> tuple[dict, str]:
    return frontmatter.leer(v / "productos" / P / "PRODUCTO.md")


# --- revisar -----------------------------------------------------------------------------------------


def test_revisar_una_por_pieza_con_su_ultima_version(tmp_path):
    v = _vault(tmp_path)
    _producir(v, "principal", 1, revisor="corregir")
    _producir(v, "principal", 2)
    estados = {e.id: e for e in revisar(v, P)}
    assert tuple(estados) == PIEZAS
    pr = estados["principal"]
    assert pr == EstadoPieza("principal", 2, "entregable/respira-lento-es-v2.pdf", 24, "ok", "ok", "ok", 0,
                             maqueta="ok", puntuacion=92, pdf_intacto=True)
    assert pr.apta
    assert estados["u1"].version is None and not estados["u1"].apta


def test_revisor_de_otra_version_no_cuenta(tmp_path):
    v = _vault(tmp_path)
    raiz = _producir(v, "principal", 1)
    ruta = raiz / "respira-lento-es-v2.pdf"
    ruta.write_bytes(b"%PDF v2 sin QC")
    e = next(x for x in revisar(v, P) if x.id == "principal")
    assert e.version == 2 and e.revisor is None and e.gates is None and not e.apta


# --- cerrar ------------------------------------------------------------------------------------------


def test_cerrar_avanza_a_producido(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert ok, mensajes
    meta, _ = _producto(v)
    assert meta["paises"]["ZZ"]["estado"] == "producido"
    assert meta["paises"]["ZZ"]["historial"][-1]["evidencia"][0] == f"productos/{P}/entregable/respira-lento-es-v1.pdf"
    assert meta["entregable"]["es"]["principal"] == {"version": 1, "pdf": "entregable/respira-lento-es-v1.pdf",
                                                     "paginas": 24, "fecha": "2026-11-14"}
    assert meta["entregable"]["es"]["u1"]["pdf"] == "entregable/upsells/u1/respira-lento-u1-es-v1.pdf"
    texto = (v / "productos" / P / "PRODUCTO.md").read_text(encoding="utf-8")
    assert texto == GOLDEN.read_text(encoding="utf-8")
    assert "cierre del entregable" in (v / "log.md").read_text(encoding="utf-8")


def test_upsell_sin_entregable_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("u1",))
    antes = (v / "productos" / P / "PRODUCTO.md").read_text(encoding="utf-8")
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "u1: sin PDF (cada upsell tiene su entregable real)" in mensajes
    assert _producto(v)[0]["paises"]["ZZ"]["estado"] == "modelado"
    assert (v / "productos" / P / "PRODUCTO.md").read_text(encoding="utf-8") == antes


def test_bump_sin_entregable_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("bump",))
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert any(m.startswith("bump: sin PDF") for m in mensajes)


def test_nativo_sin_veredicto_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("principal",))
    _producir(v, "principal", 3, nativo="falta")
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "principal v3: nativo no medido" in mensajes
    assert _producto(v)[0]["paises"]["ZZ"]["estado"] == "modelado"


def test_revisor_corregir_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("bono-1",))
    _producir(v, "bono-1", revisor="corregir")
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "bono-1 v1: revisor pide corregir" in mensajes


def test_desborde_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("principal",))
    _producir(v, "principal", desb=("diario",))
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert any(m.startswith("principal v1: desborda") for m in mensajes)
    assert _producto(v)[0]["paises"]["ZZ"]["estado"] == "modelado"


def test_sin_pdfinfo_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("principal",))
    _producir(v, "principal", en_pdfinfo=None)
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "principal v1: pdfinfo no medido" in mensajes


def test_pdf_cambiado_despues_del_qc_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    (v / "productos" / P / "entregable" / "respira-lento-es-v1.pdf").write_bytes(b"%PDF otro")
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert any("cambió después del QC" in m for m in mensajes)


def test_idioma_del_pais_distinto(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _estado(v, "modelado", "ZY")
    ok, mensajes = cerrar(v, P, "ZY", AHORA)
    assert not ok
    assert mensajes == ["ZY habla bg y el entregable está en es: produce la versión bg"]
    assert _producto(v)[0]["paises"]["ZY"]["estado"] == "modelado"


def test_estado_aprobado_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _estado(v, "aprobado")
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert mensajes == ["ZZ está en «aprobado»: primero /modelar"]


def test_estado_posterior_no_retrocede(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _estado(v, "con_landing")
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert ok
    assert any("con_landing" in m and "no cambia" in m for m in mensajes)
    meta, cuerpo = _producto(v)
    assert meta["paises"]["ZZ"]["estado"] == "con_landing"
    assert "- 2026-11-14 · principal v1 · entregable/respira-lento-es-v1.pdf · 24 págs · gates 92 · " \
           "revisor ok · nativo ok" in cuerpo


def test_conserva_lo_previo(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)

    def previo(m):
        m["paises"]["ZY"] = {"estado": "aprobado", "nota": "reserva"}
        m["paises"]["ZX"] = {"estado": "modelado", "landing": {"url": "https://ejemplo.invalid"}}
        m["apimart_tope_usd"] = "3.00"
        m["entregable"] = {"bg": {"principal": {"version": 4, "pdf": "entregable/dishai-bg-v4.pdf"}}}
        return "# Producto p-0042-respira\n\nNotas propias del usuario.\n"

    _editar(v, "PRODUCTO", previo)
    ok, _ = cerrar(v, P, "ZZ", AHORA)
    assert ok
    meta, cuerpo = _producto(v)
    assert meta["paises"]["ZY"] == {"estado": "aprobado", "nota": "reserva"}
    assert meta["paises"]["ZX"]["landing"] == {"url": "https://ejemplo.invalid"}
    assert meta["paises"]["ZX"]["estado"] == "modelado"
    assert meta["apimart_tope_usd"] == "3.00"
    assert meta["entregable"]["bg"]["principal"]["version"] == 4
    assert meta["entregable"]["es"]["principal"]["version"] == 1
    assert meta["senales"]["se_puede_mejorar"] is True
    assert cuerpo.startswith("# Producto p-0042-respira\n\nNotas propias del usuario.\n")


def test_segunda_version_anade_linea(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    assert cerrar(v, P, "ZZ", AHORA)[0]
    _producir(v, "principal", 2, ahora=LUEGO)
    ok, mensajes = cerrar(v, P, "ZX", LUEGO)  # mismo idioma, otro país
    assert not ok and mensajes == ["ZX está en «sin estado»: primero /modelar"]
    ok, mensajes = cerrar(v, P, "ZZ", LUEGO)
    assert ok
    assert any("producido" in m and "no cambia" in m for m in mensajes)
    meta, cuerpo = _producto(v)
    assert meta["entregable"]["es"]["principal"]["version"] == 2
    assert cuerpo.count("## Versiones del entregable") == 1
    assert "- 2026-11-14 · principal v1 · entregable/respira-lento-es-v1.pdf" in cuerpo
    assert "- 2026-11-15 · principal v2 · entregable/respira-lento-es-v2.pdf" in cuerpo
    assert cuerpo.index("principal v1") < cuerpo.index("principal v2")
    assert len(meta["paises"]["ZZ"]["historial"]) == 2  # aprobado→modelado y modelado→producido


def test_repetir_cierre_no_duplica_lineas(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    assert cerrar(v, P, "ZZ", AHORA)[0]
    assert cerrar(v, P, "ZZ", AHORA)[0]
    _, cuerpo = _producto(v)
    assert cuerpo.count("· principal v1 ·") == 1


def test_ficha_desfasada_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _editar(v, "ESCALERA", lambda m: m["paises"]["ZZ"]["pasos"]["u2"].update(activo=True))
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert any(m.startswith("u2: no está en FICHA.md") for m in mensajes)


def test_sin_zona_falla(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(ValueError, match="zona"):
        cerrar(v, P, "ZZ", datetime(2026, 11, 14, 10, 0))
