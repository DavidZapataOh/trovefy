import json
from pathlib import Path

import pytest
import yaml
from trovify import cli
from trovify.vault.andamio import crear_vault
from trovify.vault.frontmatter import leer
from trovify.vault.reglas import (
    ConflictoDeReglas,
    conflictos,
    consistencia,
    nueva_regla,
)


def _vault(tmp_path):
    v = tmp_path / "v"
    crear_vault(v)
    return v


def test_regla_nueva_se_indexa(tmp_path):
    v = _vault(tmp_path)
    ruta = nueva_regla(v, "No cazar en diciembre", "…", "…", "…", "Usuario 2026-11-10", fecha="2026-11-10")
    assert ruta.name == "R-013-no-cazar-en-diciembre.md"
    assert "R-013-no-cazar-en-diciembre" in (v / "CLAUDE.md").read_text()
    assert "R-013" in (v / "index.md").read_text()
    meta, _ = leer(ruta)
    assert meta["estado"] == "vigente" and meta["fecha"] == "2026-11-10"
    assert "recordar" in (v / "log.md").read_text()
    assert consistencia(v) == []


def test_slug_sin_acentos(tmp_path):
    v = _vault(tmp_path)
    ruta = nueva_regla(v, "Ñandú: ¡Más rápido!", "r", "p", "c", "U")
    assert ruta.name == "R-013-nandu-mas-rapido.md"


def test_contradiccion_se_detecta(tmp_path):
    v = _vault(tmp_path)
    antes = (v / "config/umbrales.yaml").read_text()
    with pytest.raises(ConflictoDeReglas) as e:
        nueva_regla(v, "Corte a 20", "…", "…", "…", "Usuario", umbrales={"corte.oferta.sin_ventas_usd": 20})
    assert "R-006" in e.value.ids
    assert (v / "config/umbrales.yaml").read_text() == antes
    assert not list((v / "wiki/reglas").glob("R-013*"))


def test_conflictos(tmp_path):
    v = _vault(tmp_path)
    assert conflictos(v, ["corte.oferta.sin_ventas_usd"]) == ["R-006"]
    assert conflictos(v, ["no.existe"]) == []


def test_reemplazo_actualiza_umbral_y_queda_consistente(tmp_path):
    v = _vault(tmp_path)
    claves = list(yaml.safe_load((v / "config/umbrales.yaml").read_text()))
    nueva_regla(v, "Corte a 20", "…", "…", "…", "Usuario 2026-11-10",
                umbrales={"corte.oferta.sin_ventas_usd": 20}, reemplaza=["R-006"], fecha="2026-11-10")
    u = yaml.safe_load((v / "config/umbrales.yaml").read_text())
    assert list(u) == claves
    assert u["corte.oferta.sin_ventas_usd"]["valor"] == 20
    assert u["corte.oferta.sin_ventas_usd"]["regla"] == "R-013"
    assert u["corte.oferta.sin_ventas_usd"]["fecha"] == "2026-11-10"
    assert u["corte.oferta.factor_cpa_be"]["regla"] == "R-013"
    meta, _ = leer(v / "wiki/reglas/R-006-corte-de-oferta-sin-ventas.md")
    assert meta["estado"] == "reemplazada" and meta["reemplazada_por"] == "R-013"
    assert "reemplazada por [[R-013-corte-a-20]]" in (v / "CLAUDE.md").read_text()
    assert consistencia(v) == []


def test_umbral_desconocido_no_escribe(tmp_path):
    v = _vault(tmp_path)
    with pytest.raises(ValueError):
        nueva_regla(v, "X", "r", "p", "c", "U", umbrales={"inventado": 1})
    assert not list((v / "wiki/reglas").glob("R-013*"))


def test_consistencia_ignora_reglas_reemplazadas(tmp_path):
    v = _vault(tmp_path)
    p = v / "wiki/reglas/R-011-paciencia-de-72-h.md"
    p.write_text(p.read_text().replace("estado: vigente", "estado: reemplazada"))
    problemas = consistencia(v)
    assert any("paciencia.con_ventas_h" in x and "ninguna regla" in x for x in problemas)
    assert not any(x.startswith("R-011:") for x in problemas)


def _json(tmp_path, **campos):
    base = {"titulo": "No cazar en diciembre", "regla": "r", "porque": "p", "como": "c", "fuente": "U"}
    f = tmp_path / "r.json"
    f.write_text(json.dumps({**base, **campos}))
    return str(f)


def test_cli_regla_ok(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    assert cli.main(["cerebro", "regla", "--json", _json(tmp_path)]) == 0
    assert "R-013-no-cazar-en-diciembre.md" in capsys.readouterr().out


def test_cli_regla_stdin(tmp_path, monkeypatch, capsys):
    import io
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    monkeypatch.setattr("sys.stdin", io.StringIO(Path(_json(tmp_path)).read_text()))
    assert cli.main(["cerebro", "regla", "--json", "-"]) == 0


def test_cli_regla_conflicto(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    j = _json(tmp_path, umbrales={"corte.oferta.sin_ventas_usd": 20})
    assert cli.main(["cerebro", "regla", "--json", j]) == 3
    assert "R-006" in capsys.readouterr().out


def test_cli_regla_errores(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    (tmp_path / "mal.json").write_text("{no")
    assert cli.main(["cerebro", "regla", "--json", str(tmp_path / "mal.json")]) == 2
    assert cli.main(["cerebro", "regla", "--json", str(tmp_path / "nada.json")]) == 2
    assert cli.main(["cerebro", "regla", "--json", _json(tmp_path, umbrales={"x.y": 1})]) == 2
    f = tmp_path / "falta.json"; f.write_text("{}")
    assert cli.main(["cerebro", "regla", "--json", str(f)]) == 2
    assert capsys.readouterr().err


def _snapshot(v):
    return {str(p.relative_to(v)): p.read_bytes() for p in v.rglob("*") if p.is_file()}


def test_claude_sin_marcador_no_cambia_nada(tmp_path):
    v = _vault(tmp_path)
    (v / "CLAUDE.md").write_text((v / "CLAUDE.md").read_text().replace("<!-- REGLAS:FIN -->", ""))
    antes = _snapshot(v)
    with pytest.raises(ValueError):
        nueva_regla(v, "Corte a 20", "r", "p", "c", "U",
                    umbrales={"corte.oferta.sin_ventas_usd": 20}, reemplaza=["R-006"])
    assert _snapshot(v) == antes


def test_index_ausente_no_cambia_nada(tmp_path):
    v = _vault(tmp_path)
    (v / "index.md").unlink()
    antes = _snapshot(v)
    with pytest.raises(ValueError):
        nueva_regla(v, "Corte a 20", "r", "p", "c", "U",
                    umbrales={"corte.oferta.sin_ventas_usd": 20}, reemplaza=["R-006"])
    assert _snapshot(v) == antes


def test_cli_vault_incompleto_sale_2(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    (v / "index.md").unlink()
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    assert cli.main(["cerebro", "regla", "--json", _json(tmp_path)]) == 2
    assert "index.md" in capsys.readouterr().err


def test_slug_vacio_y_fecha_invalida(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    assert cli.main(["cerebro", "regla", "--json", _json(tmp_path, titulo="¡¡")]) == 2
    assert cli.main(["cerebro", "regla", "--json", _json(tmp_path, fecha="10/11/2026")]) == 2
    assert not list((v / "wiki/reglas").glob("R-013*"))


def test_simular_no_escribe_y_muestra_heredados(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    j = _json(tmp_path, umbrales={"corte.oferta.sin_ventas_usd": 20}, reemplaza=["R-006"])
    antes = _snapshot(v)
    assert cli.main(["cerebro", "regla", "--simular", "--json", j]) == 0
    out = capsys.readouterr().out
    assert _snapshot(v) == antes
    assert "R-013 pasa a ser dueña de corte.oferta.factor_cpa_be (valor sin cambios)" in out
    assert "corte.oferta.sin_ventas_usd: 25 -> 20" in out
    assert "config/umbrales.yaml" in out and "R-013-no-cazar-en-diciembre" in out


def test_real_imprime_mismo_resumen(tmp_path, monkeypatch, capsys):
    v = _vault(tmp_path)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    j = _json(tmp_path, umbrales={"corte.oferta.sin_ventas_usd": 20}, reemplaza=["R-006"])
    assert cli.main(["cerebro", "regla", "--json", j]) == 0
    out = capsys.readouterr().out
    assert "R-013 pasa a ser dueña de corte.oferta.factor_cpa_be (valor sin cambios)" in out
    assert out.strip().endswith("R-013-no-cazar-en-diciembre.md")
    assert consistencia(v) == []
