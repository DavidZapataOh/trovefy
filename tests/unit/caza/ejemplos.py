"""Ejecuciones de caza construidas a mano para los *golden files* (datos ficticios y saneados).

Se importan sin paquete de tests: ``from ejemplos import ejecucion_ejemplo``.
"""

import pathlib
from dataclasses import replace
from datetime import date, timedelta

from ayudas import anuncio, destino_impultienda
from trovefy.caza.biblioteca import url_biblioteca
from trovefy.caza.destino import Destino
from trovefy.caza.filtros import Descarte
from trovefy.caza.hueco import HuecoPais
from trovefy.caza.nota import calcular_nota, decidir
from trovefy.caza.oferta import Oferta
from trovefy.caza.salida import Consulta, Ejecucion, ResultadoOferta
from trovefy.caza.senales import Medida, Senales, calcular_senales
from trovefy.config.mercados import cargar as cargar_mercados
from trovefy.config.umbrales import cargar

_CONFIG = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config"
U = cargar(_CONFIG / "umbrales.yaml")
MERCADOS = cargar_mercados(_CONFIG / "mercados.yaml")
TEXTO_RO = "Caiet de exerciții pentru copii: descarcă fișele în format PDF și învață acasă cu ei în fiecare zi."
HOY = date(2026, 11, 10)
P_ORIGINAL, P_COPIA, P_TIENDA, P_CAIDA = (
    "100000000000001", "100000000000002", "100000000000003", "100000000000004",
)
FRASE = "caiet de exercitii"


def _nm(motivo: str) -> Medida:
    return Medida(None, f"no medido: {motivo}")


def _anuncios(page: str, n: int, dias: int, inicio_id: int):
    return [replace(anuncio(str(inicio_id + i), page, HOY - timedelta(days=dias)), texto=TEXTO_RO)
            for i in range(n)]


def _resultado_b() -> ResultadoOferta:
    # 32 anuncios activos en RO: 15 con 8+ días, 16 con 7+ días (supervivencia 0,5).
    anuncios = (
        _anuncios(P_ORIGINAL, 10, 40, 900001) + _anuncios(P_ORIGINAL, 10, 2, 900011)
        + _anuncios(P_COPIA, 5, 21, 900021) + _anuncios(P_COPIA, 1, 7, 900026)
        + _anuncios(P_COPIA, 6, 1, 900027)
    )
    oferta = Oferta(
        "o-ejemplo", "a.impultienda.ar/checkout", [P_ORIGINAL, P_COPIA], anuncios, destino_impultienda(),
        origen="original", original_page_id=P_ORIGINAL, copias=[P_COPIA],
    )
    oferta.destinos = [oferta.destino]
    # Lectura completa con el total exacto de Meta: todas las señales salen de los anuncios de arriba.
    s = calcular_senales(oferta, "RO", HOY, [], None, 32, True, total_meta=32, umbrales=U, mercados=MERCADOS)
    nota = calcular_nota(s, U)
    comp = _nm("solo hubo 1 de los 2 intentos con frases distintas que hacen falta para confirmar que no hay competencia")
    huecos = [HuecoPais("RO", comp, "no_medido", None,
                        [url_biblioteca("RO", q="caiet de lucru")], comp.motivo)]
    decision, motivo = decidir(nota, s.c8, "tomi", None, None, U, c7=s.c7)
    return ResultadoOferta(
        oferta, "RO", s, nota, decision, motivo, None, huecos,
        url_biblioteca("RO", q=FRASE), dia=HOY, total_meta=32, completo=True,
    )


def _resultado_descartado() -> ResultadoOferta:
    anuncios = _anuncios(P_TIENDA, 3, 12, 900101) + _anuncios(P_TIENDA, 1, 3, 900104)
    destino = Destino("https://tienda.example/", "https://tienda.example/", None, None, None, None,
                      None, False, False, "ok", None)
    oferta = Oferta("o-tienda-ejemplo", "tienda.example", [P_TIENDA], anuncios, destino, destinos=[destino])
    s = Senales(
        c8=Medida(3), c7=Medida(3), total=Medida(4), supervivencia=Medida(0.75),
        escalonado_semanas=Medida(1), edad_max_dias=Medida(12),
        vida_mediana_dias=_nm("sin búsqueda de inactivos"), crecimiento_7d=_nm("primera caza"),
        expansion=Medida(2), duplicacion=_nm("la Biblioteca no informa collation_count"),
        alcance_ue=_nm("requiere /ads_archive (paso 15)"),
    )
    descarte = Descarte("producto_fisico", "señales de producto físico o retail: envío gratis, talla concreta")
    nota = calcular_nota(s, U)
    decision, motivo = decidir(nota, s.c8, "tomi", None, descarte, U, c7=s.c7)
    return ResultadoOferta(
        oferta, "RO", s, nota, decision, motivo, descarte, [],
        url_biblioteca("RO", q=FRASE), dia=HOY, total_meta=4, completo=True,
    )


def ejecucion_ejemplo() -> Ejecucion:
    b, d = _resultado_b(), _resultado_descartado()
    return Ejecucion(
        HOY, "europa", "nicho", "tomi", busquedas=6, bloqueos=0, vacios=1, errores=[],
        resultados=[b, d], pendientes=2,
        via={"firecrawl": 5, "playwright": 1}, creditos=5,
        consultas=[
            Consulta(FRASE, "RO", 48, url_biblioteca("RO", q=FRASE), ["o-ejemplo", "o-tienda-ejemplo"]),
            Consulta("fise de lucru copii", "RO", 0, url_biblioteca("RO", q="fise de lucru copii"), []),
        ],
        vara=("C8", 15),
    )


def ejecucion_fuente_caida() -> Ejecucion:
    caida = _nm("búsqueda bloqueada (captcha)")
    s = Senales(
        c8=caida, c7=caida, total=caida, supervivencia=caida, escalonado_semanas=caida,
        edad_max_dias=caida, vida_mediana_dias=caida, crecimiento_7d=caida, expansion=caida,
        duplicacion=caida, alcance_ue=caida, nuevos=caida, parados=caida,
    )
    oferta = Oferta("o-caida-ejemplo", f"pagina:{P_CAIDA}", [P_CAIDA], [], None)
    nota = calcular_nota(s, U)
    huecos = [HuecoPais("RO", caida, "no_medido", None, [], caida.motivo)]
    decision, motivo = decidir(nota, s.c8, "tomi", None, None, U, c7=s.c7)
    r = ResultadoOferta(
        oferta, "RO", s, nota, decision, motivo, None, huecos,
        url_biblioteca("RO", page_id=P_CAIDA), dia=HOY, total_meta=None, completo=False,
    )
    return Ejecucion(
        HOY, "europa", "nicho", "tomi", busquedas=5, bloqueos=1, vacios=0,
        errores=[f"RO «{FRASE}»: acceso bloqueado por Meta (captcha); se paró la caza"],
        resultados=[r], pendientes=0,
        via={"firecrawl": 5}, creditos=None,
        consultas=[Consulta(FRASE, "RO", None, url_biblioteca("RO", q=FRASE), [])],
        vara=("C8", 15),
    )
