"""El gate `creativos` de /listo mira la tanda cerrada y revisada (plan 21, Tarea 12)."""

from datetime import UTC, datetime

from trovefy.creativos import manifest, registro
from trovefy.creativos.estaticos import escribir_pieza
from trovefy.listo import GATES
from trovefy.listo.ficha import leer_ficha
from trovefy.listo.gates import Gate, gate_creativos
from trovefy.listo.veredicto import InformeListo, listo_para_activar
from trovefy.vault import frontmatter

from .ejemplos import AHORA, PAIS, P, crear_vault, jpeg, tanda_buena
from .test_manifest import cerrada, preparar_qa


def _gate(vault):
    return gate_creativos(leer_ficha(vault, P, PAIS))


def test_sin_carpeta_no_aplica(tmp_path):
    assert _gate(crear_vault(tmp_path)).estado == "no_aplica"


def test_abierta_falla(tmp_path):
    vault = crear_vault(tmp_path)
    tanda_buena(vault)
    g = _gate(vault)
    assert g.estado == "falla" and "sin cerrar" in g.texto


def test_rehacer_pendiente_falla(tmp_path):
    vault, *_ = cerrada(tmp_path)
    manifest.rehacer(vault, P, PAIS, "t1", ["AD03"], "el texto se corta", AHORA)
    g = _gate(vault)
    assert g.estado == "falla" and "faltan por rehacer: AD03 (el texto se corta)" in g.texto


def test_byte_cambiado_falla(tmp_path):
    vault, _ctx, _cfg, _ficha, carpeta, *_ = cerrada(tmp_path)
    assert _gate(vault).estado == "ok"
    escribir_pieza(vault, carpeta, "AD03", (carpeta / "AD03.mp4").read_bytes() + b"\x00", "mp4")
    g = _gate(vault)
    assert g.estado == "falla" and "cambió después de cerrarla" in g.texto


def test_sin_nativo_falla(tmp_path):
    vault = crear_vault(tmp_path)
    ctx, cfg, ficha, carpeta = tanda_buena(vault)
    preparar_qa(vault, carpeta, ficha, cfg)
    manifest.cerrar_tanda(vault, ctx, ficha, cfg, AHORA, depositar=lambda *_a: "x")
    # un nativo «corregir» posterior sobre la misma tanda deja el gate en falla
    registro.anotar(carpeta, "nativo", {"huella": registro.huella(carpeta, manifest.piezas(ficha)),
                                        "estado": "corregir"}, "- ad-03 · «x» · y", AHORA)
    g = _gate(vault)
    assert g.estado == "falla" and "nativo" in g.texto


def test_todo_ok(tmp_path):
    vault, *_ = cerrada(tmp_path)
    g = _gate(vault)
    assert g.estado == "ok"
    assert g.evidencia == (f"creativos/{PAIS}/t1/QA.md", f"creativos/{PAIS}/t1/qc/contactos-t1-v1.png")


def test_listo_para_activar_con_creativos_ok(tmp_path):
    vault, *_ = cerrada(tmp_path)
    g = _gate(vault)
    gates = tuple(g if c == "creativos" else Gate(c, "ok", f"texto {c}") for c in GATES)
    inf = InformeListo(P, PAIS, datetime(2026, 11, 21, tzinfo=UTC), gates, "BE 10 USD", True)
    assert listo_para_activar(inf)
    meta, _ = frontmatter.leer(vault / "productos" / P / "PRODUCTO.md")
    assert meta["paises"][PAIS]["estado"] == "listo"  # /creativos nunca cambia el estado
    assert jpeg()
