from dataclasses import replace
from datetime import date, datetime, timedelta

from ayudas import anuncio
from trovify.caza.cliente import SesionBloqueada
from trovify.caza.hueco import (
    HuecoPais,
    competencia_local,
    hay_hueco,
    motivo_hueco,
    original_presente,
)
from trovify.caza.modelo import ResultadoBusqueda
from trovify.caza.presupuesto import PresupuestoAgotado
from trovify.caza.senales import Medida

HOY = date(2026, 11, 10)
RO = "Fișe de terapie gata de printat, acces imediat după plată, pentru copii"
EN = "Ready to print therapy worksheets, instant access after payment for kids"


class ClienteFalso:
    def __init__(self, resultados):
        self.resultados = list(resultados)
        self.llamadas = []

    def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60):
        self.llamadas.append((pais, q, page_id, estado))
        r = self.resultados.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def url(i="x"):
    return f"https://www.facebook.com/ads/library/?q={i}"


def vacio():
    return ResultadoBusqueda("vacio", url(), 0, [], None, None)


def bloqueado():
    return ResultadoBusqueda("bloqueado", url(), None, [], "captcha", None)


def con(anuncios, completo=True):
    return ResultadoBusqueda("ok", url("y"), len(anuncios), anuncios, None, datetime(2026, 11, 10), completo)


def ad(lid, page, dias, texto=RO, pais="RO"):
    a = anuncio(lid, page, HOY - timedelta(days=dias), pais)
    return replace(a, texto=texto)


def test_cero_solo_tras_dos_intentos(umbrales):
    assert competencia_local(ClienteFalso([vacio(), vacio()]), ["fișe terapie", "kit terapie"], "RO", "ro", set(), umbrales).valor == 0
    una = competencia_local(ClienteFalso([vacio()]), ["fișe terapie"], "RO", "ro", set(), umbrales)
    assert una.valor is None and "2 intentos" in una.motivo


def test_bloqueo_no_es_cero(umbrales):
    m = competencia_local(ClienteFalso([vacio(), bloqueado()]), ["a b", "c d"], "RO", "ro", set(), umbrales)
    assert m.valor is None and "bloque" in m.motivo


def test_excepcion_del_cliente_no_es_cero(umbrales):
    for exc in (SesionBloqueada("x"), PresupuestoAgotado("y")):
        m = competencia_local(ClienteFalso([vacio(), exc]), ["a b", "c d"], "RO", "ro", set(), umbrales)
        assert m.valor is None and m.motivo.startswith("no medido")


def test_error_no_es_cero(umbrales):
    err = ResultadoBusqueda("error", url(), None, [], "fallo", None)
    m = competencia_local(ClienteFalso([vacio(), err]), ["a b", "c d"], "RO", "ro", set(), umbrales)
    assert m.valor is None


def test_cuenta_paginas_con_c7_en_idioma_local(umbrales):
    # pagina 1: 3 anuncios viejos en ro (competidor); pagina 2: 3 en inglés; pagina 3: 3 recientes;
    # pagina 4: 3 en ro pero excluida; pagina 5: solo 2.
    ads = (
        [ad(f"a{i}", "1", 10) for i in range(3)]
        + [ad(f"b{i}", "2", 10, EN) for i in range(3)]
        + [ad(f"c{i}", "3", 3) for i in range(3)]
        + [ad(f"d{i}", "4", 10) for i in range(3)]
        + [ad(f"e{i}", "5", 10) for i in range(2)]
    )
    cl = ClienteFalso([con(ads), vacio()])
    m = competencia_local(cl, ["a b", "c d"], "RO", "ro", {"4"}, umbrales, hoy=HOY)
    assert m.valor == 1 and not m.suelo


def test_anuncio_repetido_entre_frases_cuenta_una_vez(umbrales):
    ads = [ad(f"a{i}", "1", 10) for i in range(2)]
    cl = ClienteFalso([con(ads), con(ads + [ad("a9", "1", 10)])])
    m = competencia_local(cl, ["a b", "c d"], "RO", "ro", set(), umbrales, hoy=HOY)
    assert m.valor == 1


def test_lectura_incompleta_es_suelo(umbrales):
    m = competencia_local(ClienteFalso([con([ad("a", "1", 10)], completo=False), vacio()]), ["a b", "c d"], "RO", "ro", set(), umbrales, hoy=HOY)
    assert m.valor == 0 and m.suelo


def test_enlaces_y_busqueda_activa(umbrales):
    cl = ClienteFalso([vacio(), vacio()])
    competencia_local(cl, ["a b", "c d"], "RO", "ro", set(), umbrales)
    assert [c[3] for c in cl.llamadas] == ["active", "active"]


def test_hay_hueco(umbrales):
    assert hay_hueco(Medida(0), "sin_traducir", umbrales) is True
    assert hay_hueco(Medida(0), "traducido", umbrales) is False
    assert hay_hueco(Medida(2), "ausente", umbrales) is False
    assert hay_hueco(Medida(None, "no medido: x"), "ausente", umbrales) is None
    assert hay_hueco(Medida(0), "no_medido", umbrales) is None
    assert hay_hueco(Medida(0), "ausente_reciente", umbrales) is True


def test_competidor_mas_alla_de_la_primera_pagina_no_da_hueco(umbrales):
    sup = Medida(0, suelo=True)
    assert hay_hueco(sup, "sin_traducir", umbrales) is None
    assert "hay más anuncios que los leídos" in motivo_hueco(sup, "sin_traducir", umbrales)
    assert hay_hueco(Medida(5, suelo=True), "sin_traducir", umbrales) is False
    assert hay_hueco(sup, "traducido", umbrales) is False


def test_original_traducido(umbrales):
    cl = ClienteFalso([con([ad("a", "9", 50, EN), ad("b", "9", 2, RO)])])
    assert original_presente(cl, ["9"], "RO", "ro", HOY, umbrales) == "traducido"


def test_original_sin_traducir_y_reciente(umbrales):
    viejo = ClienteFalso([con([ad("a", "9", 40, EN), ad("b", "9", 2, EN)])])
    assert original_presente(viejo, ["9"], "RO", "ro", HOY, umbrales) == "sin_traducir"
    nuevo = ClienteFalso([con([ad("a", "9", 10, EN)])])
    assert original_presente(nuevo, ["9"], "RO", "ro", HOY, umbrales) == "ausente_reciente"


def test_original_ausente_y_no_medido(umbrales):
    assert original_presente(ClienteFalso([vacio()]), ["9"], "RO", "ro", HOY, umbrales) == "ausente"
    assert original_presente(ClienteFalso([bloqueado()]), ["9"], "RO", "ro", HOY, umbrales) == "no_medido"
    assert original_presente(ClienteFalso([SesionBloqueada("x")]), ["9"], "RO", "ro", HOY, umbrales) == "no_medido"
    # lectura incompleta sin traducido: no se puede afirmar «sin traducir»
    inc = ClienteFalso([con([ad("a", "9", 90, EN)], completo=False)])
    assert original_presente(inc, ["9"], "RO", "ro", HOY, umbrales) == "no_medido"


def test_texto_indetectable_del_original_es_desconocido(umbrales):
    cl = ClienteFalso([con([ad("a", "9", 90, "PDF")])])
    assert original_presente(cl, ["9"], "RO", "ro", HOY, umbrales) == "no_medido"
    mezcla = ClienteFalso([con([ad("a", "9", 90, EN), ad("b", "9", 60, "PDF")])])
    assert original_presente(mezcla, ["9"], "RO", "ro", HOY, umbrales) == "no_medido"
    joven = ClienteFalso([con([ad("a", "9", 90, EN), ad("b", "9", 2, "PDF")])])
    assert original_presente(joven, ["9"], "RO", "ro", HOY, umbrales) == "sin_traducir"


def test_original_sin_paginas_no_busca(umbrales):
    cl = ClienteFalso([])
    assert original_presente(cl, [], "RO", "ro", HOY, umbrales) == "no_medido"
    assert cl.llamadas == []


def test_competidor_de_idioma_indetectable_no_da_hueco(umbrales):
    dudosos = [ad(f"p{i}", "1", 10, "PDF") for i in range(3)]
    m = competencia_local(ClienteFalso([con(dudosos), vacio()]), ["a b", "c d"], "RO", "ro", set(), umbrales, hoy=HOY)
    assert m.valor is None and "no detectable" in m.motivo
    assert hay_hueco(m, "sin_traducir", umbrales) is None
    # con un competidor claro, la cuenta pasa a cota
    ads = [ad(f"a{i}", "2", 10) for i in range(3)] + dudosos
    m2 = competencia_local(ClienteFalso([con(ads), vacio()]), ["a b", "c d"], "RO", "ro", set(), umbrales, hoy=HOY)
    assert m2.valor == 1 and m2.suelo
    # dudosos insuficientes para llegar al mínimo: no cambian nada
    pocos = [ad("q1", "3", 10, "PDF"), ad("q2", "3", 10, "PDF")]
    m3 = competencia_local(ClienteFalso([con(pocos), vacio()]), ["a b", "c d"], "RO", "ro", set(), umbrales, hoy=HOY)
    assert m3.valor == 0 and not m3.suelo


def test_vacio_vacio_y_ok_bajo_el_minimo(umbrales):
    ads = [ad("a", "1", 10), ad("b", "1", 10)]
    m = competencia_local(ClienteFalso([vacio(), con(ads)]), ["a b", "c d"], "RO", "ro", set(), umbrales, hoy=HOY)
    assert m.valor == 0 and not m.suelo


def test_hueco_pais_no_busca_original_tras_parada(umbrales):
    from trovify.caza.hueco import hueco_pais

    cl = ClienteFalso([SesionBloqueada("x")])
    h = hueco_pais(cl, ["a b", "c d"], ["9"], "RO", "ro", set(), HOY, umbrales)
    assert len(cl.llamadas) == 1 and h.original == "no_medido" and h.hueco is None


def test_hueco_pais_dataclass():
    h = HuecoPais("RO", Medida(0), "ausente", True, ["u"])
    assert h.enlaces == ["u"]


def test_hueco_pais_reune_enlaces_y_motivo(umbrales):
    from trovify.caza.hueco import hueco_pais

    cl = ClienteFalso([vacio(), vacio(), con([ad("a", "9", 40, EN)])])
    h = hueco_pais(cl, ["a b", "c d"], ["9"], "RO", "ro", set(), HOY, umbrales)
    assert (h.competencia.valor, h.original, h.hueco) == (0, "sin_traducir", True)
    assert len(h.enlaces) == 3
