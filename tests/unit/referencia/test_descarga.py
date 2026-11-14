"""Guarda anti-SSRF: sin red, con resolver y conexión inyectados."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from trovefy.referencia.descarga import (
    DescargaRechazada,
    descargar_medio,
    ip_publica,
    url_permitida,
)

URL = "https://video.xx.fbcdn.net/v/t42/a.mp4?oh=SECRETO&oe=123ABC"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64


def resolver_fijo(*ips):
    return lambda host: list(ips)


class _Resp:
    def __init__(self, estado, cabeceras, cuerpo):
        self.status = estado
        self._h = {k.lower(): v for k, v in cabeceras.items()}
        self._b = cuerpo
        self._p = 0

    def getheader(self, nombre, defecto=None):
        return self._h.get(nombre.lower(), defecto)

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self._b) - self._p
        trozo = self._b[self._p : self._p + n]
        self._p += len(trozo)
        return trozo


class ConexionFalsa:
    def __init__(self, estado=200, cabeceras=None, cuerpo=MP4):
        self.estado = estado
        self.cabeceras = (
            {"Content-Type": "video/mp4"} if cabeceras is None else cabeceras
        )
        self.cuerpo = cuerpo
        self.llamadas = []
        self.conexiones = []

    def __call__(self, ip, host):
        self.conexiones.append((ip, host))
        return self

    def request(self, metodo, ruta, headers=None):
        self.llamadas.append((self.conexiones[-1], metodo, ruta, headers))

    def getresponse(self):
        return _Resp(self.estado, self.cabeceras, self.cuerpo)

    def close(self):
        pass


@pytest.mark.parametrize(
    "url",
    [
        "http://video.xx.fbcdn.net/v.mp4",
        "https://fbcdn.net.evil.example/v.mp4",
        "https://u:p@video.xx.fbcdn.net/v.mp4",
        "https://video.xx.fbcdn.net:8443/v.mp4",
        "https://evilfbcdn.net/v.mp4",
    ],
)
def test_rechaza_host_no_permitido(url, tmp_path):
    assert url_permitida(url) is False
    con = ConexionFalsa()
    with pytest.raises(DescargaRechazada):
        descargar_medio(
            url, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
        )
    assert con.conexiones == []


@pytest.mark.parametrize(
    "ips",
    [
        ["10.0.0.5"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["::1"],
        ["::ffff:127.0.0.1"],
        ["157.240.0.1", "10.0.0.1"],
        [],
    ],
)
def test_rechaza_ip_privada_o_mapeada(ips, tmp_path):
    con = ConexionFalsa()
    with pytest.raises(DescargaRechazada):
        descargar_medio(URL, tmp_path / "x", resolver=resolver_fijo(*ips), conectar=con)
    assert con.conexiones == []


def test_ip_publica_devuelve_la_primera():
    assert ip_publica("a.fbcdn.net", resolver_fijo("157.240.0.1", "157.240.0.2")) == (
        "157.240.0.1"
    )


def test_conecta_a_ip_fijada_con_sni(tmp_path):
    con = ConexionFalsa()
    descargar_medio(
        URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
    )
    (ip, host), metodo, _ruta, headers = con.llamadas[0]
    assert (ip, host, metodo) == ("157.240.0.1", "video.xx.fbcdn.net", "GET")
    assert headers["Host"] == "video.xx.fbcdn.net"


def test_redireccion_es_rechazo(tmp_path):
    con = ConexionFalsa(302, {"Location": "http://169.254.169.254/latest"}, b"")
    with pytest.raises(DescargaRechazada):
        descargar_medio(
            URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
        )
    assert list(tmp_path.iterdir()) == []


def test_tope_borra_parcial(tmp_path):
    cuerpo = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * (61 * 1024**2)
    con = ConexionFalsa(cuerpo=cuerpo)
    with pytest.raises(DescargaRechazada):
        descargar_medio(
            URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
        )
    assert list(tmp_path.iterdir()) == []


def test_html_disfrazado_rechazado(tmp_path):
    con = ConexionFalsa(cuerpo=b"<html><body>hola</body></html>" * 4)
    with pytest.raises(DescargaRechazada):
        descargar_medio(
            URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
        )
    assert list(tmp_path.iterdir()) == []


def test_content_type_no_permitido(tmp_path):
    con = ConexionFalsa(cabeceras={"Content-Type": "text/html"})
    with pytest.raises(DescargaRechazada):
        descargar_medio(
            URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
        )


def test_descarga_mp4_ok(tmp_path):
    con = ConexionFalsa()
    res = descargar_medio(
        URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
    )
    assert res == tmp_path / "x.mp4"
    assert res.read_bytes() == MP4
    assert stat.S_IMODE(os.stat(res).st_mode) == 0o600
    assert [p.name for p in tmp_path.iterdir()] == ["x.mp4"]


def test_descarga_jpg_ok(tmp_path):
    con = ConexionFalsa(
        cabeceras={"Content-Type": "image/jpeg"}, cuerpo=b"\xff\xd8\xff\xe0" + b"0" * 20
    )
    res = descargar_medio(
        URL, tmp_path / "y", resolver=resolver_fijo("157.240.0.1"), conectar=con
    )
    assert res.name == "y.jpg"


def test_mensaje_sin_query(tmp_path):
    for con in (
        ConexionFalsa(302, {"Location": URL}, b""),
        ConexionFalsa(404, {}, b""),
    ):
        with pytest.raises(DescargaRechazada) as ei:
            descargar_medio(
                URL, tmp_path / "x", resolver=resolver_fijo("157.240.0.1"), conectar=con
            )
        assert "oh=" not in str(ei.value) and "oe=" not in str(ei.value)
        assert "SECRETO" not in str(ei.value)
    with pytest.raises(DescargaRechazada) as ei:
        descargar_medio(
            URL,
            tmp_path / "x",
            resolver=resolver_fijo("10.0.0.1"),
            conectar=ConexionFalsa(),
        )
    assert "oh=" not in str(ei.value) and "SECRETO" not in str(ei.value)


def test_destino_tipo_path(tmp_path):
    assert isinstance(tmp_path, Path)
