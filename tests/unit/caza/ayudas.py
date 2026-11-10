"""Ayudas compartidas de las pruebas de la caza (el repo no usa paquete de tests: ``from ayudas import ...``)."""

from datetime import date

from trovify.caza.destino import Destino
from trovify.caza.modelo import AnuncioBiblioteca

URL_TIENDA = "https://a.impultienda.ar/"


def anuncio(lid, page, inicio: date, pais="RO", destino=URL_TIENDA, activo=True) -> AnuncioBiblioteca:
    return AnuncioBiblioteca(
        lid, page, f"p{page}", inicio, None, activo, ("facebook",), "texto", None, destino, None, None, pais
    )


def destino_impultienda() -> Destino:
    return Destino(
        URL_TIENDA, URL_TIENDA, "impultienda", "https://a.impultienda.ar/checkout",
        13.9, "EUR", None, False, False, "ok", None,
    )
