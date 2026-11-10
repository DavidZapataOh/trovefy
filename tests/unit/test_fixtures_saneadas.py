import pathlib
import re

FIX = pathlib.Path(__file__).resolve().parents[1] / "fixtures/arranque"
CORREO = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
TELEFONO = re.compile(r"\+?\d[\d\s-]{8,}\d")


def test_fixtures_saneadas():
    for f in FIX.rglob("*"):
        if f.is_file():
            t = f.read_text(errors="ignore")
            assert not CORREO.search(t), f
            assert not TELEFONO.search(t), f
