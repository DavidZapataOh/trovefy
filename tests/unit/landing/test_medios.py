"""Tarea 2 del plan 18: medios propios y vistas previas reales del PDF."""

import json
import stat
import subprocess
from pathlib import Path

import pytest
from trovefy import cli, landing_cli
from trovefy.landing import medios as lm
from trovefy.landing.entrada import cargar_datos, ruta_landing

from .conftest import P, vault_demo


class Ejecutar:
    """`subprocess.run` falso: registra cada orden y crea el archivo de salida que pediría."""

    def __init__(self):
        self.ordenes: list[list[str]] = []
        self.kwargs: list[dict] = []

    def __call__(self, orden, **kw):
        assert isinstance(orden, list)
        self.ordenes.append(orden)
        self.kwargs.append(kw)
        if orden[0] == "pdfinfo":
            return subprocess.CompletedProcess(orden, 0, "Pages:          3\n", "")
        if orden[0] == "pdftoppm":
            Path(orden[-1] + ".png").write_bytes(b"\x89PNG falso " + " ".join(orden).encode())
        elif orden[0] == "ffmpeg":
            Path(orden[-1]).write_bytes(b"RIFF webp falso " + " ".join(orden).encode())
        return subprocess.CompletedProcess(orden, 0, "", "")


@pytest.fixture
def ej():
    return Ejecutar()


def test_vistas_previas_ordenes(tmp_path, ej):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    out = lm.vistas_previas(pdf, (2,), tmp_path / "dest", ejecutar=ej, total=3)
    ppm = next(o for o in ej.ordenes if o[0] == "pdftoppm")
    assert ppm[ppm.index("-f") + 1] == "2" and ppm[ppm.index("-l") + 1] == "2"
    assert all("shell" not in k for k in ej.kwargs) and all(k.get("timeout") == 120 for k in ej.kwargs)
    assert all(k.get("check") is True for k in ej.kwargs)
    assert sorted(m.archivo for m in out) == ["vista-p2-480.webp", "vista-p2-960.webp"]
    assert {m.origen for m in out} == {"vista_pdf"} and {m.ancho for m in out} == {480, 960}
    assert (tmp_path / "dest" / "vista-p2-960.webp").is_file()
    ff = [o for o in ej.ordenes if o[0] == "ffmpeg"]
    assert any("scale=480:-2" in o for o in ff) and all("libwebp" in o for o in ff)


def test_vistas_previas_cuenta_paginas_con_pdfinfo(tmp_path, ej):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    lm.vistas_previas(pdf, (3,), tmp_path / "dest", ejecutar=ej)
    assert ej.ordenes[0][0] == "pdfinfo"


def test_pagina_fuera_de_rango(tmp_path, ej):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    for pagina in (4, 0):
        with pytest.raises(ValueError, match="página"):
            lm.vistas_previas(pdf, (pagina,), tmp_path / "dest", ejecutar=ej, total=3)
    assert not [o for o in ej.ordenes if o[0] != "pdfinfo"]


def test_imagen_fuera_del_entregable_rechazada(tmp_path, ej):
    otra = tmp_path / "x.png"
    otra.write_bytes(b"png")
    with pytest.raises(ValueError, match="solo imágenes propias del entregable"):
        lm.imagenes_propias((otra,), tmp_path / "dest", ejecutar=ej)
    trampa = tmp_path / "productos" / P / "entregable" / ".." / ".." / "x.png"
    with pytest.raises(ValueError, match="solo imágenes propias del entregable"):
        lm.imagenes_propias((trampa,), tmp_path / "dest", ejecutar=ej)


def test_imagenes_propias(tmp_path, ej):
    v = vault_demo(tmp_path)
    d = cargar_datos(v, P, "ZZ")
    out = lm.imagenes_propias(d.imagenes, tmp_path / "dest", ejecutar=ej)
    assert sorted(m.archivo for m in out) == ["portada-480.webp", "portada-960.webp"]
    assert {m.origen for m in out} == {"entregable"}
    assert {m.fuente for m in out} == {"entregable/medios/portada.png"}


def _preparar(tmp_path, ej, **kw):
    v = vault_demo(tmp_path)
    d = cargar_datos(v, P, "ZZ")
    return v, d, lm.preparar_medios(v, d, ejecutar=ej, **kw)


def test_manifiestos(tmp_path, ej):
    v, d, assets = _preparar(tmp_path, ej)
    assert assets == ruta_landing(v, P, "ZZ") / "assets"
    medios = json.loads((assets / "medios.json").read_text(encoding="utf-8"))
    assert medios["version"] == 1
    webps = sorted(p.name for p in assets.glob("*.webp"))
    assert sorted(m["archivo"] for m in medios["medios"]) == webps and len(webps) == 8
    import hashlib

    for m in medios["medios"]:
        assert m["origen"] in ("vista_pdf", "entregable")
        assert m["sha256"] == hashlib.sha256((assets / m["archivo"]).read_bytes()).hexdigest()
    vistas = json.loads((assets / "vistas.json").read_text(encoding="utf-8"))
    assert vistas == {"pdf": "demo-bg-v1.pdf", "sha256": d.pdf_sha256, "paginas": [1, 2, 3]}


def test_paginas_elegidas_y_limpieza(tmp_path, ej):
    v, d, assets = _preparar(tmp_path, ej)
    lm.preparar_medios(v, d, (1, 3), ejecutar=ej)
    assert not (assets / "vista-p2-480.webp").exists()
    medios = json.loads((assets / "medios.json").read_text(encoding="utf-8"))
    assert sorted(p.name for p in assets.glob("*.webp")) == sorted(m["archivo"] for m in medios["medios"])


def test_modo_0640(tmp_path, ej):
    _, _, assets = _preparar(tmp_path, ej)
    for p in assets.iterdir():
        assert stat.S_IMODE(p.stat().st_mode) == 0o640, p.name


def test_log_una_linea(tmp_path, ej):
    v, _, _ = _preparar(tmp_path, ej)
    lineas = [x for x in (v / "log.md").read_text(encoding="utf-8").splitlines() if "landing" in x]
    assert len(lineas) == 1 and "medios" in lineas[0]


def test_cli_medios(entorno, ej, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", ej)
    assert cli.main(["landing", "medios", "--producto", P, "--pais", "ZZ", "--paginas", "1,3"]) == 0
    assets = ruta_landing(entorno, P, "ZZ") / "assets"
    assert json.loads((assets / "vistas.json").read_text(encoding="utf-8"))["paginas"] == [1, 3]
    assert "assets" in capsys.readouterr().out


def test_cli_medios_paginas_mal(entorno, ej, monkeypatch, capsys):
    monkeypatch.setattr(landing_cli, "_ejecutar_orden", ej)
    assert cli.main(["landing", "medios", "--producto", P, "--pais", "ZZ", "--paginas", "1,9"]) == 2
    assert "página" in capsys.readouterr().err
