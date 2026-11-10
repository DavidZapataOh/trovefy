import pathlib

import pytest
import yaml
from trovify.config.umbrales import UmbralFaltante, UmbralInvalido, cargar, valor

PLANTILLA = pathlib.Path(__file__).resolve().parents[3] / "templates/cerebro/config/umbrales.yaml"


def test_semilla_carga_y_respeta_pu01():
    u = cargar(PLANTILLA)
    assert u["corte.oferta.sin_ventas_usd"].valor == 25
    assert u["test.spend_cap_usd"].valor == 30
    assert u["test.spend_cap_prorroga_usd"].valor == 55
    assert u["caza.perfil.tomi.c8_min"].valor == 15
    assert len(u) == 60


def test_umbral_incompleto_falla_con_nombre(tmp_path):
    ruta = tmp_path / "u.yaml"
    ruta.write_text(yaml.safe_dump({"roas.apagar": {"valor": "uno", "fuente": "x", "fecha": "2026-11-09", "gana_sobre": "-", "regla": "R-008"}}))
    with pytest.raises(UmbralInvalido, match="roas.apagar"):
        cargar(ruta)


def _escribir(tmp_path, entrada):
    ruta = tmp_path / "u.yaml"
    ruta.write_text(yaml.safe_dump({"a.b": entrada}))
    return ruta


BASE = {"valor": 1, "fuente": "x", "fecha": "2026-11-09", "gana_sobre": "—", "regla": "R-001"}


@pytest.mark.parametrize("campo", list(BASE))
def test_campo_faltante(tmp_path, campo):
    e = {k: v for k, v in BASE.items() if k != campo}
    with pytest.raises(UmbralInvalido, match="a.b"):
        cargar(_escribir(tmp_path, e))


def test_bool_y_regla_mala(tmp_path):
    with pytest.raises(UmbralInvalido, match="a.b"):
        cargar(_escribir(tmp_path, {**BASE, "valor": True}))
    with pytest.raises(UmbralInvalido, match="a.b"):
        cargar(_escribir(tmp_path, {**BASE, "regla": "R-1"}))


def test_valor_lee_del_vault_y_falta(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/umbrales.yaml").write_text(PLANTILLA.read_text(encoding="utf-8"), encoding="utf-8")
    assert valor(tmp_path, "roas.apagar") == 1.4
    with pytest.raises(UmbralFaltante, match="no.existe"):
        valor(tmp_path, "no.existe")


def test_valor_no_finito_se_rechaza(tmp_path):
    import pytest
    from trovify.config.umbrales import UmbralInvalido, cargar
    for malo in (".nan", ".inf", "-.inf"):
        p = tmp_path / "u.yaml"
        p.write_text(f'a.b:\n  valor: {malo}\n  fuente: "x"\n  fecha: "2026-11-09"\n  gana_sobre: "—"\n  regla: R-001\n')
        with pytest.raises(UmbralInvalido):
            cargar(p)
