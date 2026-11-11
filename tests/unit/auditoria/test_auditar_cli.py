from datetime import date

import pytest
from ejemplos_auditoria import oferta_ejemplo, paises_ejemplo
from trovify import auditar_cli, cli
from trovify.auditoria import orquestador
from trovify.auditoria.salida import escribir_auditoria
from trovify.caza import orquestador as caza_orq
from trovify.vault.andamio import crear_vault
from trovify.vault.frontmatter import escribir, leer


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "v"
    crear_vault(v)
    escribir(v / "wiki/ofertas/o-ejemplo.md", oferta_ejemplo(), "")
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return v


def falso(vistas, parada=None, tipo=None):
    def auditar(v, oferta_id, paises, frases, hoy=None, **kw):
        vistas.update(oferta=oferta_id, paises=paises, frases=frases, hoy=hoy)
        ruta = escribir_auditoria(v, oferta_id, paises_ejemplo(), hoy)
        return orquestador.ResultadoAuditoria(ruta, ruta.parent.name, paises_ejemplo(), parada, tipo)

    return auditar


def test_frases_de():
    assert auditar_cli.frases_de(['RO:fise terapie|kit terapie', "it:schede"]) == {
        "RO": ["fise terapie", "kit terapie"], "IT": ["schede"]}
    with pytest.raises(ValueError):
        auditar_cli.frases_de(["sinpais"])
    with pytest.raises(ValueError):
        auditar_cli.frases_de(["RO:|"])


def test_ejecutar(vault, monkeypatch, capsys):
    vistas = {}
    monkeypatch.setattr(orquestador, "auditar", falso(vistas))
    assert cli.main(["auditar", "ejecutar", "--oferta", "o-ejemplo", "--pais", "RO", "--pais", "IT",
                     "--frases", "RO:fise terapie|kit terapie"]) == 0
    assert vistas["paises"] == ["RO", "IT"] and vistas["frases"] == {"RO": ["fise terapie", "kit terapie"]}
    assert vistas["hoy"] is not None
    captura = capsys.readouterr()
    out = captura.out
    assert "1. RO — nota 100" in out and "no tirar: el original ya anuncia traducido" in out
    assert "La elección es tuya: dímela y la registro." in out


def test_sin_pais_usa_los_candidatos(vault, monkeypatch):
    vistas = {}
    monkeypatch.setattr(orquestador, "auditar", falso(vistas))
    assert cli.main(["auditar", "ejecutar", "--oferta", "o-ejemplo"]) == 0
    assert vistas["paises"] is None


@pytest.mark.parametrize(("tipo", "codigo", "texto"), [("meta", 1, "PARADA"), ("errores", 3, "INTERRUMPIDA"),
                                                       ("cuota", 0, "Cuota del día agotada")])
def test_codigos_de_salida(vault, monkeypatch, capsys, tipo, codigo, texto):
    monkeypatch.setattr(orquestador, "auditar", falso({}, parada="motivo", tipo=tipo))
    assert cli.main(["auditar", "ejecutar", "--oferta", "o-ejemplo"]) == codigo
    assert texto in capsys.readouterr().out


def test_errores_de_uso(vault, monkeypatch, capsys):
    assert cli.main(["auditar", "ejecutar", "--oferta", "o-ejemplo", "--frases", "mal"]) == 2

    def ocupado(*_a, **_k):
        raise caza_orq.CazaEnCurso("otra caza está en marcha en este cerebro")

    monkeypatch.setattr(orquestador, "auditar", ocupado)
    assert cli.main(["auditar", "ejecutar", "--oferta", "o-ejemplo"]) == 2
    assert "otra caza" in capsys.readouterr().err


def test_elegir(vault, monkeypatch, capsys):
    monkeypatch.setattr(caza_orq, "hoy_negocio", lambda: date(2026, 11, 10))
    p = escribir_auditoria(vault, "o-ejemplo", paises_ejemplo(), date(2026, 11, 10)).parent.name
    assert cli.main(["auditar", "elegir", "--producto", p, "--pais", "fr", "--cita", "Quiero Francia igual"]) == 0
    out = capsys.readouterr().out
    assert "Advertencia: el original ya anuncia traducido" in out and "aprobado" in out
    meta, _ = leer(vault / "productos" / p / "PRODUCTO.md")
    assert meta["paises"]["FR"]["estado"] == "aprobado"
    assert cli.main(["auditar", "elegir", "--producto", "p-0099-x", "--pais", "RO", "--cita", "x"]) == 2


def test_frases_de_un_pais_no_auditado_avisa(vault, monkeypatch, capsys):
    monkeypatch.setattr(orquestador, "auditar", falso({}))
    assert cli.main(["auditar", "ejecutar", "--oferta", "o-ejemplo", "--frases", "PL:a b|c d"]) == 0
    assert "PL" in capsys.readouterr().err


def test_elegir_producto_mal_escrito(vault, capsys):
    assert cli.main(["auditar", "elegir", "--producto", "../x", "--pais", "RO", "--cita", "x"]) == 2


def test_elegir_un_pais_muerto_no_dice_aprobado(vault, monkeypatch, capsys):
    monkeypatch.setattr(caza_orq, "hoy_negocio", lambda: date(2026, 11, 10))
    p = escribir_auditoria(vault, "o-ejemplo", paises_ejemplo(), date(2026, 11, 10)).parent.name
    meta, cuerpo = leer(vault / "productos" / p / "PRODUCTO.md")
    meta["paises"]["RO"]["estado"] = "MUERTO"
    escribir(vault / "productos" / p / "PRODUCTO.md", meta, cuerpo)
    assert cli.main(["auditar", "elegir", "--producto", p, "--pais", "RO", "--cita", "Rumanía otra vez"]) == 0
    out = capsys.readouterr().out
    assert "queda «aprobado»" not in out and "zona horaria" not in out
    assert "Decisión registrada" in out or "Elección registrada" in out
    assert "el estado de RO sigue siendo MUERTO" in out
