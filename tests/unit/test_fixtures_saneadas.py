import pathlib
import re

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures/arranque"
CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# ID de la página pública de pruebas (Therapy Toolkit): es de una página pública, no del usuario.
ID_PUBLICO = "102506312071455"
TELEFONO = re.compile(r"\+?\d[\d\s-]{8,}\d")


def test_fixtures_saneadas():
    for f in FIX.rglob("*"):
        if f.is_file():
            t = f.read_text(errors="ignore").replace(ID_PUBLICO, "")
            assert not CORREO.search(t), f
            assert not TELEFONO.search(t), f
