import io
import urllib.error
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from trovefy import trm as trm_mod
from trovefy.trm import Trm, cop_a_usd_centavos, trm_del_dia, usd_centavos_a_cop

FIX = Path(__file__).parent.parent / "fixtures" / "trm"


class _Resp(io.BytesIO):
    def __init__(self, datos: bytes, url: str = "https://www.datos.gov.co/resource/32sa-8pi3.json"):
        super().__init__(datos)
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fijo(nombre):
    def abrir(url, timeout=15):
        return _Resp((FIX / nombre).read_bytes())

    return abrir


def cuerpo(datos: bytes, url="https://www.datos.gov.co/resource/32sa-8pi3.json"):
    return lambda u, timeout=15: _Resp(datos, url)


def explota(url, timeout=15):
    raise AssertionError("no debe tocar la red")


def test_trm_fin_de_semana_usa_el_rango(tmp_path):
    t = trm_del_dia(tmp_path, date(2026, 11, 8), abrir=fijo("fin-de-semana.json"))
    assert t.cop_por_usd == Decimal("3237.83") and t.vigente(date(2026, 11, 8))
    assert "vigente 2026-11-07 a 2026-11-09" in t.etiqueta(date(2026, 11, 8))
    assert (tmp_path / "data/cache/trm-2026-11-08.json").exists()


def test_etiqueta_vigente_formato_es():
    t = Trm(Decimal("3297.07"), date(2026, 11, 11), date(2026, 11, 12))
    assert t.etiqueta(date(2026, 11, 11)) == (
        "TRM 3.297,07 COP/USD · Banco de la República · vigente 2026-11-11 a 2026-11-12"
    )


def test_trm_sin_publicar_usa_ultima_con_fecha(tmp_path):
    t = trm_del_dia(tmp_path, date(2026, 11, 13), abrir=fijo("2026-11-11.json"))
    assert not t.vigente(date(2026, 11, 13))
    assert t.etiqueta(date(2026, 11, 13)) == (
        "TRM 3.297,07 COP/USD · Banco de la República · última publicada, del 2026-11-11 "
        "(sin TRM para 2026-11-13)"
    )
    assert not (tmp_path / "data/cache/trm-2026-11-13.json").exists()


def test_trm_cache_del_dia(tmp_path):
    trm_del_dia(tmp_path, date(2026, 11, 11), abrir=fijo("2026-11-11.json"))
    assert trm_del_dia(tmp_path, date(2026, 11, 11), abrir=explota).cop_por_usd == Decimal("3297.07")


def test_consulta_usa_where_y_limit(tmp_path):
    vistas = []

    def abrir(url, timeout=15):
        vistas.append(url)
        return _Resp((FIX / "2026-11-11.json").read_bytes())

    trm_del_dia(tmp_path, date(2026, 11, 11), abrir=abrir)
    assert "32sa-8pi3.json?" in vistas[0] and "2026-11-11T00%3A00%3A00.000" in vistas[0]
    assert "DESC" in vistas[0] and "limit=1" in vistas[0]


FILA = '{"valor":"%s","unidad":"%s","vigenciadesde":"%s","vigenciahasta":"%s"}'


@pytest.mark.parametrize(
    "datos",
    [
        b"[]",
        b"{}",
        b"no es json",
        ("[" + FILA % ("abc", "COP", "2026-11-11T00:00:00.000", "2026-11-12T00:00:00.000") + "]").encode(),
        ("[" + FILA % ("3297.07", "USD", "2026-11-11T00:00:00.000", "2026-11-12T00:00:00.000") + "]").encode(),
        ("[" + FILA % ("0", "COP", "2026-11-11T00:00:00.000", "2026-11-12T00:00:00.000") + "]").encode(),
        ("[" + FILA % ("999.99", "COP", "2026-11-11T00:00:00.000", "2026-11-12T00:00:00.000") + "]").encode(),
        ("[" + FILA % ("10000.01", "COP", "2026-11-11T00:00:00.000", "2026-11-12T00:00:00.000") + "]").encode(),
        ("[" + FILA % ("NaN", "COP", "2026-11-11T00:00:00.000", "2026-11-12T00:00:00.000") + "]").encode(),
        ("[" + FILA % ("3297.07", "COP", "ayer", "2026-11-12T00:00:00.000") + "]").encode(),
        b'[{"valor":3297.07,"unidad":"COP"}]',
        b"x" * 1_000_001,
    ],
)
def test_trm_respuesta_rara_es_none(tmp_path, datos):
    assert trm_del_dia(tmp_path, date(2026, 11, 11), abrir=cuerpo(datos)) is None
    assert not (tmp_path / "data/cache").exists() or not list((tmp_path / "data/cache").iterdir())


def test_trm_sin_red_es_none(tmp_path):
    def abrir(url, timeout=15):
        raise urllib.error.URLError("caída")

    assert trm_del_dia(tmp_path, date(2026, 11, 11), abrir=abrir) is None


def test_trm_redireccion_a_otro_host_es_none(tmp_path):
    datos = (FIX / "2026-11-11.json").read_bytes()
    assert trm_del_dia(tmp_path, date(2026, 11, 11), abrir=cuerpo(datos, "https://evil.example/x")) is None


def test_abrir_seguro_rechaza_http():
    from trovefy.trm import _abrir_seguro

    with pytest.raises(ValueError):
        _abrir_seguro("http://www.datos.gov.co/x")


def test_conversion_redondeo():
    t = Trm(Decimal("3297.07"), date(2026, 11, 11), date(2026, 11, 12))
    assert cop_a_usd_centavos(Decimal(83700), t) == 2539
    assert usd_centavos_a_cop(28000, t) == Decimal(923179)
    assert not hasattr(trm_mod, "a_usd")  # sin conversión en float: el dinero va en enteros/Decimal


def test_trm_demasiado_vieja_es_none(tmp_path):
    # la fila vigente hasta el 2026-11-12; 7 días después aún vale, 8 no
    assert trm_del_dia(tmp_path, date(2026, 11, 19), abrir=fijo("2026-11-11.json")) is not None
    assert trm_del_dia(tmp_path, date(2026, 11, 20), abrir=fijo("2026-11-11.json")) is None
