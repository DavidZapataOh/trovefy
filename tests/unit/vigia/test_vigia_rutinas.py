"""/vigia mira cada rutina instalada (plan 24, Tarea 10)."""
from datetime import datetime

import pytest
import yaml
from trovefy.vault import frontmatter
from trovefy.vault.andamio import crear_vault
from trovefy.vault.escritura import ZONA_NEGOCIO
from trovefy.vigia import comprobaciones as c

AHORA = datetime(2026, 11, 20, 10, 0, tzinfo=ZONA_NEGOCIO)  # viernes
P = "p-0099-prueba-abc123"


@pytest.fixture
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    v = tmp_path / "vault"
    crear_vault(v)
    return v


def _unidades(tmp_path, *insts):
    u = tmp_path / "unidades"
    u.mkdir(exist_ok=True)
    for i in insts:
        (u / f"trovefy-{i}.timer").write_text("")
    return u


def _log(v, nombre, texto, dia="2026-11-20"):
    carpeta = v / "rutinas" / "log" / dia
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / f"{nombre}.md").write_text(f"# Rutina {nombre}\n\n{texto}\n")


def _test_vivo(v):
    caja = yaml.safe_load((v / "config" / "caja.yaml").read_text())
    caja["tests"] = [{"producto": P, "pais": "ZZ", "campana_id": "1", "estado": "vivo", "prorroga": False,
                      "ventas": None, "diario_usd": 25}]
    (v / "config" / "caja.yaml").write_text(yaml.safe_dump(caja))
    frontmatter.escribir(v / "productos" / P / "PRODUCTO.md", {"id": P, "paises": {"ZZ": {"estado": "test"}}}, "")


def _por_nombre(res):
    return {x.nombre: x for x in res}


def test_una_comprobacion_por_rutina(vault, tmp_path):
    res = c.rutinas(vault, AHORA, _unidades(tmp_path, "caza", "cierre", "vigia"))
    assert {x.nombre for x in res} == {"rutinas", "rutina cierre", "rutina vigia"}


def test_rutina_sin_log_es_aviso(vault, tmp_path):
    res = _por_nombre(c.rutinas(vault, AHORA, _unidades(tmp_path, "cierre")))
    assert res["rutina cierre"].nivel == "aviso" and "no dejó su log" in res["rutina cierre"].texto
    _log(vault, "cierre", "## 08:31 COT · ok\n\nCierre del 19/11")
    assert c.rutinas(vault, AHORA, _unidades(tmp_path, "cierre"))[0].nivel == "ok"
    _log(vault, "cierre", "## 08:31 COT · ok\n\nx\n\n## 08:50 COT · fallida\n\nfallida: exit-code/1")
    assert c.rutinas(vault, AHORA, _unidades(tmp_path, "cierre"))[0].nivel == "aviso"


def test_antes_de_su_hora_es_ok(vault, tmp_path):
    temprano = AHORA.replace(hour=8, minute=45)
    assert c.rutinas(vault, temprano, _unidades(tmp_path, "cierre"))[0].nivel == "ok"
    assert _por_nombre(c.rutinas(vault, AHORA, _unidades(tmp_path, "cierre-noche")))["rutina cierre-noche"].nivel == "ok"


def test_omitida_sin_test_vivo_no_es_aviso(vault, tmp_path):
    assert c.rutinas(vault, AHORA, _unidades(tmp_path, "parte"))[0].nivel == "ok"
    _test_vivo(vault)
    assert c.rutinas(vault, AHORA, _unidades(tmp_path, "parte"))[0].nivel == "aviso"
    _log(vault, "leer-parte", "## 07:31 COT · omitida\n\nomitida")
    assert c.rutinas(vault, AHORA, _unidades(tmp_path, "parte"))[0].nivel == "ok"


def test_intradia_fuera_de_ventana_no_se_exige(vault, tmp_path):
    u = _unidades(tmp_path, "intradia-zz")
    assert c.rutinas(vault, AHORA, u)[0].nivel == "ok"  # sin test vivo no se lanza
    _test_vivo(vault)
    assert c.rutinas(vault, AHORA, u)[0].nivel == "aviso"
    _log(vault, "leer-intradia-zz", "## 05:00 COT · ok\n\nx")
    assert c.rutinas(vault, AHORA, u)[0].nivel == "aviso"  # más de 3 h
    _log(vault, "leer-intradia-zz", "## 05:00 COT · ok\n\nx\n\n## 09:00 COT · ok\n\ny")
    assert c.rutinas(vault, AHORA, u)[0].nivel == "ok"


def test_caza_domingo_sigue_igual(vault, tmp_path):
    domingo = datetime(2026, 11, 22, 10, 0, tzinfo=ZONA_NEGOCIO)
    r = c.rutinas(vault, domingo, _unidades(tmp_path, "caza"))[0]
    assert r.nivel == "ok" and "domingo" in r.texto


def test_sin_rutinas_no_medido(vault, tmp_path):
    assert c.rutinas(vault, AHORA, tmp_path / "nada")[0].texto == "no medido: no hay rutinas instaladas"
