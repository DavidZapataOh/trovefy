"""Guarda de la regla 1 del plan 19 (resolución 38): nunca una sesión en un panel.

En `scripts/trovefy/{tracking,checkout,embudo}` no aparece ningún camino de sesión: ni `sesion(...)` con un perfil de
panel, ni el `Conductor`, ni `navegador.abrir`, ni `app.impultienda.ar` (no es el panel). Solo se admite nombrar
`app.impultienda.ar` en una línea que dice que no es el panel (para rechazarlo).
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3] / "scripts" / "trovefy"
CARPETAS = ("tracking", "checkout", "embudo")
PROHIBIDOS = ('sesion("impultienda"', 'sesion("meta"', 'sesion("hotmart"', "Conductor", "navegador.abrir")
_SESION_PANEL = re.compile(r"""sesion\(\s*['"](?:impultienda|meta|hotmart|whop)['"]""")


def _archivos():
    for carpeta in CARPETAS:
        yield from sorted((RAIZ / carpeta).rglob("*.py"))


def test_sin_sesion_de_panel():
    archivos = list(_archivos())
    assert archivos
    for archivo in archivos:
        texto = archivo.read_text(encoding="utf-8")
        for prohibido in PROHIBIDOS:
            assert prohibido not in texto, (archivo.name, prohibido)
        assert not _SESION_PANEL.search(texto), archivo.name
        for n, linea in enumerate(texto.splitlines(), 1):
            if "app.impultienda.ar" in linea:
                assert "no es el panel" in linea, (archivo.name, n, linea)
