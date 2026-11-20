"""Voz en todos los vídeos con APIMart o ElevenLabs, con coste aprobado (plan 21, Tarea 6)."""

from decimal import Decimal

import pytest
from trovefy.apimart.gasto import leer_costes
from trovefy.apimart.voz import precio_tts
from trovefy.creativos import coste, escenas, voz
from trovefy.creativos.config import RELATIVA, cargar_config
from trovefy.creativos.contexto import cargar_contexto, ruta_tanda
from trovefy.creativos.guion import validar_video
from trovefy.producto.medios import leer_manifiesto

from .ejemplos import AHORA, PAIS, P, crear_vault, guion_video
from .falsos import wav


def ajustar(vault, *pares):
    ruta = vault / RELATIVA
    texto = ruta.read_text(encoding="utf-8")
    for a, b in pares:
        assert a in texto, a
        texto = texto.replace(a, b)
    ruta.write_text(texto, encoding="utf-8")
    return cargar_config(vault)


TTS = ('precio_tts_usd_1000_caracteres: {valor: null', 'precio_tts_usd_1000_caracteres: {valor: "0.015"')
EL = [("plan: {valor: null", "plan: {valor: Starter"), ("coste_mensual_usd: {valor: null", 'coste_mensual_usd: {valor: "6"'),
      ("caracteres_mes: {valor: null", "caracteres_mes: {valor: 30000"),
      ("voz_id: {valor: null", "voz_id: {valor: abcdefgh12345678")]


@pytest.fixture
def base(tmp_path):
    vault = crear_vault(tmp_path)
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    carpeta.mkdir(parents=True)
    return vault, carpeta


def _aprobar(vault, est=None, usd="6.00"):
    est = est or coste.Estimacion((coste.Partida("voz de APIMart", 1000, "carácter", Decimal("0.000015"), "p"),))
    coste.aprobar(vault, P, PAIS, "t1", est, Decimal(usd), "sí, dale", AHORA)


def _guion(cfg):
    return validar_video("AD09", guion_video("claymation"), cfg)


def _generar(vault, carpeta, cfg, precio, llamadas, **kw):
    ctx = cargar_contexto(vault, P, PAIS)
    d = escenas.destino(vault, ctx, cfg, "t1")

    def apimart(cuerpo):
        llamadas.append(("apimart", cuerpo))
        return wav()

    def eleven(v, cuerpo):
        llamadas.append(("elevenlabs", cuerpo))
        return b"ID3" + b"\x00" * 32

    return voz.generar(vault, P, d, carpeta, _guion(cfg), precio=precio, voz=kw.pop("voz", "nova"),
                       llamar_apimart=apimart, llamar_elevenlabs=eleven, ahora=lambda: AHORA, **kw)


def test_sin_precio_tts_pasa_a_elevenlabs(base):
    vault, carpeta = base
    cfg = ajustar(vault, *EL)
    est = coste.Estimacion((coste.Partida("voz ElevenLabs", 400, "carácter", Decimal("0.0002"), "plan"),))
    _aprobar(vault, est)
    precio, motivo = voz.elegir_proveedor(vault, cfg, carpeta)
    assert motivo is None and precio.proveedor == "elevenlabs"
    assert precio.usd_por_caracter == Decimal(6) / 30000


def test_sin_ningun_proveedor_no_medido(base):
    vault, carpeta = base
    precio, motivo = voz.elegir_proveedor(vault, cargar_config(vault), carpeta)
    assert precio is None and motivo.startswith("no medido")


def test_elevenlabs_sin_aprobacion_no_envia(base):
    vault, carpeta = base
    cfg = ajustar(vault, *EL)
    _aprobar(vault)  # aprobado sin ElevenLabs
    precio, motivo = voz.elegir_proveedor(vault, cfg, carpeta)
    assert precio is None and "ElevenLabs sin aprobar" in motivo


def test_precio_forma_rara_none():
    assert precio_tts("gpt-4o-mini-tts", None, "x") is None
    assert precio_tts(None, Decimal("0.01"), "x") is None
    assert precio_tts("gpt-4o-mini-tts", Decimal(5), "x") is None  # > 1 USD por 1000 letras: dato corrupto
    assert precio_tts("gpt-4o-mini-tts", Decimal("0.015"), "x").usd_por_caracter == Decimal("0.000015")


def test_sin_aprobacion_no_envia(base):
    vault, carpeta = base
    cfg = ajustar(vault, TTS)
    llamadas = []
    precio, _ = voz.elegir_proveedor(vault, cfg, carpeta)
    r = _generar(vault, carpeta, cfg, precio, llamadas)
    assert not llamadas and all(e.estado == "detenido" and "aprobar-coste" in e.motivo for e in r)


def test_tope_para_voz(base):
    vault, carpeta = base
    cfg = ajustar(vault, TTS)
    _aprobar(vault, usd="6.00")
    coste.fijar_tope(vault, P, PAIS, "t1", Decimal("0.01"), "un centavo", AHORA)
    caro = voz.PrecioVoz("apimart", "gpt-4o-mini-tts", Decimal("0.001"), "p")
    llamadas = []
    r = _generar(vault, carpeta, cfg, caro, llamadas, depositar=lambda *_a: "P-1")
    assert not llamadas and r[0].estado == "detenido" and r[0].motivo.startswith("tope")


def test_no_reenvia_enviada(base):
    vault, carpeta = base
    cfg = ajustar(vault, TTS)
    _aprobar(vault)
    precio, _ = voz.elegir_proveedor(vault, cfg, carpeta)
    llamadas = []

    def falla(*_a):
        raise OSError("sin respuesta")

    ctx = cargar_contexto(vault, P, PAIS)
    r = voz.generar(vault, P, escenas.destino(vault, ctx, cfg, "t1"), carpeta, _guion(cfg), precio=precio,
                    voz="nova", llamar_apimart=falla, ahora=lambda: AHORA, solo_gancho=True)
    assert r[0].estado == "pendiente"
    r2 = _generar(vault, carpeta, cfg, precio, llamadas, solo_gancho=True)
    assert not llamadas and r2[0].estado == "pendiente"  # el POST sin respuesta no se reenvía solo


def test_solo_gancho_envia_primera_frase(base):
    vault, carpeta = base
    cfg = ajustar(vault, TTS)
    _aprobar(vault)
    precio, _ = voz.elegir_proveedor(vault, cfg, carpeta)
    llamadas = []
    r = _generar(vault, carpeta, cfg, precio, llamadas, solo_gancho=True)
    assert [e.estado for e in r] == ["completada"] and len(llamadas) == 1
    assert llamadas[0][1]["input"] == "Не можеш да заспиш вечер?" and llamadas[0][1]["model"] == "gpt-4o-mini-tts"


def test_audio_registrado_con_su_proveedor(base):
    vault, carpeta = base
    cfg = ajustar(vault, TTS)
    _aprobar(vault)
    precio, _ = voz.elegir_proveedor(vault, cfg, carpeta)
    llamadas = []
    r = _generar(vault, carpeta, cfg, precio, llamadas)
    assert all(e.estado == "completada" for e in r) and len(r) == 6  # gancho, 4 segmentos y cierre
    m = leer_manifiesto(carpeta / "fuente", verificar=True)
    assert m["voz-ad09-g"]["origen"] == "apimart" and m["voz-ad09-g"]["archivo"].endswith(".wav")
    assert any(f.estado == "completada" and f.pieza == "voz" for f in leer_costes(vault, P, carpeta))
    assert len(voz.pistas(carpeta, _guion(cfg))) == 6
    # lo ya hecho con el mismo texto no se repite
    assert all(e.estado == "omitida" for e in _generar(vault, carpeta, cfg, precio, llamadas))


def test_elige_voz_por_similitud():
    assert voz.elegir_voz({"nova": Decimal("0.91"), "shimmer": Decimal("0.95")}) == "shimmer"
    assert voz.elegir_voz({"nova": Decimal("0.93"), "shimmer": None}) == "nova"
    assert voz.elegir_voz({"nova": None}) is None
