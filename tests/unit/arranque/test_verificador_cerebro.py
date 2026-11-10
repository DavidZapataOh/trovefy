import json
from datetime import datetime, timedelta

from trovify.arranque.verificadores import REGISTRO
from trovify.cerebro.canarios import cargar, sha256_de
from trovify.vault.andamio import crear_vault
from trovify.vault.escritura import ZONA_NEGOCIO
from trovify.vault.frontmatter import escribir


def _hoy():
    return datetime.now(ZONA_NEGOCIO).date()


def _pagina_metodo(vault, n=1):
    raw = vault / f"raw/fuente{n}.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("fuente")
    escribir(
        vault / f"wiki/metodo/m{n}.md",
        {"tipo": "metodo", "fecha": "2026-01-01", "fuentes": [f"raw/fuente{n}.md"]},
        "## Regla\nSe hace así (T1 10:00).\n",
    )
    idx = vault / "index.md"
    idx.write_text(idx.read_text() + f"\n[[m{n}]]\n")


def _ultimo(vault, **cambios):
    datos = {
        "fecha": _hoy().isoformat(), "todos_ok": True,
        "resultados": [{"id": c.id, "estado": "ok", "faltan": [], "respuesta": ""} for c in cargar()],
        "ids": [c.id for c in cargar()], "canarios_sha256": sha256_de(),
    }
    datos.update(cambios)
    (vault / "data/canarios").mkdir(parents=True, exist_ok=True)
    (vault / "data/canarios/ultimo.json").write_text(json.dumps(datos))


def test_cerebro_sin_canarios_no_verifica(tmp_path):
    crear_vault(tmp_path)
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "canarios" in r.motivo
    assert any("trovify cerebro canarios" in a for a in r.arreglos)


def test_canarios_viejos_no_valen(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, fecha=(_hoy() - timedelta(days=31)).isoformat())
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "30 días" in r.motivo


def test_cerebro_completo_verifica(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, fecha=(_hoy() - timedelta(days=30)).isoformat())
    r = REGISTRO["01"](tmp_path)
    assert r.ok is True, r.motivo
    assert any("ultimo.json" in e for e in r.evidencia)
    assert (tmp_path / r.evidencia[-1]).is_file()
    assert json.loads((tmp_path / r.evidencia[-1]).read_text())["paginas_metodo"] == 1


def test_todos_ok_falso(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, todos_ok=False)
    assert REGISTRO["01"](tmp_path).ok is False


def test_ids_distintos(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, ids=["otro"])
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "ids" in r.motivo


def test_sha_distinto(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, canarios_sha256="0" * 64)
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "sha" in r.motivo


def test_cero_paginas_de_metodo(tmp_path):
    crear_vault(tmp_path)
    _ultimo(tmp_path)
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "wiki/metodo" in r.motivo


def test_pagina_invalida(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    escribir(tmp_path / "wiki/metodo/mala.md", {"tipo": "metodo", "fecha": "2026-01-01", "fuentes": ["raw/fuente1.md"]}, "## Sin cita\ntexto\n")
    (tmp_path / "index.md").write_text((tmp_path / "index.md").read_text() + "\n[[mala]]\n")
    _ultimo(tmp_path)
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "wiki/metodo" in r.motivo and "cita" in r.motivo


def test_sin_vault(tmp_path):
    r = REGISTRO["01"](tmp_path / "nada")
    assert r.ok is False and "vault" in r.motivo


def test_fecha_futura(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, fecha=(_hoy() + timedelta(days=1)).isoformat())
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "futuro" in r.motivo


def test_resultados_vacios(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path, resultados=[])
    assert REGISTRO["01"](tmp_path).ok is False


def test_resultado_no_ok(tmp_path):
    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    res = [{"id": c.id, "estado": "ok"} for c in cargar()]
    res[0]["estado"] = "falla"
    _ultimo(tmp_path, resultados=res)
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and res[0]["id"] in r.motivo


def test_canarios_yaml_roto(tmp_path, monkeypatch):
    import yaml
    from trovify.cerebro import canarios

    def roto(*a, **k):
        raise yaml.YAMLError("mal")

    crear_vault(tmp_path)
    _pagina_metodo(tmp_path)
    _ultimo(tmp_path)
    monkeypatch.setattr(canarios, "cargar", roto)
    r = REGISTRO["01"](tmp_path)
    assert r.ok is False and "canarios.yaml" in r.motivo
