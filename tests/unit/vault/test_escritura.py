from datetime import datetime
from multiprocessing import Pool
from zoneinfo import ZoneInfo

from trovify.vault.escritura import anadir_log, escribir_atomico


def test_escritura_atomica_crea_padres(tmp_path):
    ruta = tmp_path / "wiki/caza/2026-11-10/europa.md"
    escribir_atomico(ruta, "hola")
    assert ruta.read_text() == "hola"
    assert list(ruta.parent.glob("*.tmp*")) == []


def test_linea_de_log(tmp_path):
    ahora = datetime(2026, 11, 10, 6, 30, tzinfo=ZoneInfo("America/Bogota"))
    linea = anadir_log(tmp_path, "cazar", "3 ofertas nuevas", ["wiki/caza/2026-11-10/europa.md"], 12000, ahora)
    assert linea == "- 2026-11-10 06:30 COT · cazar · 3 ofertas nuevas · wiki/caza/2026-11-10/europa.md · ~12000 tokens"
    assert (tmp_path / "log.md").read_text().endswith(linea + "\n")


def _escribe(args):
    vault, i = args
    anadir_log(vault, "prueba", f"linea {i}", [])


def test_log_concurrente_no_pierde_lineas(tmp_path):
    with Pool(8) as p:
        p.map(_escribe, [(tmp_path, i) for i in range(200)])
    assert len((tmp_path / "log.md").read_text().splitlines()) == 200
