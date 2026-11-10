from trovify.arranque.verificadores import REGISTRO
from trovify.vault.frontmatter import escribir

LINK = "https://www.facebook.com/ads/library/?view_all_page_id=102506312071455&country=DE"


def test_caza_con_enlace_reproducible(tmp_path):
    escribir(tmp_path / "wiki/ofertas/o-therapy-toolkit.md",
             {"tipo": "oferta", "paises": {"DE": {"link_biblioteca": LINK}}}, "")
    r = REGISTRO["02"](tmp_path)
    assert r.ok is True and "o-therapy-toolkit" in r.evidencia[0]
    assert LINK in r.evidencia[1]
    assert r.datos == {"oferta": "o-therapy-toolkit"}


def test_caza_vacia(tmp_path):
    r = REGISTRO["02"](tmp_path)
    assert r.ok is False
    assert "/trovify:cazar --modo nicho" in r.arreglos[0] and "plan 07" in r.arreglos[0].lower()


def test_enlace_ajeno_no_vale(tmp_path):
    escribir(tmp_path / "wiki/ofertas/o-x.md",
             {"paises": {"DE": {"link_biblioteca": "https://example.com/ads/library/"}}}, "")
    assert REGISTRO["02"](tmp_path).ok is False


def test_ficha_mal_formada_se_salta(tmp_path):
    (tmp_path / "wiki/ofertas").mkdir(parents=True)
    (tmp_path / "wiki/ofertas/a-rota.md").write_text("---\n: [\nmal\n---\n")
    escribir(tmp_path / "wiki/ofertas/b-paises-lista.md", {"paises": ["DE"]}, "")
    escribir(tmp_path / "wiki/ofertas/c-pais-roto.md", {"paises": {"DE": None, "FR": {"link_biblioteca": 5}}}, "")
    escribir(tmp_path / "wiki/ofertas/d-buena.md", {"paises": {"ES": {"link_biblioteca": LINK}}}, "")
    r = REGISTRO["02"](tmp_path)
    assert r.ok is True and r.datos == {"oferta": "d-buena"}
