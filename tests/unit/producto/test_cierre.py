import hashlib
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
ZW: {idioma: es, moneda: USD, zona: America/New_York, banda_eur: [9, 19], estado: activo}
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
              ahora=AHORA, gates=True):
    """Simula `producir_pdf` + `anotar_producido` + los dos agentes, sin WeasyPrint."""
    ficha = leer_ficha(v, P)
    raiz = pieza(v, P, pieza_id).raiz
    raiz.mkdir(parents=True, exist_ok=True)
    ruta = None
    if pdf:
        ruta = raiz / nombre_pdf(ficha, pieza_id, version)
        ruta.write_bytes(f"%PDF-1.7 {pieza_id} v{version}".encode())
    informe = Informe(hallazgos=(), puntuacion=92, pasa=gates, palabras=8000, paginas_estimadas=24)
    apto = pdf and not desb and en_pdfinfo == 24
    r = Producido(version, raiz / "fuente" / f"x-v{version}.html", ruta, informe, 24 if pdf else None,
                  en_pdfinfo if pdf else None, tuple(desb), (), apto)
    anotar_producido(raiz, r, ahora)
    for agente, veredicto in (("revisor", revisor), ("nativo", nativo)):
        if veredicto != "falta" and pdf:
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


# --- ronda de revisión de las tareas 11–12 -----------------------------------------------------------


def _pdf_principal(v, version=1) -> Path:
    return v / "productos" / P / "entregable" / f"respira-lento-es-v{version}.pdf"


def test_cambiar_el_pdf_y_reanotar_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    raiz = pieza(v, P, "principal").raiz
    pdf = _pdf_principal(v)
    pdf.write_bytes(b"%PDF-1.7 CONTENIDO NUEVO NO REVISADO")
    inf = Informe(hallazgos=(), puntuacion=92, pasa=True, palabras=8000, paginas_estimadas=24)
    with pytest.raises(ValueError, match="ya tiene maqueta"):
        anotar_producido(raiz, Producido(1, raiz / "fuente" / "x.html", pdf, inf, 24, 24, (), (), True), LUEGO)
    with pytest.raises(ValueError, match="ya tiene maqueta"):
        anotar_qc(raiz, 1, "maqueta", "ok", "x", LUEGO)
    anotar_qc(raiz, 1, "revisor", "ok", "VEREDICTO: ok", LUEGO)
    ok, mensajes = cerrar(v, P, "ZZ", LUEGO)
    assert not ok
    assert any("cambió después del QC" in m for m in mensajes)


def test_veredictos_de_otro_pdf_no_cuentan(tmp_path):
    """Una maqueta añadida a mano con el sha del PDF nuevo no rescata los veredictos del PDF viejo."""
    v = _vault(tmp_path)
    _todo_apto(v)
    pdf = _pdf_principal(v)
    pdf.write_bytes(b"%PDF-1.7 CONTENIDO NUEVO NO REVISADO")
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    qc = pieza(v, P, "principal").raiz / "QC.md"
    qc.write_text(qc.read_text(encoding="utf-8") + "\n## v1 · maqueta · 2026-11-15 12:00\n\n- veredicto: ok\n"
                  f"- pdf: {pdf.name}\n- sha256: {sha}\n- paginas: 24\n- pdfinfo: 24\n- desbordes: 0\n",
                  encoding="utf-8")
    e = next(x for x in revisar(v, P) if x.id == "principal")
    assert e.maqueta == "ok" and e.pdf_intacto
    assert e.gates is None and e.revisor is None and e.nativo is None
    ok, mensajes = cerrar(v, P, "ZZ", LUEGO)
    assert not ok
    assert {"principal v1: gates no medido", "principal v1: revisor no medido",
            "principal v1: nativo no medido"} <= set(mensajes)


def test_gates_corregir_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("bono-2",))
    _producir(v, "bono-2", gates=False)
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "bono-2 v1: gates pide corregir" in mensajes


def test_sin_seccion_de_maqueta_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("principal",))
    raiz = pieza(v, P, "principal").raiz
    raiz.mkdir(parents=True, exist_ok=True)
    _pdf_principal(v).write_bytes(b"%PDF-1.7 sin maqueta")
    anotar_qc(raiz, 1, "gates", "ok", "sin hallazgos", AHORA)
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "principal v1: maqueta no medido" in mensajes
    assert any(m.startswith("principal v1: el PDF cambió después del QC o no tiene QC de maqueta") for m in mensajes)


def test_principal_sin_pdf_dice_que_es_lo_que_se_vende(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v, sin=("principal",))
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert "principal: sin PDF (es el producto que se vende)" in mensajes


def test_falta_oferta_no_lanza(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    (v / "productos" / P / "OFERTA.md").unlink()
    ok, mensajes = cerrar(v, P, "ZZ", AHORA)
    assert not ok
    assert mensajes == ["falta OFERTA.md: /modelar"]


def test_pdf_vigente_borrado_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _producir(v, "principal", 2)
    assert cerrar(v, P, "ZZ", AHORA)[0]
    _pdf_principal(v, 2).unlink()
    ok, mensajes = cerrar(v, P, "ZZ", LUEGO)
    assert not ok
    assert "principal: el PDF vigente v2 ya no existe" in mensajes
    assert _producto(v)[0]["entregable"]["es"]["principal"]["version"] == 2


def test_otro_pais_con_otra_moneda_no_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _estado(v, "modelado", "ZW")
    ok, mensajes = cerrar(v, P, "ZW", AHORA)
    assert not ok
    assert mensajes == ["ZW paga en USD y el entregable se hizo para ZZ en EUR: produce la versión de ZW"]
    assert _producto(v)[0]["paises"]["ZW"]["estado"] == "modelado"


def test_otro_pais_mismo_idioma_y_moneda_cierra(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    _estado(v, "modelado", "ZX")
    _editar(v, "ESCALERA", lambda m: m["paises"].update(ZX=m["paises"]["ZZ"]))
    ok, mensajes = cerrar(v, P, "ZX", AHORA)
    assert ok, mensajes
    assert _producto(v)[0]["paises"]["ZX"]["estado"] == "producido"


def test_historial_con_el_formato_de_avanzar_estado(tmp_path):
    v = _vault(tmp_path)
    _todo_apto(v)
    assert cerrar(v, P, "ZZ", AHORA)[0]
    historial = _producto(v)[0]["paises"]["ZZ"]["historial"]
    assert [set(h) for h in historial] == [{"de", "a", "fecha", "evidencia"}] * 2
    assert [(h["de"], h["a"]) for h in historial] == [("aprobado", "modelado"), ("modelado", "producido")]
