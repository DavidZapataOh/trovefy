import hashlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3] / "vendor/claude-video"


def test_vendor_intacto():
    for linea in (RAIZ / "MANIFEST.sha256").read_text().splitlines():
        suma, rel = linea.split(maxsplit=1)
        assert hashlib.sha256((RAIZ / rel).read_bytes()).hexdigest() == suma, rel


def test_vendor_fijado_y_con_licencia():
    v = (RAIZ / "VENDOR.md").read_text()
    assert "03ceb42f7fa2c4439aca01752118044baabffb8f" in v
    assert (RAIZ / "LICENSE").read_text().startswith("MIT License")


def test_vendor_sin_hooks_ni_skill():
    assert not list(RAIZ.rglob("hooks.json")) and not list(RAIZ.rglob("SKILL.md"))


def test_manifest_cubre_todo():
    listados = {
        linea.split(maxsplit=1)[1]
        for linea in (RAIZ / "MANIFEST.sha256").read_text().splitlines()
    }
    reales = {str(p.relative_to(RAIZ)) for p in RAIZ.rglob("*.py")}
    assert reales <= listados and "skills/watch/scripts/watch.py" in listados
    assert reales == {x for x in listados if x.endswith(".py")}
