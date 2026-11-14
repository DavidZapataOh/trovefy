"""CLI `trovefy economia` (plan 16, Tarea 9)."""

from datetime import date

import pytest
from trovefy import cli, economia_cli

HOY = date(2026, 11, 13)


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "v"
    (v / "config").mkdir(parents=True)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(economia_cli, "_hoy", lambda: HOY)
    return v


def test_iniciar(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    assert (vault / "config/economia.yaml").is_file()
    assert "config/economia.yaml" in capsys.readouterr().out
    antes = (vault / "config/economia.yaml").read_text(encoding="utf-8")
    assert cli.main(["economia", "iniciar"]) == 0  # ya existe: no se toca
    assert "ya existe" in capsys.readouterr().out
    assert (vault / "config/economia.yaml").read_text(encoding="utf-8") == antes


def test_economia_fijar_y_ver(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    fuente = "https://precios.whop.test/tarifas"
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "0.03",
                     "--fuente", fuente]) == 0
    capsys.readouterr()
    assert cli.main(["economia", "ver"]) == 0
    out = capsys.readouterr().out
    linea = next(x for x in out.splitlines() if "plataformas.whop.comision_pct" in x)
    assert "0,03" in linea and fuente in linea and "2026-11-13" in linea
    assert "no medido" in next(x for x in out.splitlines() if x.lstrip().startswith("ruta_activa"))


def test_fijar_null_vuelve_a_no_medido(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "0.03",
                     "--fuente", "https://a.test/"]) == 0
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "null",
                     "--fuente", "pendiente de verificar"]) == 0
    capsys.readouterr()
    assert cli.main(["economia", "ver"]) == 0
    linea = next(x for x in capsys.readouterr().out.splitlines() if "plataformas.whop.comision_pct" in x)
    assert "no medido" in linea and "pendiente de verificar" in linea


def test_fijar_clave_inexistente(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    antes = (vault / "config/economia.yaml").read_text(encoding="utf-8")
    assert cli.main(["economia", "fijar", "--clave", "plataformas.inventada.x", "--valor", "1",
                     "--fuente", "f"]) == 2
    err = capsys.readouterr().err
    assert err.startswith("Error: ") and "plataformas.inventada.x" in err
    assert (vault / "config/economia.yaml").read_text(encoding="utf-8") == antes


def test_fijar_valor_invalido(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    antes = (vault / "config/economia.yaml").read_bytes()
    assert cli.main(["economia", "fijar", "--clave", "plataformas.whop.comision_pct", "--valor", "1.5",
                     "--fuente", "https://a.test/"]) == 2
    assert capsys.readouterr().err.startswith("Error: ")
    assert (vault / "config/economia.yaml").read_bytes() == antes


def test_ver_sin_archivo(vault, capsys):
    assert cli.main(["economia", "ver"]) == 2
    assert "trovefy economia iniciar" in capsys.readouterr().err


SECRETO = "sk" + "-" + "q" * 24
CLAVE = "plataformas.whop.comision_pct"


def _fijar(*, clave=CLAVE, valor="0.03", fuente="https://a.test/"):
    return cli.main(["economia", "fijar", "--clave", clave, "--valor", valor, "--fuente", fuente])


@pytest.mark.parametrize("valor", ["", "   "])
def test_fijar_valor_en_blanco(vault, capsys, valor):
    """L-1: el valor en blanco no es «no medido» por accidente."""
    assert cli.main(["economia", "iniciar"]) == 0
    antes = (vault / "config/economia.yaml").read_bytes()
    assert _fijar(valor=valor) == 2
    assert "usa `null` para no medido" in capsys.readouterr().err
    assert (vault / "config/economia.yaml").read_bytes() == antes


def test_fijar_secreto_en_la_fuente(vault, capsys):
    """L-7: un secreto en --fuente sale 2, no se repite y no se escribe nada."""
    assert cli.main(["economia", "iniciar"]) == 0
    antes = (vault / "config/economia.yaml").read_bytes()
    assert _fijar(fuente=f"https://a.test/?token={SECRETO}") == 2
    salida = capsys.readouterr()
    assert salida.err.startswith("Error: ")
    assert SECRETO not in salida.err and SECRETO not in salida.out
    assert (vault / "config/economia.yaml").read_bytes() == antes


@pytest.mark.parametrize("fuente", ["precios de whop", "www.whop.test", "ftp://whop.test/"])
def test_fijar_plataforma_exige_url(vault, capsys, fuente):
    """L-5: plataformas.* con valor no nulo exige una fuente http(s)://."""
    assert cli.main(["economia", "iniciar"]) == 0
    antes = (vault / "config/economia.yaml").read_bytes()
    assert _fijar(fuente=fuente) == 2
    assert "http" in capsys.readouterr().err
    assert (vault / "config/economia.yaml").read_bytes() == antes


def test_fijar_url_no_exigida_fuera_de_plataformas_ni_en_null(vault, capsys):
    assert cli.main(["economia", "iniciar"]) == 0
    assert _fijar(valor="null", fuente="pendiente de verificar") == 0
    assert _fijar(clave="reembolsos_pct", valor="0.05", fuente="diseño §4.6") == 0
    assert _fijar(fuente="HTTPS://precios.whop.test/") == 0


def test_fijar_eco_con_el_formato_de_ver(vault, capsys):
    """Nit: `fijar` repite el valor ya interpretado, con el mismo formato que `ver`."""
    assert cli.main(["economia", "iniciar"]) == 0
    capsys.readouterr()
    assert _fijar(valor="0.030") == 0
    eco = capsys.readouterr().out
    assert cli.main(["economia", "ver"]) == 0
    linea = next(x for x in capsys.readouterr().out.splitlines() if x.startswith(CLAVE))
    valor_ver = linea.split(": ", 1)[1].split(" · ")[0]
    assert valor_ver == "0,03"
    assert f"{CLAVE} = {valor_ver} " in eco


def test_ctrl_c_sale_3_sin_traza(vault, capsys, monkeypatch):
    """L-2: Ctrl-C sale con 3 y sin traceback."""
    from trovefy.economia import config

    assert cli.main(["economia", "iniciar"]) == 0

    def _interrumpe(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(config, "fijar", _interrumpe)
    assert _fijar() == 3
    err = capsys.readouterr().err
    assert "Traceback" not in err and "Ctrl-C" in err


def test_keyerror_inesperado_no_es_clave_desconocida(vault, capsys, monkeypatch):
    """L-2: solo el KeyError de la búsqueda de la clave en `fijar` es «clave desconocida» (2)."""
    from trovefy.economia import config

    assert cli.main(["economia", "iniciar"]) == 0

    def _roto(*a, **k):
        raise KeyError("interno")

    monkeypatch.setattr(config, "cargar_economia", _roto)
    assert cli.main(["economia", "ver"]) == 3
    assert "fallo inesperado (KeyError)" in capsys.readouterr().err
