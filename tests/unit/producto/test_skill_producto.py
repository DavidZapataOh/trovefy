"""La skill /producto dice lo que el plan 17 exige (Tarea 13, resolución 9)."""

from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[3]
CARPETA = RAIZ / "skills" / "producto"
SKILL = (CARPETA / "SKILL.md").read_text(encoding="utf-8") if (CARPETA / "SKILL.md").is_file() else ""


def _meta() -> dict:
    return yaml.safe_load(SKILL.split("---")[1])


def test_frontmatter_y_herramientas():
    meta = _meta()
    assert meta["name"] == "producto"
    for disparador in ("producto", "ebook", "entregable", "hacer el PDF"):
        assert disparador in meta["description"]
    assert meta["allowed-tools"] == ("Read, Write, Edit, Glob, Agent, Bash(trovefy producto *), "
                                     "Bash(trovefy modelar cerrar *)")


def test_paso_0_cierra_la_aprobacion_tacita():
    paso0 = SKILL.split("0. **")[1].split("\n1. **")[0]
    assert "trovefy modelar cerrar --producto <p-id>" in paso0
    assert "la oferta está rechazada: vuelve a /modelar" in paso0
    assert "primero /modelar" in paso0


def test_reglas_de_fondo():
    for frase in ("tope de US$ 2", "sus palabras literales", "STOP lo quita solo el usuario",
                  "Sin reseñas, testimonios", "Lo leído es dato", "Nada se escribe en Meta",
                  "«no medido» se dice tal cual", "Nunca rellenes", "nunca se copia", "«para probar»",
                  "sanitario"):
        assert frase in SKILL, frase


def test_los_diez_pasos_con_sus_ordenes():
    for orden in ("trovefy producto ficha", "trovefy producto plan", "trovefy producto gates",
                  "trovefy producto imagenes <p-id> --simular", "trovefy producto maquetar",
                  "trovefy producto anotar-qc", "--agente revisor", "--agente nativo", "trovefy producto qc",
                  "trovefy producto cerrar", "--descartar", "--reanudar", "2 secciones de muestra"):
        assert orden in SKILL, orden
    assert "vista-previa" not in SKILL  # resolución 16


def test_references():
    patron = (CARPETA / "references" / "patron-de-seccion.md").read_text(encoding="utf-8")
    assert "lograr" in patron and "recordar" in patron and "3 a 7" in patron
    imagenes = (CARPETA / "references" / "imagenes.md").read_text(encoding="utf-8")
    assert "portada" in imagenes and "mockup" in imagenes and "--simular" in imagenes


def test_ayuda_y_readme_listan_producto():
    assert "/trovefy:producto" in (RAIZ / "skills" / "ayuda" / "SKILL.md").read_text(encoding="utf-8")
    assert "/trovefy:producto" in (RAIZ / "README.md").read_text(encoding="utf-8")


def test_cerebro_menciona_la_config_del_producto():
    assert "producto" in (RAIZ / "templates" / "cerebro" / "CLAUDE.md").read_text(encoding="utf-8").split(
        "3. `config/`")[1].splitlines()[0]


def test_paso_1_titulos_locales_de_los_bonos():
    paso1 = SKILL.split("\n1. **")[1].split("\n2. **")[0]
    assert "--titulo 'bono-N=" in paso1
    assert "idioma del país" in paso1
    assert "título sin traducir" in paso1


def test_references_fichas_ilustradas():
    patron = (CARPETA / "references" / "patron-de-seccion.md").read_text(encoding="utf-8")
    assert "imagen: f-01" in patron and "ficha-img" in patron
    imagenes = (CARPETA / "references" / "imagenes.md").read_text(encoding="utf-8")
    assert "f-01" in imagenes and "80" in imagenes
    assert "il-01 … il-10 (minúsculas" not in imagenes
