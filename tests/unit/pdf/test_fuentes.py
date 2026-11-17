import shutil
import subprocess
from pathlib import Path

import pytest
from fixtures.pdf.fuente_latina import FAMILIA_LATINA
from trovefy.pdf.fuentes import (
    comprobar_fuentes,
    glifos_faltantes,
    paquete_apt,
    ruta_fuente,
)

DEJAVU_SERIF = "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"


def _fc(salidas: dict[str, str], llamadas: list | None = None):
    """``correr`` falso de ``fc-match``: devuelve la salida fijada para cada familia pedida."""

    def correr(args, **kw):
        if llamadas is not None:
            llamadas.append((list(args), kw))
        assert args[0] == "fc-match"
        return subprocess.CompletedProcess(args, 0, stdout=salidas[args[-1]], stderr="")

    return correr


def test_fc_match_sustituye_familia():
    correr = _fc({"Lora": f"DejaVu Serif\n{DEJAVU_SERIF}"})
    assert ruta_fuente("Lora", correr=correr) is None


def test_fc_match_usa_formato_familia_y_archivo(latin_only):
    llamadas = []
    correr = _fc({FAMILIA_LATINA: f"{FAMILIA_LATINA}\n{latin_only}"}, llamadas)
    assert ruta_fuente(FAMILIA_LATINA, correr=correr) == latin_only
    args, kw = llamadas[0]
    assert args == ["fc-match", "-f", "%{family}\n%{file}", FAMILIA_LATINA]
    assert kw.get("capture_output") is True


def test_fc_match_primera_familia_sin_mayusculas(latin_only):
    correr = _fc({"latin only": f"Latin Only,Latin Only Regular\n{latin_only}"})
    assert ruta_fuente("latin only", correr=correr) == latin_only


def test_fc_match_falla_es_none():
    def correr(args, **kw):
        return subprocess.CompletedProcess(args, 1, stdout="", stderr="error")

    assert ruta_fuente("Lora", correr=correr) is None


def test_glifos_cirilicos_faltantes(latin_only):
    faltan = glifos_faltantes("Дишай bien", latin_only)
    assert {"Д", "и", "ш", "а", "й"} <= faltan
    assert not faltan & set("bien")


def test_glifos_ignora_espacios_y_control(latin_only):
    assert glifos_faltantes("hola\n\t mundo\u200b\x07", latin_only) == set()


def test_fuente_cirilica_completa():
    if shutil.which("fc-match") is None:
        pytest.skip("falta fc-match (fontconfig): CI lo instala en la Tarea 9")
    ruta = ruta_fuente("DejaVu Sans")
    if ruta is None:
        pytest.skip("DejaVu Sans no está instalada (fonts-dejavu-core): CI la instala en la Tarea 9")
    assert glifos_faltantes("Дишай спокойно: щ, ж, ъ, ю, я — «Ъ»", ruta) == set()


def test_comprobar_fuentes_sustitucion_da_orden_apt():
    correr = _fc({"Lora": f"DejaVu Serif\n{DEJAVU_SERIF}", "Noto Sans": f"DejaVu Sans\n{DEJAVU_SERIF}"})
    problemas = comprobar_fuentes("<p>Hola</p>", ("Lora", "Noto Sans"), correr=correr)
    assert problemas[0] == (
        "la fuente «Lora» no está instalada (fc-match da «DejaVu Serif»); en una terminal de Ubuntu (WSL) "
        "aparte: `sudo apt install -y fonts-noto-core` o elige otra en BRANDBOOK.md")
    assert "«Noto Sans»" in problemas[1] and "fonts-noto-core" in problemas[1]
    assert len(problemas) == 2


def test_comprobar_fuentes_letras_que_faltan(latin_only):
    correr = _fc({FAMILIA_LATINA: f"{FAMILIA_LATINA}\n{latin_only}"})
    html = "<html><head><title>Ж</title><style>.x{content:'щ'}</style></head><body><h1>Дишай</h1></body></html>"
    problemas = comprobar_fuentes(html, (FAMILIA_LATINA, FAMILIA_LATINA), correr=correr)
    assert problemas == ["«Latin Only» no tiene 5 letras del texto: Д, а, и, й, ш"]


def test_comprobar_fuentes_bien(latin_only):
    correr = _fc({FAMILIA_LATINA: f"{FAMILIA_LATINA}\n{latin_only}"})
    assert comprobar_fuentes("<p>Todo bien: 1, 2, 3.</p>", (FAMILIA_LATINA, FAMILIA_LATINA), correr=correr) == []


def test_sin_fc_match_no_medido():
    def correr(args, **kw):
        raise FileNotFoundError(args[0])

    problemas = comprobar_fuentes("<p>Hola</p>", ("DejaVu Serif", "DejaVu Sans"), correr=correr)
    assert len(problemas) == 1
    assert problemas[0].startswith("no medido: falta fc-match") and "sudo apt install -y fontconfig" in problemas[0]


@pytest.mark.parametrize(("familia", "paquete"), [
    ("DejaVu Sans", "fonts-dejavu-core"),
    ("Noto Serif", "fonts-noto-core"),
    ("Ubuntu", "fonts-ubuntu"),
    ("Nimbus Sans", "fonts-urw-base35"),
    ("Lora", "fonts-noto-core"),
])
def test_paquete_apt(familia, paquete):
    assert paquete_apt(familia) == paquete


def test_ruta_inexistente_es_none(tmp_path):
    correr = _fc({"Fantasma": f"Fantasma\n{tmp_path / 'no-existe.ttf'}"})
    assert ruta_fuente("Fantasma", correr=correr) is None


def test_ruta_es_path(latin_only):
    correr = _fc({FAMILIA_LATINA: f"{FAMILIA_LATINA}\n{latin_only}"})
    assert isinstance(ruta_fuente(FAMILIA_LATINA, correr=correr), Path)
