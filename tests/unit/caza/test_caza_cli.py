from datetime import date

import pytest
from ejemplos import ejecucion_ejemplo
from trovify import cli
from trovify.caza import orquestador
from trovify.vault.andamio import crear_vault


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "v"
    crear_vault(v)
    monkeypatch.setenv("TROVIFY_VAULT", str(v))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    return v


def test_ejecutar_imprime_resumen(vault, monkeypatch, capsys):
    vistas = {}

    def falso(v, modo, consultas, perfil, max_nuevas, page_ids=None, **kw):
        vistas.update(modo=modo, consultas=consultas, perfil=perfil, max=max_nuevas, page_ids=page_ids, **kw)
        e = ejecucion_ejemplo()
        e.via, e.creditos = {"firecrawl": 4, "playwright": 1}, 4
        return e

    monkeypatch.setattr(orquestador, "ejecutar", falso)
    assert cli.main(["caza", "ejecutar", "--modo", "nicho", "--region", "europa",
                     "--consulta", "RO:caiet de exercitii", "--consulta", "MD:fise"]) == 0
    assert vistas["consultas"] == [("RO", "caiet de exercitii"), ("MD", "fise")]
    assert vistas["perfil"] == "tomi" and vistas["max"] == 3 and vistas["region"] == "europa"
    out = capsys.readouterr().out
    assert "Búsquedas" in out and "Firecrawl 4" in out and "créditos de Firecrawl: 4" in out
    assert "B:" in out and "Descartadas" in out and "RO" in out


def test_consulta_mal_formada(vault, capsys):
    assert cli.main(["caza", "ejecutar", "--modo", "nicho", "--region", "europa", "--consulta", "sinpais"]) == 2
    assert "PAIS:FRASE" in capsys.readouterr().err


def test_region_desconocida(vault, capsys):
    assert cli.main(["caza", "ejecutar", "--modo", "oferta", "--region", "marte", "--page-id", "1"]) == 2
    assert "marte" in capsys.readouterr().err


def test_resumen_marca_palabras_a_reescribir():
    from dataclasses import replace

    from trovify.caza.salida import Consulta
    e = replace(ejecucion_ejemplo(), consultas=[Consulta("poca", "RO", 3, "u"), Consulta("bien", "RO", 90, "u")])
    texto = orquestador.resumen(e, 20)
    linea = next(x for x in texto.splitlines() if "reescribir" in x)
    assert "«poca»" in linea and "«bien»" not in linea


def test_rutina_deja_registro(vault, monkeypatch):
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: ejecucion_ejemplo())
    monkeypatch.setattr(orquestador, "hoy_negocio", lambda: date(2026, 11, 10))
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--region", "europa", "--rutina"]) == 0
    assert (vault / "rutinas/log/2026-11-10/ok").exists()
    assert "Búsquedas" in (vault / "rutinas/log/2026-11-10/caza.md").read_text()


def test_rutina_parada_no_deja_ok(vault, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: replace(ejecucion_ejemplo(), parada="bloqueo"))
    monkeypatch.setattr(orquestador, "hoy_negocio", lambda: date(2026, 11, 10))
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--region", "europa", "--rutina"]) == 1
    assert not (vault / "rutinas/log/2026-11-10/ok").exists()


def test_hueco_cli(vault, monkeypatch, capsys):
    from trovify.caza.hueco import HuecoPais
    from trovify.caza.senales import Medida
    vistas = {}

    def falso(v, oferta, pais, frases, **kw):
        vistas.update(oferta=oferta, pais=pais, frases=frases, **kw)
        return HuecoPais(pais, Medida(0), "sin_traducir", True, ["u"]), None, None

    monkeypatch.setattr(orquestador, "medir_hueco", falso)
    assert cli.main(["caza", "hueco", "--oferta", "o-x", "--pais", "RO", "--frase", "a b", "--frase", "c d"]) == 0
    assert vistas["frases"] == ["a b", "c d"] and vistas["pais"] == "RO"
    assert "hueco" in capsys.readouterr().out.lower()


def test_hueco_cli_parada(vault, monkeypatch, capsys):
    from trovify.caza.hueco import HuecoPais
    from trovify.caza.senales import Medida
    monkeypatch.setattr(orquestador, "medir_hueco", lambda *a, **k: (
        HuecoPais("RO", Medida(None, "no medido: bloqueo"), "no_medido", None, []), "bloqueo de Meta: captcha",
        "meta"))
    assert cli.main(["caza", "hueco", "--oferta", "o-x", "--pais", "RO", "--frase", "a b", "--frase", "c d"]) == 1
    assert "PARADA" in capsys.readouterr().out


def test_cuotas_de_la_rutina_y_de_vigilar(vault, monkeypatch):
    vistas = {}
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: vistas.update(k) or ejecucion_ejemplo())
    monkeypatch.setattr(orquestador, "hoy_negocio", lambda: date(2026, 11, 10))
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--region", "europa", "--rutina"]) == 0
    assert vistas["max_busquedas_rutina"] == 20 and vistas["max_vigiladas"] == 6
    vistas.clear()
    assert cli.main(["caza", "ejecutar", "--modo", "nicho", "--region", "europa", "--consulta", "RO:x"]) == 0
    assert vistas["max_busquedas_rutina"] is None  # la sesión del usuario no tiene cuota de rutina


def test_caza_yaml_se_crea_si_falta(vault, monkeypatch):
    (vault / "config/caza.yaml").unlink()
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: ejecucion_ejemplo())
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--region", "europa"]) == 0
    assert "rutina" in (vault / "config/caza.yaml").read_text()


def test_perfil_desconocido_sale_con_2_sin_buscar(vault, capsys, monkeypatch):
    from trovify.caza import cliente as m

    def nunca(*a, **k):
        raise AssertionError("no debe crear el cliente")

    monkeypatch.setattr(m, "ClienteBibliotecaPublica", nunca)
    assert cli.main(["caza", "ejecutar", "--modo", "nicho", "--region", "europa", "--consulta", "RO:fise",
                     "--perfil", "Tommi"]) == 2
    err = capsys.readouterr().err
    assert "perfil desconocido" in err and "tomi, santino, europa_caro" in err


# --- ola final: I4/I5 finales de la ejecución y etiqueta de vigilancia --------------------------


def test_rutina_con_cuota_agotada_termina_bien(vault, monkeypatch, capsys):
    from dataclasses import replace
    e = replace(ejecucion_ejemplo(), cuota="Cuota de la rutina agotada: 20 de 20", pendientes=3,
                pendientes_por={"tope_nuevas": 1, "cuota": 2})
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: e)
    monkeypatch.setattr(orquestador, "hoy_negocio", lambda: date(2026, 11, 10))
    assert cli.main(["caza", "ejecutar", "--modo", "barrido", "--region", "europa", "--consulta", "RO:x",
                     "--rutina"]) == 0
    out = capsys.readouterr().out
    assert "PARADA" not in out and "Cuota del día agotada" in out
    assert "Sin evaluar: 3 candidatas: 1 por el tope" in out and "2 porque no quedaban búsquedas hoy" in out
    assert (vault / "rutinas/log/2026-11-10/ok").exists()


def test_racha_de_errores_es_interrupcion_no_parada(vault, monkeypatch, capsys):
    from dataclasses import replace
    e = replace(ejecucion_ejemplo(), parada="ParadaPorErrores: 3 errores", tipo_parada="errores")
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: e)
    monkeypatch.setattr(orquestador, "hoy_negocio", lambda: date(2026, 11, 10))
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--rutina"]) == 3
    out = capsys.readouterr().out
    assert "PARADA" not in out and "INTERRUMPIDA" in out
    assert not (vault / "rutinas/log/2026-11-10/ok").exists()
    assert "interrumpida" in (vault / "rutinas/log/2026-11-10/caza.md").read_text()


def test_vigilar_sin_region_se_llama_vigilancia_y_sin_tope_fuera_de_la_rutina(vault, monkeypatch):
    vistas = {}
    monkeypatch.setattr(orquestador, "ejecutar", lambda *a, **k: vistas.update(k) or ejecucion_ejemplo())
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar"]) == 0
    assert vistas["region"] == "vigilancia" and vistas["max_vigiladas"] is None
    vistas.clear()
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--region", "europa", "--rutina"]) == 0
    assert vistas["region"] == "vigilancia" and vistas["max_vigiladas"] == 6


def test_region_obligatoria_fuera_de_vigilar(vault, capsys):
    assert cli.main(["caza", "ejecutar", "--modo", "nicho", "--consulta", "RO:x"]) == 2
    assert "--region" in capsys.readouterr().err


def test_hueco_cli_cuota_no_es_parada(vault, monkeypatch, capsys):
    from trovify.caza.hueco import HuecoPais
    from trovify.caza.senales import Medida
    monkeypatch.setattr(orquestador, "medir_hueco", lambda *a, **k: (
        HuecoPais("RO", Medida(None, "no medido: cuota"), "no_medido", None, []),
        "cuota del día agotada (Presupuesto del día agotado)", "cuota"))
    assert cli.main(["caza", "hueco", "--oferta", "o-x", "--pais", "RO", "--frase", "a b", "--frase", "c d"]) == 0
    out = capsys.readouterr().out
    assert "PARADA" not in out and "cuota" in out.lower()


def test_resumen_pone_las_ya_vistas_aparte():
    import dataclasses

    from trovify.caza.filtros import Descarte
    e = ejecucion_ejemplo()
    r = e.resultados[0]
    vista = dataclasses.replace(r, oferta=dataclasses.replace(r.oferta, oferta_id="o-vista"), decision="descartada",
                                descarte=Descarte("ya_visto", "ya visto"), explicacion="ya_visto: ya visto")
    texto = orquestador.resumen(dataclasses.replace(e, resultados=[*e.resultados, vista]), 20)
    assert "Ya vistas (ya en el cerebro; su ficha manda): o-vista (RO)" in texto
    assert "o-vista" not in texto.split("Descartadas:")[1].split("Ya vistas")[0]
