import subprocess
from pathlib import Path

import pytest
from fixtures.pdf.fuente_latina import FAMILIA_LATINA, crear_coleccion
from fixtures.pdf.herramientas import faltan, requerir
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
    assert args == ["fc-match", "-f", "%{family}\n%{file}\n%{index}", FAMILIA_LATINA]
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
    requerir(faltan("fc-match"))
    ruta = ruta_fuente("DejaVu Sans")
    requerir(None if ruta else "DejaVu Sans no está instalada (sudo apt install -y fonts-dejavu-core)")
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


# --- revisión: colecciones .ttc (L6) ----------------------------------------------------------------


def test_glifos_de_la_fuente_del_indice(tmp_path):
    ttc = crear_coleccion(tmp_path / "coleccion.ttc")
    assert {"Д", "ш"} <= glifos_faltantes("Дишай", ttc, indice=0)
    assert glifos_faltantes("Дишай", ttc, indice=1) == set()


def test_comprobar_fuentes_usa_el_indice_de_fc_match(tmp_path):
    ttc = crear_coleccion(tmp_path / "coleccion.ttc")
    correr = _fc({"Coleccion Cirilica": f"Coleccion Cirilica\n{ttc}\n1",
                  "Coleccion Latina": f"Coleccion Latina\n{ttc}\n0"})
    assert comprobar_fuentes("<p>Дишай</p>", ("Coleccion Cirilica", "Coleccion Cirilica"), correr=correr) == []
    problemas = comprobar_fuentes("<p>Дишай</p>", ("Coleccion Latina", "Coleccion Latina"), correr=correr)
    assert len(problemas) == 1 and "«Coleccion Latina» no tiene" in problemas[0]


def test_indice_ilegible_es_problema(tmp_path):
    ttc = crear_coleccion(tmp_path / "coleccion.ttc")
    correr = _fc({"Coleccion Latina": f"Coleccion Latina\n{ttc}\nx"})
    problemas = comprobar_fuentes("<p>Hola</p>", ("Coleccion Latina", "Coleccion Latina"), correr=correr)
    assert len(problemas) == 1 and "no medido" in problemas[0]


def test_real_fc_match_da_indice():
    requerir(faltan("fc-match"))
    r = subprocess.run(["fc-match", "-f", "%{family}\n%{file}\n%{index}", "DejaVu Sans"], capture_output=True,
                       text=True, check=True)
    assert r.stdout.split("\n")[2] == "0"


def test_requerir_en_ci_falla(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(pytest.fail.Exception, match="falta pdfinfo"):
        requerir("falta pdfinfo")
    requerir(None)
    monkeypatch.delenv("CI")
    with pytest.raises(pytest.skip.Exception):
        requerir("falta pdfinfo")
