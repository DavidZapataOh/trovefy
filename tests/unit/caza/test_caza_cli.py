from datetime import date
from pathlib import Path

import pytest
from ejemplos import ejecucion_ejemplo
from trovefy import cli
from trovefy.caza import orquestador
from trovefy.vault.andamio import crear_vault


@pytest.fixture
def vault(tmp_path, monkeypatch):
    v = tmp_path / "v"
    crear_vault(v)
    monkeypatch.setenv("TROVEFY_VAULT", str(v))
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

    from trovefy.caza.salida import Consulta
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
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida
    vistas = {}

    def falso(v, oferta, pais, frases, **kw):
        vistas.update(oferta=oferta, pais=pais, frases=frases, **kw)
        return HuecoPais(pais, Medida(0), "sin_traducir", True, ["u"]), None, None

    monkeypatch.setattr(orquestador, "medir_hueco", falso)
    assert cli.main(["caza", "hueco", "--oferta", "o-x", "--pais", "RO", "--frase", "a b", "--frase", "c d"]) == 0
    assert vistas["frases"] == ["a b", "c d"] and vistas["pais"] == "RO"
    assert "hueco" in capsys.readouterr().out.lower()


def test_hueco_cli_parada(vault, monkeypatch, capsys):
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida
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
    from trovefy.caza import cliente as m

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
    from trovefy.caza.hueco import HuecoPais
    from trovefy.caza.senales import Medida
    monkeypatch.setattr(orquestador, "medir_hueco", lambda *a, **k: (
        HuecoPais("RO", Medida(None, "no medido: cuota"), "no_medido", None, []),
        "cuota del día agotada (Presupuesto del día agotado)", "cuota"))
    assert cli.main(["caza", "hueco", "--oferta", "o-x", "--pais", "RO", "--frase", "a b", "--frase", "c d"]) == 0
    out = capsys.readouterr().out
    assert "PARADA" not in out and "cuota" in out.lower()


def test_resumen_pone_las_ya_vistas_aparte():
    import dataclasses

    from trovefy.caza.filtros import Descarte
    e = ejecucion_ejemplo()
    r = e.resultados[0]
    vista = dataclasses.replace(r, oferta=dataclasses.replace(r.oferta, oferta_id="o-vista"), decision="descartada",
                                descarte=Descarte("ya_visto", "ya visto"), explicacion="ya_visto: ya visto")
    texto = orquestador.resumen(dataclasses.replace(e, resultados=[*e.resultados, vista]), 20)
    assert "Ya vistas (ya en el cerebro; su ficha manda): o-vista (RO)" in texto
    assert "o-vista" not in texto.split("Descartadas:")[1].split("Ya vistas")[0]


def test_rutina_omitida_si_otra_caza_esta_en_curso(vault, monkeypatch, capsys):
    def ocupado(*a, **k):
        raise orquestador.CazaEnCurso("otra caza está en marcha en este cerebro")

    monkeypatch.setattr(orquestador, "ejecutar", ocupado)
    monkeypatch.setattr(orquestador, "hoy_negocio", lambda: date(2026, 11, 10))
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar", "--rutina"]) == 4
    assert not (vault / "rutinas/log/2026-11-10/ok").exists()
    assert "omitida: otra caza en curso" in (vault / "rutinas/log/2026-11-10/caza.md").read_text()
    assert cli.main(["caza", "ejecutar", "--modo", "vigilar"]) == 2  # sin --rutina: error normal


def test_caza_yaml_con_no_sin_comillas_lee_noruega(vault):
    from trovefy import caza_cli
    from trovefy.caza import orquestador as caza_orq

    ruta = vault / "config/caza.yaml"
    ruta.write_text(ruta.read_text(encoding="utf-8").replace('"NO"', "NO"), encoding="utf-8")
    assert ", NO," in ruta.read_text(encoding="utf-8")
    assert "NO" in caza_cli._config(vault)["regiones"]["europa"]
    ruta.write_text("perfil: no\n", encoding="utf-8")
    assert caza_orq._perfil_config(vault) == "no"


def test_plantilla_caza_yaml_lleva_no_entre_comillas():
    from trovefy.vault.andamio import PLANTILLA

    assert '"NO"' in (PLANTILLA / "config/caza.yaml").read_text(encoding="utf-8")
    assert '\n"NO":' in (PLANTILLA / "config/mercados.yaml").read_text(encoding="utf-8")


FIX_MCP = Path(__file__).resolve().parents[2] / "fixtures/biblioteca/mcp_ads_library_search.json"


def _base(*extra):
    return ["caza", "ejecutar", "--modo", "nicho", "--region", "europa", *extra]


def test_desde_mcp_usa_el_lote_y_dice_la_via(vault, monkeypatch, capsys):
    from trovefy.caza.mcp import ClienteMcp

    vistas = {}

    def falso(v, modo, consultas, perfil, max_nuevas, page_ids=None, cliente=None, **kw):
        vistas.update(consultas=consultas, cliente=cliente)
        e = ejecucion_ejemplo()
        e.via, e.creditos = {"mcp": 1}, None
        return e

    monkeypatch.setattr(orquestador, "ejecutar", falso)
    assert cli.main(_base("--desde-mcp", str(FIX_MCP))) == 0
    assert vistas["consultas"] == [("RO", "fise de lucru")]
    assert isinstance(vistas["cliente"], ClienteMcp) and vistas["cliente"].respaldo is None
    assert "MCP oficial 1" in capsys.readouterr().out


def test_respaldo_publico_se_pasa_al_cliente(vault, monkeypatch):
    vistas = {}

    def falso(v, modo, consultas, perfil, max_nuevas, page_ids=None, cliente=None, **kw):
        vistas["cliente"] = cliente
        return ejecucion_ejemplo()

    monkeypatch.setattr(orquestador, "ejecutar", falso)
    assert cli.main(_base("--desde-mcp", str(FIX_MCP), "--respaldo-publico")) == 0
    assert vistas["cliente"].respaldo is not None


def test_faltan_se_escriben(vault, monkeypatch, capsys):
    def falso(v, modo, consultas, perfil, max_nuevas, page_ids=None, cliente=None, **kw):
        cliente.buscar("BG", q="x")
        return ejecucion_ejemplo()

    monkeypatch.setattr(orquestador, "ejecutar", falso)
    assert cli.main(_base("--desde-mcp", str(FIX_MCP))) == 0
    archivos = list((vault / "data/caza/mcp").glob("faltan-*.json"))
    assert len(archivos) == 1
    import json

    assert json.loads(archivos[0].read_text()) == [{"pais": "BG", "q": "x", "page_id": None, "estado": "active"}]
    out = capsys.readouterr().out
    assert "Faltaron 1 búsquedas en el lote del MCP; quedan «no medido»" in out


def test_rutina_no_usa_mcp(vault, capsys):
    assert cli.main(_base("--desde-mcp", str(FIX_MCP), "--rutina")) == 2
    assert "la rutina no usa el MCP" in capsys.readouterr().err


def test_respaldo_sin_desde_mcp_es_error(vault):
    assert cli.main(_base("--respaldo-publico", "--consulta", "RO:x")) == 2


def test_lote_invalido_error_claro(vault, tmp_path, capsys):
    import json

    d = json.loads(FIX_MCP.read_text())
    d["herramienta"] = "mcp__meta-ads__ads_get_campaigns"
    p = tmp_path / "otro.json"
    p.write_text(json.dumps(d))
    assert cli.main(_base("--desde-mcp", str(p))) == 2
    assert "ads_library_search" in capsys.readouterr().err


def test_respaldo_publico_cuenta_mcp_y_publico_sin_stub_del_orquestador(vault, monkeypatch, capsys):
    """Orquestador real: RO sale del lote del MCP (no gasta cuota) y BG del cliente público (sí la gasta)."""
    from datetime import UTC, datetime

    from trovefy.caza import cliente as mod_cliente
    from trovefy.caza.modelo import ResultadoBusqueda

    class PublicoFalso:
        def __init__(self, presupuesto, cache=None):
            self.presupuesto = presupuesto

        def buscar(self, pais, q=None, page_id=None, estado="active", max_anuncios=60, completa=False):
            self.presupuesto.antes_de_buscar()
            self.presupuesto.vacios += 1
            return ResultadoBusqueda("vacio", "https://www.facebook.com/ads/library/?q=x", 0, [], None,
                                     datetime.now(UTC), completo=True, via="playwright", total_exacto=True)

    monkeypatch.setattr(mod_cliente, "ClienteBibliotecaPublica", PublicoFalso)
    codigo = cli.main(_base("--desde-mcp", str(FIX_MCP), "--respaldo-publico",
                            "--consulta", "RO:fise de lucru", "--consulta", "BG:x"))
    out = capsys.readouterr().out
    assert codigo == 0, out
    import re

    m = re.search(r"Búsquedas en la Biblioteca: (\d+) \(MCP oficial (\d+), Playwright (\d+)\)", out)
    assert m, out
    total, mcp, publico = map(int, m.groups())
    assert mcp >= 1 and publico >= 1 and total == mcp + publico


def test_faltan_usa_la_hora_del_negocio_con_zona(vault, monkeypatch):
    import time
    from datetime import datetime

    from trovefy.caza_cli import _escribir_faltan
    from trovefy.vault.escritura import ZONA_NEGOCIO

    monkeypatch.setenv("TZ", "Pacific/Kiritimati")  # UTC+14: con la hora local ingenua el nombre sería otro
    time.tzset()
    try:
        antes = datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d-%H")
        ruta = _escribir_faltan(vault, [])
        despues = datetime.now(ZONA_NEGOCIO).strftime("%Y-%m-%d-%H")
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()
    assert ruta.name[len("faltan-"):len("faltan-") + 13] in (antes, despues)
