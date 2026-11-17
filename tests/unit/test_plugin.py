import json
import pathlib
import re

import yaml

RAIZ = pathlib.Path(__file__).resolve().parents[2]


def test_manifiesto_del_plugin():
    m = json.loads((RAIZ / ".claude-plugin/plugin.json").read_text())
    assert m["name"] == "trovefy"
    assert m["version"] == "0.1.0"


def test_cada_skill_tiene_frontmatter_valido():
    for skill in (RAIZ / "skills").glob("*/SKILL.md"):
        cabecera = skill.read_text().split("---")[1]
        meta = yaml.safe_load(cabecera)
        assert meta["name"] == skill.parent.name
        assert meta["description"].strip()
        assert "allowed-tools" in meta


def test_cada_agente_tiene_frontmatter_valido():
    agentes = sorted((RAIZ / "agents").glob("*.md"))
    assert {a.stem for a in agentes} >= {"revisor", "nativo"}
    for agente in agentes:
        texto = agente.read_text()
        _, cabecera, cuerpo = texto.split("---", 2)
        meta = yaml.safe_load(cabecera)
        assert meta["name"] == agente.stem
        assert meta["description"].strip()
        herramientas = {t.strip() for t in meta["tools"].split(",")}
        assert herramientas <= {"Read", "Glob", "Grep"}
        assert "VEREDICTO: ok" in cuerpo
        assert "VEREDICTO: corregir" in cuerpo


def _skill_landing() -> tuple[dict, str]:
    texto = (RAIZ / "skills/landing/SKILL.md").read_text()
    _, cabecera, cuerpo = texto.split("---", 2)
    return yaml.safe_load(cabecera), cuerpo


def test_skill_landing_existe_con_sus_herramientas():
    meta, cuerpo = _skill_landing()
    assert meta["name"] == "landing"
    for disparo in ("«landing»", "«página de venta»", "«publicar la landing»"):
        assert disparo in meta["description"], disparo
    herramientas = {t.strip() for t in meta["allowed-tools"].split(",")}
    assert {"Read", "Agent", "Skill",
            "Write(~/.cache/trovefy/landing/**)", "Edit(~/.cache/trovefy/landing/**)"} <= herramientas
    # Solo escribe en el borrador: nada del vault ni de la configuración.
    assert all(not t.startswith(("Write", "Edit")) or "~/.cache/trovefy/landing/" in t for t in herramientas)
    assert (RAIZ / "skills/landing/references/secciones.md").is_file()
    assert "¿Estás en el cerebro?" in cuerpo


def test_skill_landing_nunca_ejecuta_capturar_ni_confirma_por_el_usuario():
    meta, cuerpo = _skill_landing()
    assert "capturar" not in meta["allowed-tools"]
    lineas = [linea for linea in cuerpo.splitlines() if "landing capturar" in linea]
    assert lineas, "la skill tiene que darle al usuario la orden de capturar"
    for linea in lineas:  # cada mención dice que la lanza el usuario, en su terminal
        assert "él" in linea and "terminal" in linea, linea
        assert "nunca lo ejecutas" in linea or "tú no la ejecutas" in linea, linea
    # La confirmación vive fuera del vault (F1-1): la skill no nombra la copia antigua del vault ni escribe la
    # ruta literal del directorio de configuración en ninguna orden (el hook bloquea esa ruta en Bash).
    assert "pantallas-confirmadas.yaml" not in cuerpo
    assert "configuración de trovefy, fuera del cerebro" in cuerpo
    assert "config/evidencia/p05-diseno-contenido-<fecha>.png" in cuerpo and "90 días" in cuerpo
    assert "nunca escribes ni editas su confirmación" in cuerpo
    assert "nunca respondes «sí» por él" in cuerpo
    assert "Nunca cambies `TROVEFY_VAULT`" in cuerpo


SEGUROS_LANDING = ("estado", "medios", "preparar", "guardar", "validar", "texto", "nativo", "qa", "resena")


def _subcomandos_landing() -> set[str]:
    import argparse

    from trovefy import landing_cli

    p = argparse.ArgumentParser()
    landing_cli._configurar(p)
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    return set(sub.choices)


def test_skill_landing_preautoriza_solo_los_subcomandos_seguros():
    """M5: sonda, capturar y publicar los lanza el usuario en su terminal: no van en allowed-tools."""
    meta, _ = _skill_landing()
    herramientas = {t.strip() for t in meta["allowed-tools"].split(",")}
    landing = {t for t in herramientas if t.startswith("Bash(trovefy landing")}
    assert landing == {f"Bash(trovefy landing {s} *)" for s in SEGUROS_LANDING}
    reales = _subcomandos_landing()
    assert set(SEGUROS_LANDING) <= reales  # cada uno existe en `trovefy landing --help`
    assert reales - set(SEGUROS_LANDING) == {"sonda", "capturar", "publicar"}
    for peligroso in ("sonda", "capturar", "publicar"):
        assert peligroso not in meta["allowed-tools"]


def test_skill_landing_decide_la_sonda_por_estado_y_guia_el_dominio():
    """M4: la sonda hace falta según la línea `Hosting:` de `trovefy landing estado` (capacidades_vigentes +
    elegir_hosting), no por si hay un archivo; conectar el dominio es un paso guiado (resolución 25)."""
    _, cuerpo = _skill_landing()
    assert "p05-impultienda-*.json" not in cuerpo
    paso2 = next(linea for linea in cuerpo.splitlines() if linea.startswith("2. **Hosting"))
    assert "`Hosting:`" in paso2 and "no medido" in paso2 and "trovefy landing estado" in paso2
    assert re.search(r"^\d+\. \*\*Conectar el dominio", cuerpo, re.MULTILINE)
    assert "--hosting cloudflare" in cuerpo  # I1: la salida cuando Impultienda no la guarda entera
    assert "--campo-vacio" in cuerpo
    assert "QA-publicada.md" in cuerpo and "-publicada.png" in cuerpo  # M2


def test_skill_landing_cloudflare_sube_solo_la_carpeta_limpia():
    _, cuerpo = _skill_landing()
    assert "landing/<PAIS>/publicar/" in cuerpo and "solo `index.html` y `assets/`" in cuerpo
    assert "nunca la carpeta `landing/<PAIS>/` entera" in cuerpo


def test_skill_landing_sigue_el_cli_real():
    _, cuerpo = _skill_landing()
    for x in ("--version", "--texto-sha256", "Texto-sha256:", "`ok` o `corregir`", "trovefy landing resena",
              "trovefy navegador abrir impultienda https://app.impultienda.ar/", "pixel: pendiente",
              "no toques `assets/`", "restaura solo", "D-01", "Claude nunca escribe en Meta"):
        assert x in cuerpo, x
    assert "/trovefy/*.env" in cuerpo
    assert "aprobado" not in cuerpo  # el veredicto del nativo es ok|corregir (resolución 17)


def test_secciones_de_landing_cubren_todos_los_tipos():
    from trovefy.modelar.esquema import TIPOS_SECCION

    texto = (RAIZ / "skills/landing/references/secciones.md").read_text()
    for tipo in TIPOS_SECCION:
        assert f"**`{tipo}`**" in texto, tipo
    for x in ("D-01", "páginas", "Garantía explícita", "data-tf-formato", "data-tf-garantia"):
        assert x in texto, x
