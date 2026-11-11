from trovefy.vault.frontmatter import escribir, leer


def test_ida_y_vuelta(tmp_path):
    ruta = tmp_path / "wiki/ofertas/o-1.md"
    escribir(ruta, {"tipo": "oferta", "fecha": "2026-11-10"}, "# Oferta\n")
    meta, cuerpo = leer(ruta)
    assert meta == {"tipo": "oferta", "fecha": "2026-11-10"} and cuerpo == "# Oferta\n"


def test_sin_frontmatter(tmp_path):
    ruta = tmp_path / "a.md"
    ruta.write_text("solo cuerpo\n")
    assert leer(ruta) == ({}, "solo cuerpo\n")


def test_frontmatter_con_crlf(tmp_path):
    ruta = tmp_path / "a.md"
    ruta.write_bytes(b"---\r\ntipo: regla\r\nid: R-001\r\n---\r\ncuerpo\r\n")
    meta, cuerpo = leer(ruta)
    assert meta == {"tipo": "regla", "id": "R-001"} and cuerpo == "cuerpo\n"
    ruta.write_bytes(b"---\r\n---\r\nsolo\r\n")
    assert leer(ruta) == ({}, "solo\n")
