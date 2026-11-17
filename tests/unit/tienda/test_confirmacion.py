"""Confirmación guiada de una pantalla con controles (plan 18, Tarea 8; resolución 20).

`capturado` de una pantalla escribible solo lo pone el usuario con su pantalla real delante. La confirmación
vive fuera del vault, en el directorio de configuración de trovefy (`pantallas-confirmadas.yaml`, que el hook
protege), atada a la huella de la pantalla del mapa, a la URL real que vio y a su captura del vault
`config/evidencia/p05-diseno-contenido-<fecha>.png` por SHA-256; caduca a los 90 días. La copia del vault
(`config/pantallas-confirmadas.yaml`) ya no se lee. `confirmar_pantalla` exige stdin y stdout TTY.
"""

import copy
import hashlib
import inspect
import io
import os
import types
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from trovefy.mapa import capturado_de
from trovefy.mapa import cargar as cargar_mapa
from trovefy.tienda import confirmacion
from trovefy.tienda.confirmacion import (
    confirmar_pantalla,
    huella_pantalla,
    mapa_con_confirmaciones,
    ruta_confirmaciones,
)

MAPA = Path(__file__).resolve().parents[3] / "templates" / "impultienda" / "mapa.yaml"
AHORA = datetime(2026, 11, 17, 10, 30, tzinfo=ZoneInfo("America/Bogota"))
REAL = "https://app.impultienda.ar/dashboard/tienda/123/diseno?tab=contenido"
EVIDENCIA = "config/evidencia/p05-diseno-contenido-2026-11-17.png"
PNG = b"\x89PNG\r\n\x1a\n captura enmascarada"
HOY = date(2026, 11, 17)


class _Tty(io.StringIO):
    def __init__(self, fd: int):
        super().__init__()
        self.fd = fd

    def fileno(self):
        return self.fd


def con_terminal(monkeypatch, stdin=True, stdout=True):
    """stdin y stdout con descriptor; `os.isatty` dice si son terminal (lo que mira `confirmar_pantalla`).

    Se cambian el `sys` y el `os.isatty` que ve el módulo: pytest vuelve a poner su `sys.stdout` al ejecutar."""
    monkeypatch.setattr(confirmacion, "sys", types.SimpleNamespace(stdin=_Tty(100), stdout=_Tty(101)))
    monkeypatch.setattr(confirmacion.os, "isatty", lambda fd: {100: stdin, 101: stdout}.get(fd, False))


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    h.mkdir()
    monkeypatch.setenv("HOME", str(h))
    return h


@pytest.fixture(autouse=True)
def terminal(monkeypatch):
    con_terminal(monkeypatch)


@pytest.fixture
def v(tmp_path):
    v = tmp_path / "v"
    (v / "config" / "evidencia").mkdir(parents=True)
    (v / EVIDENCIA).write_bytes(PNG)
    return v


def confirmar(v, m, **kw):
    """Una confirmación como la deja `trovefy landing capturar`: «sí», hoy y con su captura."""
    return confirmar_pantalla(v, "impultienda", m, "diseno_contenido", REAL, kw.pop("respuesta", "sí"), AHORA,
                              **kw)


def manipular(v, **cambios):
    ruta = ruta_confirmaciones()
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8"))
    datos["impultienda"]["diseno_contenido"].update(cambios)
    ruta.write_text(yaml.safe_dump(datos, allow_unicode=True), encoding="utf-8")


def confirmado(v, m, hoy=HOY):
    return capturado_de(mapa_con_confirmaciones(v, "impultienda", m, hoy=hoy), "diseno_contenido")


def test_sin_confirmar_el_mapa_no_cambia(v):
    m = cargar_mapa(MAPA)
    assert mapa_con_confirmaciones(v, "impultienda", m) == m
    assert capturado_de(m, "diseno_contenido") is None


def test_confirmar_y_mapa_confirmado(v, home):
    m = cargar_mapa(MAPA)
    original = copy.deepcopy(m)
    entrada = confirmar_pantalla(v, "impultienda", m, "diseno_contenido", REAL + "#x", "Sí", AHORA)
    assert entrada["fecha"] == "2026-11-17" and entrada["respuesta"] == "Sí" and entrada["url"] == REAL
    assert entrada["evidencia"] == EVIDENCIA
    assert entrada["evidencia_sha256"] == hashlib.sha256(PNG).hexdigest()
    assert m == original  # no muta el mapa que recibe
    assert ruta_confirmaciones() == home / ".config" / "trovefy" / "pantallas-confirmadas.yaml"
    assert not (v / "config" / "pantallas-confirmadas.yaml").exists()  # fuera del vault
    datos = yaml.safe_load(ruta_confirmaciones().read_text(encoding="utf-8"))
    assert datos["impultienda"]["diseno_contenido"]["huella"] == huella_pantalla(m["pantallas"]["diseno_contenido"])
    c = mapa_con_confirmaciones(v, "impultienda", m, hoy=HOY)
    assert capturado_de(c, "diseno_contenido") == "2026-11-17"
    assert c["pantallas"]["diseno_contenido"]["url"] == REAL
    assert capturado_de(c, "plan") is None and c["pantallas"]["plan"] == m["pantallas"]["plan"]
    assert "diseno_contenido" in (v / "log.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("respuesta", ["no", "", "si, pero", "vale"])
def test_sin_un_si_no_se_registra(v, respuesta):
    with pytest.raises(ValueError, match="no se confirma"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "diseno_contenido", REAL, respuesta, AHORA)
    assert not ruta_confirmaciones().exists()


@pytest.mark.parametrize("url", ["https://otro.test/x", "http://app.impultienda.ar/x",
                                 "https://app.impultienda.ar/login", "https://app.impultienda.ar/pagos/tarjeta"])
def test_url_fuera_del_mapa_o_de_login_o_cobro(v, url):
    with pytest.raises(ValueError):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "diseno_contenido", url, "si", AHORA)
    assert not ruta_confirmaciones().exists()


def test_pantalla_prohibida_no_se_confirma(v):
    with pytest.raises(ValueError, match="prohibida"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "pasarelas", REAL, "si", AHORA)


def test_pantalla_sin_controles_no_hace_falta(v):
    with pytest.raises(ValueError, match="controles"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "plan", REAL, "si", AHORA)


def test_si_el_mapa_cambia_la_confirmacion_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    assert confirmado(v, m) == "2026-11-17"
    cambiado = copy.deepcopy(m)
    cambiado["pantallas"]["diseno_contenido"]["firma"].append("Otra cosa")
    assert confirmado(v, cambiado) is None


def test_una_url_editada_a_mano_fuera_del_mapa_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, url="https://malo.test/x")
    assert confirmado(v, m) is None


# --- I-1: la confirmación exige un humano (un YAML manipulado no desbloquea nada) -----------------------


@pytest.mark.parametrize("respuesta", ["no", "", "vale", "si, pero", None, 1])
def test_yaml_manipulado_respuesta_que_no_es_si_no_vale(v, respuesta):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, respuesta=respuesta)
    assert confirmado(v, m) is None


@pytest.mark.parametrize("respuesta", ["sí", "Sí", " si ", "SÍ"])
def test_respuestas_si_valen(v, respuesta):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, respuesta=respuesta)
    assert confirmado(v, m) == "2026-11-17"


def test_sin_evidencia_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    (v / EVIDENCIA).unlink()
    assert confirmado(v, m) is None
    manipular(v, evidencia=None)
    assert confirmado(v, m) is None


@pytest.mark.parametrize("evidencia", ["config/otra/x.png", "../x.png", "config/evidencia/../../x.png",
                                       "config/evidencia/../otra/x.png", "config/evidencia", "config/evidencia/",
                                       "/etc/hosts", 7, "config/evidencia/p05-impultienda-2026-11-17.json",
                                       "config/evidencia/p05-diseno-contenido-2026-11-16.png",
                                       "config/evidencia/otra-2026-11-17.png"])
def test_evidencia_que_no_es_la_de_la_entrada_no_vale(v, evidencia):
    for ruta in (v / "config" / "otra" / "x.png", v / "x.png", v.parent / "x.png",
                 v / "config/evidencia/p05-impultienda-2026-11-17.json",
                 v / "config/evidencia/p05-diseno-contenido-2026-11-16.png", v / "config/evidencia/otra-2026-11-17.png"):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(PNG)
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, evidencia=evidencia)
    assert confirmado(v, m) is None


def test_evidencia_enlace_simbolico_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    fuera = v.parent / "fuera.png"
    fuera.write_bytes(PNG)
    (v / EVIDENCIA).unlink()
    os.symlink(fuera, v / EVIDENCIA)
    assert confirmado(v, m) is None


def test_evidencia_bajo_carpeta_enlazada_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    fuera = v.parent / "ev-fuera"
    fuera.mkdir()
    (fuera / "p05-diseno-contenido-2026-11-17.png").write_bytes(PNG)
    (v / EVIDENCIA).unlink()
    (v / "config" / "evidencia").rmdir()
    os.symlink(fuera, v / "config" / "evidencia")
    assert confirmado(v, m) is None


def test_fecha_futura_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, fecha="2026-11-18")
    assert confirmado(v, m) is None
    # la evidencia es la de su fecha: cambiar solo la fecha tampoco vale al día siguiente
    assert confirmado(v, m, hoy=date(2026, 11, 18)) is None


def test_sin_hoy_usa_la_fecha_de_negocio(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, fecha="2999-01-01")
    assert capturado_de(mapa_con_confirmaciones(v, "impultienda", m), "diseno_contenido") is None


def test_huella_manipulada_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, huella="0" * 64)
    assert confirmado(v, m) is None


def test_el_capturado_del_codigo_manda(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    m["pantallas"]["diseno_contenido"]["capturado"] = "2026-12-01"
    c = mapa_con_confirmaciones(v, "impultienda", m, hoy=HOY)
    assert capturado_de(c, "diseno_contenido") == "2026-12-01"
    assert c["pantallas"]["diseno_contenido"]["url"] == m["pantallas"]["diseno_contenido"]["url"]


def test_archivo_roto_no_se_pisa(v):
    ruta = ruta_confirmaciones()
    ruta.parent.mkdir(parents=True)
    ruta.write_text("{roto", encoding="utf-8")
    with pytest.raises(ValueError, match="no se puede leer"):
        confirmar_pantalla(v, "impultienda", cargar_mapa(MAPA), "diseno_contenido", REAL, "si", AHORA)
    assert ruta.read_text(encoding="utf-8") == "{roto"
    m = cargar_mapa(MAPA)
    assert mapa_con_confirmaciones(v, "impultienda", m) == m  # leer roto: sin confirmación, sin excepción


# --- F1-1: fuera del vault, con una persona en la terminal --------------------------------------------


@pytest.mark.parametrize(("stdin", "stdout"), [(False, True), (True, False), (False, False)])
def test_confirmar_sin_terminal_no_escribe(v, monkeypatch, stdin, stdout):
    con_terminal(monkeypatch, stdin, stdout)
    with pytest.raises(ValueError, match="ejecútalo tú en tu terminal"):
        confirmar(v, cargar_mapa(MAPA))
    assert not ruta_confirmaciones().exists()


def test_confirmar_con_stdin_sin_descriptor_no_escribe(v, monkeypatch):
    """Una tubería o un agente: stdin sin descriptor de terminal no es una persona delante."""
    monkeypatch.setattr(confirmacion, "sys", types.SimpleNamespace(stdin=io.StringIO("sí\n"), stdout=_Tty(101)))
    monkeypatch.setattr(confirmacion.os, "isatty", lambda fd: True)
    with pytest.raises(ValueError, match="terminal"):
        confirmar(v, cargar_mapa(MAPA))
    assert not ruta_confirmaciones().exists()


def test_sin_terminal_no_sugiere_rodeos():
    texto = confirmacion.SIN_TERMINAL
    assert "ejecútalo tú en tu terminal" in texto
    for rodeo in ("script", "printf", "tty", "pty", "|", "tubería"):
        assert rodeo not in texto, rodeo


def test_confirmar_pantalla_no_admite_terminal_inyectada():
    assert "terminal" not in inspect.signature(confirmar_pantalla).parameters


def test_la_copia_del_vault_ya_no_se_lee(v):
    """Un YAML con forma válida en el vault no desbloquea nada: solo cuenta el de la configuración."""
    m = cargar_mapa(MAPA)
    entrada = {"fecha": "2026-11-17", "url": REAL, "huella": huella_pantalla(m["pantallas"]["diseno_contenido"]),
               "respuesta": "sí", "evidencia": EVIDENCIA, "evidencia_sha256": hashlib.sha256(PNG).hexdigest()}
    (v / "config" / "pantallas-confirmadas.yaml").write_text(
        yaml.safe_dump({"impultienda": {"diseno_contenido": entrada}}), encoding="utf-8")
    assert confirmado(v, m) is None


def _forja(v, m) -> str:
    """El YAML de `forja.py` de la revisión: ancla, « SÍ », fecha de 1999 y la evidencia de la sonda."""
    (v / "config/evidencia/p05-impultienda-2026-01-01.json").write_text("{}", encoding="utf-8")
    p = m["pantallas"]["diseno_contenido"]
    return ("base: &e\n"
            f"  fecha: 1999-01-01\n  url: {p['url']}\n  huella: {huella_pantalla(p)}\n  respuesta: ' SÍ '\n"
            "  evidencia: config/evidencia/p05-impultienda-2026-01-01.json\n"
            "impultienda:\n  diseno_contenido: *e\n")


def test_forja_de_la_revision_en_el_vault_no_vale(v):
    from trovefy.landing.panel import preparar_mapa
    from trovefy.tienda.conductor import MapaSinConfirmar

    m = cargar_mapa(MAPA)
    (v / "config" / "pantallas-confirmadas.yaml").write_text(_forja(v, m), encoding="utf-8")
    assert confirmado(v, m) is None
    with pytest.raises(MapaSinConfirmar):
        preparar_mapa(v)


def test_forja_de_la_revision_en_la_config_no_vale(v):
    m = cargar_mapa(MAPA)
    ruta = ruta_confirmaciones()
    ruta.parent.mkdir(parents=True)
    ruta.write_text(_forja(v, m), encoding="utf-8")
    assert confirmado(v, m) is None


# --- F1-3: la evidencia, atada a la entrada ------------------------------------------------------------


def test_confirmar_sin_captura_no_escribe(v):
    (v / EVIDENCIA).unlink()
    with pytest.raises(ValueError, match="captura"):
        confirmar(v, cargar_mapa(MAPA))
    assert not ruta_confirmaciones().exists()


def test_confirmar_captura_que_no_es_png_no_escribe(v):
    (v / EVIDENCIA).write_bytes(b"GIF89a no es png")
    with pytest.raises(ValueError, match="PNG"):
        confirmar(v, cargar_mapa(MAPA))
    assert not ruta_confirmaciones().exists()


def test_evidencia_cambiada_tras_confirmar_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    (v / EVIDENCIA).write_bytes(PNG + b" otra")
    assert confirmado(v, m) is None


def test_evidencia_que_deja_de_ser_png_no_vale(v):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    texto = b"no es png"
    (v / EVIDENCIA).write_bytes(texto)
    manipular(v, evidencia_sha256=hashlib.sha256(texto).hexdigest())
    assert confirmado(v, m) is None


@pytest.mark.parametrize("sha", [None, "", "0" * 64, 7])
def test_sha_manipulado_o_ausente_no_vale(v, sha):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    manipular(v, evidencia_sha256=sha)
    assert confirmado(v, m) is None


@pytest.mark.parametrize(("hoy", "vale"), [(date(2027, 2, 15), True), (date(2027, 2, 16), False),
                                           (date(2028, 1, 1), False)])
def test_caduca_a_los_90_dias(v, hoy, vale):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    assert (confirmado(v, m, hoy=hoy) == "2026-11-17") is vale


def test_confirmaciones_enlazadas_no_valen(v, tmp_path):
    m = cargar_mapa(MAPA)
    confirmar(v, m)
    ruta = ruta_confirmaciones()
    otra = tmp_path / "otra.yaml"
    otra.write_bytes(ruta.read_bytes())
    ruta.unlink()
    os.symlink(otra, ruta)
    assert confirmado(v, m) is None
