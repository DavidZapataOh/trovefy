"""APIMart para las tandas: destino de lote, libro de la tanda, coste aprobado y tope (plan 21, Tarea 4)."""

from datetime import date
from decimal import Decimal

import pytest
from trovefy.apimart.gasto import leer_costes
from trovefy.apimart.lote import MOTIVO_STOP, destino_entregable
from trovefy.apimart.precios import Precio
from trovefy.creativos import coste, escenas
from trovefy.creativos import tanda as tanda_md
from trovefy.creativos.config import cargar_config
from trovefy.creativos.contexto import cargar_contexto, ruta_tanda
from trovefy.creativos.guion import Escena
from trovefy.producto.config import cargar_config as cargar_config_producto
from trovefy.producto.config import iniciar_config as iniciar_producto
from trovefy.producto.medios import leer_manifiesto

from .ejemplos import AHORA, PAIS, P, crear_vault
from .falsos import CRED, APIMartFalso, explota, publico

PRECIO = Precio("gpt-image-2", "1k", Decimal("0.0085"), "prueba", date(2026, 11, 20))
ESC = [Escena("e01", "mujer que duerme en calma, luz cálida", "4:5", ("mockup",)),
       Escena("e02", "mesa de noche con libreta", "9:16", ())]


@pytest.fixture
def base(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg = cargar_contexto(vault, P, PAIS), cargar_config(vault)
    ruta_tanda(vault, P, PAIS, "t1").mkdir(parents=True)
    return vault, ctx, cfg


def _aprobar(vault, usd="1.00"):
    est = coste.Estimacion((coste.Partida("escenas de APIMart", 2, "imagen", Decimal("0.0085"), "prueba"),))
    coste.aprobar(vault, P, PAIS, "t1", est, Decimal(usd), "sí, adelante con eso", AHORA)


def _generar(vault, ctx, cfg, abrir, **kw):
    return escenas.generar(vault, ctx, cfg, "t1", ESC, cred=CRED, precio=PRECIO, abrir=abrir, abrir_publico=publico,
                           ahora=lambda: AHORA, dormir=lambda _s: None, depositar=kw.pop("depositar", explota), **kw)


def test_sin_destino_igual_que_antes(tmp_path):
    vault = crear_vault(tmp_path)
    iniciar_producto(vault)
    d = destino_entregable(vault, P, cargar_config_producto(vault))
    assert d.raiz_libro == vault / "productos" / P / "entregable" and d.skill == "/producto"
    assert d.raiz_medios("bono-1") == vault / "productos" / P / "entregable" / "bonos" / "bono-1"


def test_sin_aprobacion_de_coste_no_envia(base):
    vault, ctx, cfg = base
    r = _generar(vault, ctx, cfg, explota)
    assert r.detenido and "aprobar-coste" in r.detenido and not r.generadas


def test_destino_tanda_escribe_en_la_tanda(base):
    vault, ctx, cfg = base
    _aprobar(vault)
    falso = APIMartFalso()
    r = _generar(vault, ctx, cfg, falso)
    assert r.generadas == ("e01", "e02"), r
    carpeta = ruta_tanda(vault, P, PAIS, "t1")
    manifiesto = leer_manifiesto(carpeta / "fuente")
    assert manifiesto["e01"]["origen"] == "apimart" and manifiesto["mockup"]["origen"] == "propio"
    assert len(leer_costes(vault, P, carpeta)) > 0
    assert leer_costes(vault, P) == []  # el libro del entregable no se toca


def test_simular_no_llama(base):
    vault, ctx, cfg = base
    r = _generar(vault, ctx, cfg, explota, simular=True)
    assert r.detenido is None and not r.generadas


def test_stop_no_envia(base):
    vault, ctx, cfg = base
    _aprobar(vault)
    (vault / ".trovefy").mkdir(exist_ok=True)
    (vault / ".trovefy" / "STOP").write_text("")
    assert _generar(vault, ctx, cfg, explota).detenido == MOTIVO_STOP


def test_tope_tanda_para(base):
    vault, ctx, cfg = base
    _aprobar(vault, "6.00")
    caro = Precio("gpt-image-2", "1k", Decimal("0.90"), "prueba", date(2026, 11, 20))
    coste.fijar_tope(vault, P, PAIS, "t1", Decimal("0.50"), "pon medio dólar", AHORA)
    alertas = []

    def depositar(_v, datos, _a):
        alertas.append(datos)
        return "P-20261120-001"

    r = escenas.generar(vault, ctx, cfg, "t1", ESC, cred=CRED, precio=caro, abrir=explota, abrir_publico=publico,
                        ahora=lambda: AHORA, dormir=lambda _s: None, depositar=depositar)
    assert r.detenido.startswith("tope") and not r.generadas
    assert alertas and alertas[0]["origen"] == "/creativos"


def test_tope_renovacion(base):
    vault, _, cfg = base
    carpeta = ruta_tanda(vault, P, PAIS, "t2")
    carpeta.mkdir()
    tanda_md.actualizar(carpeta, {"tipo": "renovacion"}, None, AHORA)
    tope, motivo = coste.limite(vault, P, PAIS, "t2", cfg)
    assert tope == Decimal("2.00") and motivo  # sin aprobar: no se envía
    coste.fijar_tope(vault, P, PAIS, "renovacion", Decimal("2.00"), "vale, dos dólares cada renovación", AHORA)
    assert coste.limite(vault, P, PAIS, "t2", cfg) == (Decimal("2.00"), None)


def test_tope_subido_con_cita(base):
    vault, _, cfg = base
    assert coste.tope_vigente(vault, P, PAIS, "t1", cfg) == Decimal("6.00")
    coste.fijar_tope(vault, P, PAIS, "t1", Decimal("7.50"), "súbelo a 7,50", AHORA)
    assert coste.tope_vigente(vault, P, PAIS, "t1", cfg) == Decimal("7.50")
    with pytest.raises(ValueError):
        coste.fijar_tope(vault, P, PAIS, "t1", Decimal(8), "  ", AHORA)


def test_aprobar_con_no_medido_falla(base):
    vault, _, _ = base
    est = coste.Estimacion((coste.Partida("voz de APIMart", 400, "carácter", None, "no medido"),))
    with pytest.raises(ValueError, match="sin medir"):
        coste.aprobar(vault, P, PAIS, "t1", est, Decimal(6), "sí", AHORA)
