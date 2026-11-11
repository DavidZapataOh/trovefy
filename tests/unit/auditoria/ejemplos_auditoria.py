"""Datos fijos de las pruebas de /auditar (sin paquete de tests: ``from ejemplos import ...``).

Oferta con su enlace de la Biblioteca y precio 13,90 EUR; RO con hueco y precio soportable 1;
IT con hueco y 0,5; FR con el original ya traducido (no tirar).
"""

import pathlib

from trovify.auditoria.paises import PaisAuditado, no_tirar, puntuar_pais
from trovify.caza.hueco import HuecoPais
from trovify.caza.senales import Medida
from trovify.config.umbrales import cargar

_UMBRALES = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml"
_BIB = "https://www.facebook.com/ads/library/?active_status=active&ad_type=all&country={pais}&media_type=all"
PAGINA = "100000000000001"


def link_pagina(pais: str) -> str:
    return _BIB.format(pais=pais) + f"&search_type=page&view_all_page_id={PAGINA}"


def link_frase(pais: str, frase: str) -> str:
    return _BIB.format(pais=pais) + f"&q={frase.replace(' ', '+')}&search_type=keyword_unordered"


def oferta_ejemplo() -> dict:
    """Frontmatter de ``wiki/ofertas/o-ejemplo.md`` con el contrato del plan 07."""
    return {
        "tipo": "oferta",
        "fecha": "2026-11-09",
        "fuente": link_pagina("ES"),
        "oferta_id": "o-ejemplo",
        "page_ids": [PAGINA],
        "original_page_id": PAGINA,
        "origen": "palabra",
        "checkout": "https://tienda.example/checkout",
        "gateway": "hotmart",
        "dominio": "tienda.example",
        "paises": {
            "ES": {
                "c8": 15,
                "c7": 16,
                "total": 32,
                "edad_max": 40,
                "link_biblioteca": link_pagina("ES"),
                "pagina": f"https://www.facebook.com/{PAGINA}",
                "estado": "B",
                "motivo": "nota 62,4 < 70 para A; sin hueco comprobado",
                "nota": 62.4,
                "cota_inferior": [],
                "fecha": "2026-11-09",
            }
        },
        "idiomas": ["es"],
        "precio": 13.9,
        "moneda": "EUR",
        "estado": "B",
        "motivo": "nota 62,4 < 70 para A; sin hueco comprobado",
        "primera_vez": "2026-11-09",
        "ultima_vez": "2026-11-09",
        "banderas": [],
    }


def _pais(pais, comp, original, hueco, precio_s, enlaces, banda=(11.9, 15.9),
          fuente="vídeos: 11,90–15,90 €") -> PaisAuditado:
    u = cargar(_UMBRALES)
    h = HuecoPais(pais, Medida(comp), original, hueco, enlaces)
    ps = Medida(precio_s)
    nota, desglose = puntuar_pais(h, ps, u)
    return PaisAuditado(pais, h, Medida(13.9), ps, nota, desglose, no_tirar(h), banda, fuente)


def paises_ejemplo() -> list[PaisAuditado]:
    return [
        _pais("RO", 0, "sin_traducir", True, 1.0,
              [link_frase("RO", "fise terapie"), link_frase("RO", "kit terapie"), link_pagina("RO")]),
        _pais("IT", 0, "ausente", True, 0.5,
              [link_frase("IT", "schede terapia"), link_frase("IT", "kit terapia"), link_pagina("IT")],
              banda=(15.9, 19.9), fuente="banda de ejemplo"),  # 13,90 € queda a media banda: 0,5
        _pais("FR", 0, "traducido", False, 1.0,
              [link_frase("FR", "fiches therapie"), link_frase("FR", "kit therapie"), link_pagina("FR")]),
    ]
