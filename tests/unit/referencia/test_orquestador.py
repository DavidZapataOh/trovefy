from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from trovefy.caza.cliente import PaginaCapturada
from trovefy.referencia import cache, orquestador
from trovefy.referencia.orquestador import Objetivo, resolver_objetivo, ver
from trovefy.referencia.salida import Analisis, cargar_referencia
from trovefy.referencia.watch import Entorno
from trovefy.vault.frontmatter import escribir as fm_escribir
from trovefy.vault.frontmatter import leer as fm_leer

FIX = Path(__file__).resolve().parents[2] / "fixtures/referencia"
PLANTILLA = Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml"
AHORA = datetime(2026, 11, 13, 10, 0, tzinfo=ZoneInfo("America/Bogota"))
P = "p-0001-prueba"
LIB = "900000000000001"
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PAISES = {"MX": {"c8": 31}, "AR": {"c8": 5}}


class NavFalso:
    def __init__(self):
        self.llamadas = []

    def abrir(self, url, max_anuncios):
        self.llamadas.append(url)
        d = json.loads((FIX / "pagina_con_medios.json").read_text())
        return PaginaCapturada(d["url_final"], d["html_final"], "", [])


class Resp:
    def __init__(self, tipo, cuerpo):
        self.status, self._t, self._b, self._p = 200, tipo, cuerpo, 0

    def getheader(self, n, d=None):
        return self._t if n.lower() == "content-type" else d

    def read(self, n=-1):
        t = self._b[self._p : self._p + n]
        self._p += len(t)
        return t


class Conexion:
    def __init__(self):
        self.ruta = ""

    def __call__(self, ip, host):
        return self

    def request(self, m, ruta, headers=None):
        self.ruta = ruta

    def getresponse(self):
        return Resp("video/mp4", MP4) if ".mp4" in self.ruta else Resp("image/jpeg", JPG)

    def close(self):
        pass


def ejecutar_falso(cmd, **kw):
    out = Path(cmd[cmd.index("--out-dir") + 1])
    (out / "frames").mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 3):
        (out / "frames" / f"f_000{i}.jpg").write_bytes(b"")
    texto = (FIX / "watch_salida.md").read_text().replace("{trabajo}", str(out))
    return subprocess.CompletedProcess(cmd, 0, texto, "")


def entorno(whisperx=True):
    return Entorno("/usr/bin/ffmpeg", "/usr/bin/ffprobe", True, whisperx, "")


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("TROVEFY_CACHE_REFERENCIA", str(tmp_path / "cache"))
    v = tmp_path / "vault"
    (v / "config").mkdir(parents=True)
    shutil.copy(PLANTILLA, v / "config/umbrales.yaml")
    fm_escribir(v / f"productos/{P}/PRODUCTO.md", {"id": P, "oferta_id": "o-001", "paises": {"RO": {"estado": "aprobado"}}}, "# P\n")
    fm_escribir(
        v / "wiki/ofertas/o-001.md",
        {"oferta_id": "o-001", "page_ids": ["800000000001"], "paises": PAISES, "idiomas": ["ro"]},
        "# o\n",
    )
    return v


OBJ = Objetivo(P, "o-001", "800000000001", "RO", "ro")


def _ver(v, **kw):
    args = {
        "top": None, "lote": None, "sin_navegador": False, "ahora": AHORA, "navegador": NavFalso(),
        "resolver": lambda h: ["8.8.8.8"], "conectar": Conexion(), "ejecutar": ejecutar_falso, "entorno": entorno(),
    }  # fmt: skip
    args.update(kw)
    return ver(v, OBJ, **args)


def test_ver_extremo_a_extremo(vault, tmp_path):
    r = _ver(vault)
    d = vault / f"productos/{P}/referencia"
    assert all((d / n).is_file() for n in ("anuncios.md", "mezcla.md", "ranking.json", "galeria.html"))
    assert cargar_referencia(vault, P).via == "publica"
    carpeta = tmp_path / "cache" / P / LIB
    assert any(carpeta.rglob("video.mp4")) and (carpeta / "watch.md").is_file()
    assert not any(f for f in (vault / "productos").rglob("*") if f.suffix in (".mp4", ".jpg"))
    assert sum("ver-anuncios" in x for x in (vault / "log.md").read_text().splitlines()) == 1
    t = next(x for x in r.trabajo if x["library_id"] == LIB)
    assert len(t["fotogramas"]) == 3 and t["transcripcion"] and t["puesto"] == 1
    textos = json.loads(cache.textos_path(P).read_text())
    assert set(textos[LIB]) == {"texto", "titulo"}


def test_ver_desde_lote(vault):
    ref = _ver(vault, lote=FIX / "lote_pagina.json").ref
    assert ref.via == "mcp" and ref.via_medios == "publica"


def test_ver_parada_meta_no_descarga(vault):
    class Bloquea:
        def abrir(self, url, max_anuncios):
            from trovefy.caza.cliente import SesionBloqueada

            raise SesionBloqueada("x")

    def no_debe(h):
        raise AssertionError("no debe resolver")

    r = _ver(vault, navegador=Bloquea(), resolver=no_debe)
    assert r.tipo_parada == "meta" and r.trabajo == []


def test_ver_conserva_analisis_previos(vault):
    _ver(vault)
    from trovefy.referencia.salida import escribir_referencia

    ref = cargar_referencia(vault, P)
    ref.fichas[0].analisis = Analisis("a", "b", "c", "d", "e", "f")
    escribir_referencia(vault, ref, AHORA)
    _ver(vault)
    assert cargar_referencia(vault, P).fichas[0].analisis == Analisis("a", "b", "c", "d", "e", "f")


def test_ver_limpia_vencidos_al_empezar(vault, tmp_path):
    viejo = cache.carpeta_anuncio("p-0002-viejo", "111", AHORA.replace(year=2026, month=9, day=1), 30)
    _ver(vault)
    assert not viejo.exists()


def test_ver_sin_whisperx_sigue(vault):
    def sin_texto(cmd, **kw):
        p = ejecutar_falso(cmd, **kw)
        p.stdout = (FIX / "watch_sin_transcripcion.md").read_text().replace("{trabajo}", cmd[cmd.index("--out-dir") + 1])
        return p

    r = _ver(vault, entorno=entorno(whisperx=False), ejecutar=sin_texto)
    t = next(x for x in r.trabajo if x["library_id"] == LIB)
    assert t["fotogramas"] and t["transcripcion"] is None
    assert t["motivo"].startswith("no medido: whisper local no instalado")


def test_ver_fallos_son_no_medido(vault):
    def revienta(h):
        raise OSError("x")

    r = _ver(vault, resolver=revienta)
    assert all(t["motivo"] and t["motivo"].startswith("no medido") for t in r.trabajo if t["fotogramas"] == [])


def test_resolver_objetivo_pais_de_la_ficha(vault):
    o = resolver_objetivo(vault, P, None, None)
    assert (o.pais, o.page_id, o.oferta_id, o.idioma) == ("MX", "800000000001", "o-001", "ro")


def test_page_id_ajeno_rechazado(vault):
    with pytest.raises(ValueError):
        resolver_objetivo(vault, P, None, "123")


def test_producto_o_ficha_faltan(vault):
    with pytest.raises(FileNotFoundError, match="auditar"):
        resolver_objetivo(vault, "p-0009-no", None, None)
    (vault / "wiki/ofertas/o-001.md").unlink()
    with pytest.raises(FileNotFoundError):
        resolver_objetivo(vault, P, None, None)


def test_no_cambia_estados(vault):
    antes = fm_leer(vault / f"productos/{P}/PRODUCTO.md")[0]["paises"]
    _ver(vault)
    assert fm_leer(vault / f"productos/{P}/PRODUCTO.md")[0]["paises"] == antes


def test_modulo_importable():
    assert orquestador.Resultado
