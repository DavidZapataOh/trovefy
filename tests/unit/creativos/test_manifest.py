"""manifest.csv, cierre de la tanda, aviso y rehacer tras un veto (plan 21, Tarea 11)."""

import csv
import hashlib
from decimal import Decimal

import pytest
from trovefy.aprobaciones.fuentes import BuzonNoDisponible
from trovefy.creativos import manifest, registro, whisper
from trovefy.creativos.estaticos import escribir_pieza
from trovefy.producto.medios import escribir_medio
from trovefy.tracking.modelo import PLANTILLA_UTM
from trovefy.vault import frontmatter

from .ejemplos import AHORA, LANDING, PAIS, P, crear_vault, jpeg, tanda_buena


def preparar_qa(vault, carpeta, ficha, cfg, *, revisor=True, nativo=True):
    piezas = manifest.piezas(ficha)
    for ad, tipo in piezas:
        if tipo == "video":
            escribir_medio(carpeta / "miniaturas" / f"{ad}.jpg", jpeg(1080, 1920), base=vault)
            whisper.anotar(carpeta, whisper.ResultadoWhisper(ad, "ok", Decimal("0.96"), "…", None), cfg, "apimart",
                           AHORA)
    hoja = carpeta / "qc" / "contactos-t1-v1.png"
    escribir_medio(hoja, b"\x89PNG", base=vault)
    h = registro.huella(carpeta, piezas)
    registro.anotar(carpeta, "automatica", {"huella": h, "estado": "ok"}, "", AHORA)
    if revisor:
        registro.anotar(carpeta, "revisor", {"huella": h, "estado": "ok", "hoja": "qc/contactos-t1-v1.png"}, "", AHORA)
    if nativo:
        registro.anotar(carpeta, "nativo", {"huella": h, "estado": "ok", "textos": "qc/textos-t1-v1.html"}, "", AHORA)


def cerrada(tmp_path, depositar=None):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    preparar_qa(vault, carpeta, ficha, cfg)
    avisos = []

    def dep(_v, datos, _a):
        avisos.append(datos)
        return "P-20261120-001"

    ruta, aviso = manifest.cerrar_tanda(vault, ctx, ficha, cfg, AHORA, depositar=depositar or dep)
    return vault, ctx, cfg, ficha, carpeta, ruta, aviso, avisos


def _filas(ruta):
    return list(csv.DictReader(ruta.read_text(encoding="utf-8").splitlines()))


def test_cabecera_exacta(tmp_path):
    *_, ruta, _, _ = cerrada(tmp_path)
    primera = ruta.read_text(encoding="utf-8").splitlines()[0]
    assert primera == ("id,nombre,uso,orden,angulo,angulo_es,hook,formato,tipo,archivo,sha256,miniatura,duracion_s,"
                       "voz,texto,titulo,descripcion,cta,url,idioma")


def test_sha_de_cada_fila_es_el_del_archivo(tmp_path):
    vault, *_, ruta, _, _ = cerrada(tmp_path)
    for f in _filas(ruta):
        assert not f["archivo"].startswith("/") and ".." not in f["archivo"]
        assert hashlib.sha256((vault / f["archivo"]).read_bytes()).hexdigest() == f["sha256"]
        assert f["nombre"].startswith(f"{f['id']} G1 ")


def test_url_con_plantilla_literal(tmp_path):
    *_, ruta, _, _ = cerrada(tmp_path)
    assert {f["url"] for f in _filas(ruta)} == {LANDING + "?" + PLANTILLA_UTM}


def test_5_test_5_reserva(tmp_path):
    *_, ruta, _, _ = cerrada(tmp_path)
    usos = [f["uso"] for f in _filas(ruta)]
    assert usos.count("test") == 5 and usos.count("reserva") == 5
    assert [f["orden"] for f in _filas(ruta)] == [str(n) for n in range(1, 11)]


def test_no_cierra_sin_revisor(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    preparar_qa(vault, carpeta, ficha, cfg, revisor=False)
    with pytest.raises(manifest.TandaNoCierra, match="revisor"):
        manifest.cerrar_tanda(vault, ctx, ficha, cfg, AHORA, depositar=lambda *_a: "x")


def test_no_cierra_si_la_huella_cambio(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    preparar_qa(vault, carpeta, ficha, cfg)
    escribir_pieza(vault, carpeta, "AD01", jpeg() + b"\x00", "jpg")  # otro byte tras el ok
    with pytest.raises(manifest.TandaNoCierra):
        manifest.cerrar_tanda(vault, ctx, ficha, cfg, AHORA, depositar=lambda *_a: "x")


def test_cierra_y_fusiona_producto_sin_tocar_estado(tmp_path):
    vault, *_ = cerrada(tmp_path)
    meta, _ = frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")
    pais = meta["paises"][PAIS]
    assert pais["estado"] == "listo" and pais["landing"]["url"] == LANDING
    c = pais["creativos"]
    assert c["vigente"] == "t1" and c["tandas"]["t1"]["cerrada"] and len(c["tandas"]["t1"]["test"]) == 5
    assert c["tandas"]["t1"]["manifest_sha256"] == hashlib.sha256(
        (vault / c["tandas"]["t1"]["manifest"]).read_bytes()).hexdigest()


def test_alerta_con_adjunto(tmp_path):
    *_, aviso, avisos = cerrada(tmp_path)
    assert aviso == "aviso enviado: P-20261120-001"
    a = avisos[0]
    assert a["tipo"] == "alerta" and a["origen"] == "/creativos" and a["nivel"] == "info"
    assert a["adjuntos"] == [f"productos/{P}/creativos/{PAIS}/t1/qc/contactos-t1-v1.png"]
    assert "5 al test, 5 de reserva" in a["texto"]
    from trovefy_ejecutor.esquema import cargar_propuesta
    cargar_propuesta({**a, "id": "P-20261120-001", "creada": AHORA.isoformat(), "version": 1})  # el buzón la acepta


def test_sin_buzon_cierra_y_avisa(tmp_path):
    def sin(*_a):
        raise BuzonNoDisponible("STOP del cerebro activo")

    *_, ruta, aviso, _ = cerrada(tmp_path, depositar=sin)
    assert ruta.is_file() and aviso.startswith("aviso no enviado: STOP")


def test_rehacer_abre_y_guarda_motivo_literal(tmp_path):
    vault, *_ = cerrada(tmp_path)
    motivo = "en el segundo tres no me gustó la letra"
    manifest.rehacer(vault, P, PAIS, "t1", ["AD03"], motivo, AHORA)
    meta, _ = frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")
    t1 = meta["paises"][PAIS]["creativos"]["tandas"]["t1"]
    assert t1["cerrada"] is None and t1["rehacer"][-1]["motivo"] == motivo and t1["rehacer"][-1]["ads"] == ["AD03"]
    assert f"«{motivo}»" in (vault / "productos" / P / "creativos" / PAIS / "t1" / "TANDA.md").read_text("utf-8")
